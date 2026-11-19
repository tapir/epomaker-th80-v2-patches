#!/usr/bin/env python3
"""Patch the vendor image per patch/patches.py and patch/hooks/, write patch/build/.

Output is patch/build/th80.bin (flash with tools/flash_boot.py) and
patch/build/review.dis (disassembly of every patched region and of the hook blob).
"""

import hashlib
import importlib.util
import re
import sys
import tempfile
from pathlib import Path

from rv import MATTR, OBJDUMP, decode_call, decode_jal, disassemble, jal, run, tool
from rv import call as rv_call

ROOT = Path(__file__).resolve().parent.parent
PATCH_DIR = ROOT / "patch"
HOOKS_DIR = PATCH_DIR / "hooks"
OUT_DIR = PATCH_DIR / "build"
IMAGE_PATH = ROOT / "firmware/3720_v107.bin"
IMAGE_SHA256 = "44cf45c9da7a45cea2fa6b340d3492190dc904030791ba5c7b70022079d70550"

BOOT_END = 0x5000  # bootloader plus the 0x4000 flag page
APP_END = 0x60000  # end of the application region
RESERVED_END = 0x5400
# 0x5400-0x10ef7 is .highcode: the startup copies it to 0x20000200 and executes it there,
# so its flash addresses are not execution addresses.
HIGHCODE = (RESERVED_END, 0x10EF8)
RAM_OFFSET = 0x1FFFAE00  # RAM address = flash address + this
# Whatever the boot, the app startup or the boot-flag handling depends on.
# 0x5000-0x5203 is a RAM image the startup copies to 0x20000000 and runs there.
FORBIDDEN = [
    (0x0000, BOOT_END, "vendor bootloader and its 0x4000 flag page"),
    (0x5000, RESERVED_END, "app reset entry, startup copy source, boot-checked tag"),
    (0x550A, 0x5874, "the firmware's flash erase/write routine"),
    (HIGHCODE[1], 0x10F40, "first-stage startup: sets gp/sp, copies .highcode, jumps to RAM"),
    (0x11E1E, 0x11F30, "SetSysClock"),
    (0x13742, 0x13766, "writes the dev_id word into the boot's flag page at 0x4004"),
    (0x19C74, 0x19CEE, "stock enter-boot routine: erases the boot flag and config pages"),
    (0x1BDF4, 0x1BE4C, "main() up to the hook site at 0x1be4c"),
]
SRAM = (0x20000000, 0x20018000)
# The only RAM verified unused once main() runs: the RAM copy of __highcode_init, which runs
# once before main() and is never called again. Nothing zeroes it for hooks; they clear
# their own .bss (hook_call does).
HOOK_RAM_WINDOW = (0x20000150, 0x20000200)
# Large hook buffers (.bufram, never zeroed): RAM past the firmware's .bss (ends 0x20013c9f),
# where newlib's heap starts. Only rand() mallocs, once, 24 bytes. The stack grows down from
# 0x20018000, its deepest known frame is a 4 KiB flash-page buffer; 8 KiB stay for it.
BUF_RAM_WINDOW = (0x20013D00, 0x20016000)
DEFAULT_HOOK_BASE = 0x3F000

# -mno-relax and -msmall-data-limit=0 keep generated code off gp, which the firmware owns.
CFLAGS = [
    "-march=rv32imac",
    "-mabi=ilp32",
    "-mcmodel=medany",
    "-Os",
    "-ffreestanding",
    "-fno-builtin",
    "-nostdlib",
    "-nostartfiles",
    "-msmall-data-limit=0",
    "-mno-relax",
    "-ffunction-sections",
    "-fdata-sections",
    "-Wall",
    "-Wextra",
    "-Werror",
]


def load_image():
    image = IMAGE_PATH.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    if digest != IMAGE_SHA256:
        raise RuntimeError(f"{IMAGE_PATH}: sha256 {digest}, pinned {IMAGE_SHA256}")
    return image


def load_config():
    sys.path.insert(0, str(PATCH_DIR))
    spec = importlib.util.spec_from_file_location("patches", PATCH_DIR / "patches.py")
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def resolve(patches, syms):
    resolved = []
    for patch in patches:
        try:
            new = patch.new(syms) if callable(patch.new) else patch.new
        except KeyError as exc:
            raise RuntimeError(f"patch at {patch.addr:#x}: no hook symbol {exc}") from None
        if not isinstance(new, (bytes, bytearray)):
            raise RuntimeError(f"patch at {patch.addr:#x}: new is {type(new).__name__}, want bytes")
        resolved.append(patch._replace(new=bytes(new)))
    return resolved


def exec_addr(addr):
    """Where the code at flash `addr` runs: .highcode runs from its RAM copy."""
    return addr + RAM_OFFSET if HIGHCODE[0] <= addr < HIGHCODE[1] else addr


def far_call_redirect(patch):
    """(rd, old target), (rd, new target) when the patch replaces one auipc+jalr call with
    another, both decoded where the code executes."""
    old = decode_call(exec_addr(patch.addr), patch.old)
    new = decode_call(exec_addr(patch.addr), patch.new)
    return (old, new) if old and new else None


def call_redirect(patch):
    """(rd, old target), (rd, new target) when the patch replaces one jal with another."""
    old = decode_jal(patch.addr, patch.old)
    new = decode_jal(patch.addr, patch.new)
    return (old, new) if old and new else None


def validate(image, patches, blob_range=(0, 0)):
    prev_end = 0
    for patch in sorted(patches, key=lambda p: p.addr):
        end = patch.addr + len(patch.old)
        where = f"patch at {patch.addr:#x} ({patch.why})"
        if not patch.old:
            raise RuntimeError(f"{where}: empty old bytes")
        if patch.addr < 0 or end > len(image):
            raise RuntimeError(f"{where}: {patch.addr:#x}-{end:#x} is outside the image")
        if end > APP_END:
            raise RuntimeError(f"{where}: ends at {end:#x}, past the app region end {APP_END:#x}")
        for low, high, reason in FORBIDDEN:
            if patch.addr < high and end > low:
                raise RuntimeError(
                    f"{where}: {patch.addr:#x}-{end:#x} overlaps reserved {low:#x}-{high - 1:#x}"
                    f" ({reason})"
                )
        if patch.addr < prev_end:
            raise RuntimeError(f"{where}: overlaps the previous patch ending at {prev_end:#x}")
        prev_end = end
        if image[patch.addr:end] != patch.old:
            raise RuntimeError(
                f"{where}: old {patch.old.hex(' ')} != image {image[patch.addr:end].hex(' ')}"
            )
        if len(patch.new) != len(patch.old):
            raise RuntimeError(f"{where}: new is {len(patch.new)} bytes, old is {len(patch.old)}")
        redirect = call_redirect(patch)
        new_jal = decode_jal(patch.addr, patch.new)
        calls_blob = bool(new_jal) and blob_range[0] <= new_jal[1] < blob_range[1]
        if new_jal and not redirect and not calls_blob:
            raise RuntimeError(
                f"{where}: writes a jal to {new_jal[1]:#x}, outside the hook blob "
                f"{blob_range[0]:#x}-{blob_range[1] - 1:#x}"
            )
        if HIGHCODE[0] <= patch.addr < HIGHCODE[1]:
            if redirect or calls_blob:
                raise RuntimeError(
                    f"{where}: calls a hook from .highcode, which executes at "
                    f"{patch.addr + RAM_OFFSET:#x}; a jal built for the flash address lands on "
                    "garbage, and RAM code cannot reach the flash hook blob anyway"
                )
            if not patch.ram_code:
                raise RuntimeError(
                    f"{where}: sits in .highcode ({HIGHCODE[0]:#x}-{HIGHCODE[1] - 1:#x}), which "
                    f"runs from RAM at {patch.addr + RAM_OFFSET:#x}; set ram_code=True once the "
                    "patch's address arithmetic accounts for that"
                )
        if redirect:
            (old_rd, _), (new_rd, new_target) = redirect
            if old_rd != new_rd:
                raise RuntimeError(f"{where}: replaces jal rd={old_rd} with jal rd={new_rd}")
            if not blob_range[0] <= new_target < blob_range[1]:
                raise RuntimeError(
                    f"{where}: new call target {new_target:#x} is outside the hook blob "
                    f"{blob_range[0]:#x}-{blob_range[1] - 1:#x}"
                )
        far = far_call_redirect(patch)
        if far:
            (old_rd, _), (new_rd, new_target) = far
            if old_rd != 1 or new_rd != 1:
                raise RuntimeError(f"{where}: far call rd={old_rd} -> rd={new_rd}, want ra both times")
            if not blob_range[0] <= new_target < blob_range[1]:
                raise RuntimeError(
                    f"{where}: new far-call target {new_target:#x} is outside the hook blob "
                    f"{blob_range[0]:#x}-{blob_range[1] - 1:#x}"
                )
    return sorted(patches, key=lambda p: p.addr)


def elf_sections(elf):
    sections = {}
    for line in run(tool("readelf"), "-SW", elf).splitlines():
        m = re.match(
            r"\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+(\S+)\s*(\S*)",
            line,
        )
        if m and m.group(1).startswith("."):
            sections[m.group(1)] = (int(m.group(3), 16), int(m.group(5), 16), m.group(7))
    return sections


def elf_symbols(elf):
    syms = {}
    for line in run(tool("nm"), "-n", elf).splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1].isupper() and parts[2] not in ("HOOK_BASE", "HOOK_RAM", "BUF_RAM"):
            syms[parts[2]] = int(parts[0], 16)
    return syms


def check_ram(name, addr, size, base, window):
    """A hook RAM section must start at its configured base and stay inside its window."""
    if base is None:
        raise RuntimeError(f"hooks need {size} bytes of {name}: set its base in patch/patches.py")
    if addr != base:
        raise RuntimeError(f"hook {name} is at {addr:#x}, not its base {base:#x}")
    if not window[0] <= addr or addr + size > window[1]:
        raise RuntimeError(
            f"hook {name} {addr:#x}-{addr + size - 1:#x} leaves {window[0]:#x}-{window[1] - 1:#x}"
        )


def build_hooks(hooks_dir, hook_base, hook_ram, work, buf_ram=None):
    sources = sorted([*hooks_dir.glob("*.c"), *hooks_dir.glob("*.S")])
    if not sources:
        return b"", {}
    script = hooks_dir / "hooks.ld"
    if not script.is_file():
        raise RuntimeError(f"{script} is missing")

    objs = []
    for source in sources:
        obj = work / f"{source.name}.o"
        run(tool("gcc"), *CFLAGS, "-c", source, "-o", obj)
        objs.append(obj)

    globals_ = set()
    for obj in objs:
        for line in run(tool("nm"), "--defined-only", "--extern-only", obj).splitlines():
            globals_.add(line.split()[2])

    elf = work / "hooks.elf"
    run(
        tool("gcc"),
        *CFLAGS,
        "-T",
        script,
        f"-Wl,-L,{hooks_dir}",
        "-Wl,--gc-sections",
        f"-Wl,--defsym=HOOK_BASE={hook_base:#x}",
        f"-Wl,--defsym=HOOK_RAM={hook_ram or 0:#x}",
        f"-Wl,--defsym=BUF_RAM={buf_ram or 0:#x}",
        # Roots every global hook; --gc-sections still drops static helpers nobody calls.
        *[f"-Wl,--undefined={name}" for name in sorted(globals_)],
        "-o",
        elf,
        *objs,
    )

    sections = elf_sections(elf)
    for name, (_, size, flags) in sections.items():
        if "A" in flags and size and name not in (".text", ".rodata", ".bss", ".bufram"):
            raise RuntimeError(
                f"hook section {name} ({size} bytes) is not allowed: "
                "hooks may only use .text, .rodata, .bss and .bufram"
            )
    if sections.get(".text", (0,))[0] != hook_base:
        raise RuntimeError(f"linker script did not place hook .text at {hook_base:#x}")
    for name, base, window in ((".bss", hook_ram, HOOK_RAM_WINDOW), (".bufram", buf_ram, BUF_RAM_WINDOW)):
        addr, size, _ = sections.get(name, (0, 0, ""))
        if size:
            check_ram(name, addr, size, base, window)

    blob_path = work / "hooks.bin"
    run(
        tool("objcopy"),
        "-O",
        "binary",
        "-j",
        ".text",
        "-j",
        ".rodata",
        "--gap-fill=0xFF",
        elf,
        blob_path,
    )
    blob = blob_path.read_bytes()

    if "(gp)" in run(OBJDUMP, "-d", MATTR, elf):
        raise RuntimeError("hook code addresses data through gp, which the firmware owns")

    return blob, elf_symbols(elf)


def assemble(image, patches, blob, hook_base):
    out = bytearray(image)
    for patch in patches:
        out[patch.addr : patch.addr + len(patch.new)] = patch.new
    if blob:
        out += b"\xFF" * (hook_base - len(out))
        out += blob
    return bytes(out)


def review(out, patches, blob, hook_base):
    parts = []
    for patch in patches:
        in_ram = HIGHCODE[0] <= patch.addr < HIGHCODE[1]
        low, high = HIGHCODE if in_ram else (0, len(out))
        start = max(low, patch.addr - 16)
        end = min(high, patch.addr + len(patch.old) + 16)
        delta = RAM_OFFSET if in_ram else 0
        header = f"; patch @ flash {patch.addr:#07x}"
        if in_ram:
            header += f" = ram {patch.addr + delta:#08x}"
        parts.append(f"{header}  {len(patch.old)} B  {patch.why}")
        parts.append(disassemble(start + delta, out[start:end]).rstrip())
    if blob:
        parts.append(f"; hook blob @ {hook_base:#07x}  {len(blob)} B")
        parts.append(disassemble(hook_base, blob).rstrip())
    return "\n".join(parts) + "\n"


def check_output(image, out, patches, blob, hook_base):
    """Assert the only changed bytes are the declared ones; return the changed ranges."""
    if out[:RESERVED_END] != image[:RESERVED_END]:
        raise RuntimeError(f"output differs from the image below {RESERVED_END:#x}")
    spans = [(p.addr, p.addr + len(p.new)) for p in patches]
    if blob:
        spans.append((hook_base, hook_base + len(blob)))
        if out[len(image) : hook_base] != b"\xFF" * (hook_base - len(image)):
            raise RuntimeError(f"gap up to HOOK_BASE {hook_base:#x} is not all 0xFF")
        if out[hook_base:] != blob:
            raise RuntimeError(f"hook blob is not at HOOK_BASE {hook_base:#x}")
    regions = []
    for offset in range(len(image)):
        if image[offset] == out[offset]:
            continue
        if not any(low <= offset < high for low, high in spans):
            raise RuntimeError(f"byte {offset:#x} changed outside every declared patch")
        if regions and regions[-1][1] == offset:
            regions[-1][1] = offset + 1
        else:
            regions.append([offset, offset + 1])
    return regions


def summarise(out, patches, blob, hook_base, regions):
    print(f"image    {IMAGE_PATH.relative_to(ROOT)}  {IMAGE_PATH.stat().st_size} bytes")
    print(f"patches  {len(patches)}")
    for patch in patches:
        print(f"  {patch.addr:#07x}  {len(patch.old)} B  {patch.why}")
        print(f"    {patch.old.hex(' ')}  ->  {patch.new.hex(' ')}")
        redirect = call_redirect(patch)
        if redirect:
            (old_rd, old_target), (new_rd, new_target) = redirect
            print(f"    jal rd={old_rd} {old_target:#x} -> jal rd={new_rd} {new_target:#x}")
        far = far_call_redirect(patch)
        if far:
            (_, old_target), (_, new_target) = far
            print(f"    call at {exec_addr(patch.addr):#x}: {old_target:#x} -> {new_target:#x}")
    if blob:
        print(f"hooks    {hook_base:#07x}-{hook_base + len(blob) - 1:#07x}  {len(blob)} bytes")
    print(f"changed  {len(regions)} range(s)")
    for low, high in regions:
        print(f"  {low:#07x}-{high - 1:#07x}  {high - low} B")
    print(f"output   {(OUT_DIR / 'th80.bin').relative_to(ROOT)}  {len(out)} bytes")
    print(f"sha256   {hashlib.sha256(out).hexdigest()}")


def selftest():
    image = load_image()
    if assemble(image, [], b"", DEFAULT_HOOK_BASE) != image:
        raise RuntimeError("empty build is not identical to the image")

    config = load_config()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        hooks = work / "hooks"
        hooks.mkdir()
        if build_hooks(hooks, DEFAULT_HOOK_BASE, None, work) != (b"", {}):
            raise RuntimeError("an empty hooks directory produced a blob")

    def rejects(*patches, blob_range=(0, 0)):
        try:
            validate(image, list(patches), blob_range)
        except RuntimeError:
            return
        raise RuntimeError(f"validation accepted {[p.why for p in patches]}")

    def rejects_output(out):
        try:
            check_output(image, out, [], b"", DEFAULT_HOOK_BASE)
        except RuntimeError:
            return
        raise RuntimeError("output check accepted a stray change")

    keep = config.Patch(0x19000, image[0x19000:0x19004], image[0x19000:0x19004], "identity")
    validate(image, [keep])
    if check_output(image, image, [], b"", DEFAULT_HOOK_BASE) != []:
        raise RuntimeError("identical output reported changes")
    if assemble(image, [keep], b"", DEFAULT_HOOK_BASE) != image:
        raise RuntimeError("identity patch changed the image")

    def at(addr, why, **kwargs):
        return config.Patch(addr, image[addr : addr + 4], image[addr : addr + 4], why, **kwargs)

    for addr, why in [
        (0x0100, "bootloader"),
        (0x5202, "startup copy source"),
        (0x550A, "flash erase/write routine"),
        (0x10F00, "first-stage startup"),
        (0x11E1E, "SetSysClock"),
        (0x13742, "dev_id into the boot flag page"),
        (0x19C74, "stock enter-boot"),
        (0x1BDF4, "main up to the hook site"),
    ]:
        rejects(at(addr, why))
    rejects(keep, at(0x19002, "overlap"))
    rejects(config.Patch(0x19000, bytes(4), bytes(4), "stale old"))
    rejects(config.Patch(0x19000, image[0x19000:0x19004], bytes(8), "wrong length"))

    hook_blob = (0x3F000, 0x3F010)
    call = image[0x1BE4C:0x1BE50]
    site = config.Patch(0x1BE4C, call, jal(0x1BE4C, 0x3F004), "redirect")
    validate(image, [site], hook_blob)
    rejects(config.Patch(0x1BE4C, call, jal(0x1BE4C, 0x3F004, rd=5), "rd"), blob_range=hook_blob)
    rejects(config.Patch(0x1BE4C, call, jal(0x1BE4C, 0x8000), "outside blob"), blob_range=hook_blob)

    hookify = config.Patch(0x19000, image[0x19000:0x19004], jal(0x19000, 0x3F004), "hookify")
    validate(image, [hookify], hook_blob)
    ram_site = image[0x6364:0x6368]
    rejects(config.Patch(0x6364, ram_site, jal(0x6364, 0x3F004), "ram redirect"), blob_range=hook_blob)
    rejects(at(0x6000, "ram code, unflagged"))
    validate(image, [at(0x6000, "ram code, flagged", ram_code=True)])
    ram_call = config.Patch(0x8000, image[0x8000:0x8004], jal(0x8000, 0x3F004), "call in RAM code")
    rejects(ram_call, blob_range=hook_blob)

    far_site = image[0x7830:0x7838]  # RAM code calling flash 0x199e8 with auipc+jalr
    far_new = rv_call(0x7830 + RAM_OFFSET, 0x3F004)
    validate(image, [config.Patch(0x7830, far_site, far_new, "far call", ram_code=True)], hook_blob)
    rejects(config.Patch(0x7830, far_site, far_new, "far call, unflagged"), blob_range=hook_blob)
    rejects(config.Patch(0x7830, far_site, rv_call(0x7830, 0x3F004), "far call at the flash address",
                         ram_code=True), blob_range=hook_blob)
    rejects(config.Patch(0x7830, far_site, rv_call(0x7830 + RAM_OFFSET, 0x8000), "far call outside",
                         ram_code=True), blob_range=hook_blob)

    rejects(config.Patch(0x19000, image[0x19000:0x19004], jal(0x19000, 0x8000), "hookify outside"),
            blob_range=hook_blob)

    check_ram(".bufram", 0x20013E00, 0xAE0, 0x20013E00, BUF_RAM_WINDOW)
    for addr, size, base in [(0x20013E00, 0xAE0, None), (0x20013E04, 0xAE0, 0x20013E00),
                             (0x20013C00, 0x10, 0x20013C00), (0x20015F00, 0x200, 0x20015F00)]:
        try:
            check_ram(".bufram", addr, size, base, BUF_RAM_WINDOW)
        except RuntimeError:
            continue
        raise RuntimeError(f"check_ram accepted {addr:#x}+{size:#x} (base {base})")

    stray = bytearray(image)
    stray[0x8000] ^= 0xFF
    rejects_output(bytes(stray))


def main(argv):
    if "--selftest" in argv:
        selftest()
        print("selftest OK: empty build is byte-identical to the original image")
        return

    image = load_image()
    config = load_config()
    hook_base = getattr(config, "HOOK_BASE", DEFAULT_HOOK_BASE)
    hook_ram = getattr(config, "HOOK_RAM", None)
    buf_ram = getattr(config, "BUF_RAM", None)
    if hook_base < len(image) or hook_base % 4:
        raise RuntimeError(
            f"HOOK_BASE {hook_base:#x} must be >= the image end ({len(image):#x}) "
            "and 4-byte aligned"
        )
    if hook_ram is not None and (hook_ram % 4 or not HOOK_RAM_WINDOW[0] <= hook_ram < HOOK_RAM_WINDOW[1]):
        raise RuntimeError(
            f"HOOK_RAM {hook_ram:#x} must be 4-byte aligned and inside "
            f"{HOOK_RAM_WINDOW[0]:#x}-{HOOK_RAM_WINDOW[1] - 1:#x}, the only RAM known to be "
            "unused after startup"
        )

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        blob, syms = build_hooks(HOOKS_DIR, hook_base, hook_ram, work, buf_ram)
        blob_range = (hook_base, hook_base + len(blob))
        if blob_range[1] > APP_END:
            raise RuntimeError(f"hook blob ends at {blob_range[1]:#x}, past {APP_END:#x}")
        patches = validate(image, resolve(config.PATCHES, syms), blob_range)
        out = assemble(image, patches, blob, hook_base)
        if len(out) > APP_END:
            raise RuntimeError(f"output ends at {len(out):#x}, past the app region end")
        regions = check_output(image, out, patches, blob, hook_base)
        text = review(out, patches, blob, hook_base)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "th80.bin").write_bytes(out)
    (OUT_DIR / "review.dis").write_text(text)
    summarise(out, patches, blob, hook_base, regions)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except RuntimeError as exc:
        sys.exit(f"error: {exc}")

"""RISC-V RV32 encoders (jal, auipc+jalr call, auipc+addi address) for firmware patches, plus
raw-bytes disassembly."""

import re
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLCHAIN = ROOT / "toolchain/riscv-none-elf-gcc/bin/riscv-none-elf-"
OBJDUMP = "llvm-objdump"  # LLVM >= 17: the first with the WCH (+xwchc) extension
# The CPU is a QingKe RISC-V3C: without +xwchc the decoder misreads its compressed forms.
MATTR = "--mattr=+m,+a,+c,+xwchc,+zba,+zbb,+zbc,+zbs"


def tool(name):
    return str(TOOLCHAIN) + name


def run(*cmd, timeout=120):
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"{Path(str(cmd[0])).name} failed: {proc.stdout}{proc.stderr}")
    if proc.stderr.strip():
        raise RuntimeError(f"{Path(str(cmd[0])).name} was not quiet: {proc.stderr}")
    return proc.stdout


def disassemble(start, data):
    """Decode raw bytes as if they sat at flash address `start`."""
    with tempfile.TemporaryDirectory() as tmp:
        bin_path = Path(tmp) / "chunk.bin"
        bin_path.write_bytes(data)
        obj_path = Path(tmp) / "chunk.o"
        run(tool("objcopy"), "-I", "binary", "-O", "elf32-littleriscv", bin_path, obj_path)
        # objcopy -I binary stores the bytes in .data; any other section llvm-objdump
        # dumps is ELF metadata decoded as instruction garbage.
        text = run(OBJDUMP, "-D", "--section=.data", MATTR, f"--adjust-vma={start:#x}", obj_path)
    lines = text.split("Disassembly of section .data:\n", 1)[-1].splitlines()
    # Symbol annotations carry the temp file name; the addresses are what matters.
    kept = [ln for ln in lines if "<" not in ln or not ln.rstrip().endswith(">:")]
    return "\n".join(re.sub(r" <[^>]*>", "", ln) for ln in kept).lstrip("\n") + "\n"


def jal(src, dst, rd=1):
    offset = dst - src
    if offset & 1:
        raise ValueError(f"jal {src:#x} -> {dst:#x}: offset {offset:#x} is not 2-byte aligned")
    if not -(1 << 20) <= offset <= (1 << 20) - 2:
        raise ValueError(f"jal {src:#x} -> {dst:#x}: offset {offset:#x} is outside +-1 MiB")
    imm = offset & 0x1FFFFF
    word = (
        ((imm >> 20) & 1) << 31
        | ((imm >> 1) & 0x3FF) << 21
        | ((imm >> 11) & 1) << 20
        | ((imm >> 12) & 0xFF) << 12
        | (rd & 0x1F) << 7
        | 0x6F
    )
    return struct.pack("<I", word)


def decode_jal(src, code):
    """(rd, target) for a 4-byte jal placed at `src`, or None."""
    if len(code) != 4:
        return None
    word = struct.unpack("<I", code)[0]
    if word & 0x7F != 0x6F:
        return None
    imm = (
        ((word >> 31) & 1) << 20
        | ((word >> 21) & 0x3FF) << 1
        | ((word >> 20) & 1) << 11
        | ((word >> 12) & 0xFF) << 12
    )
    if imm & (1 << 20):
        imm -= 1 << 21
    return (word >> 7) & 0x1F, src + imm


def j(src, dst):
    return jal(src, dst, rd=0)


def call(src, dst):
    """8-byte `auipc ra, hi` + `jalr ra, lo(ra)` at `src` calling `dst`; reaches any address."""
    offset = (dst - src) & 0xFFFFFFFF
    if dst & 1:
        raise ValueError(f"call {src:#x} -> {dst:#x}: odd target")
    hi = ((offset + 0x800) >> 12) & 0xFFFFF
    lo = (offset - (hi << 12)) & 0xFFF
    return struct.pack("<II", hi << 12 | 1 << 7 | 0x17, lo << 20 | 1 << 15 | 1 << 7 | 0x67)


def decode_call(src, code):
    """(rd, target) for an 8-byte `auipc rX` + `jalr rd, imm(rX)` placed at `src`, or None."""
    if len(code) != 8:
        return None
    auipc, jalr = struct.unpack("<II", code)
    reg = (auipc >> 7) & 0x1F
    if auipc & 0x7F != 0x17 or jalr & 0x707F != 0x67 or (jalr >> 15) & 0x1F != reg:
        return None
    lo = jalr >> 20
    if lo & 0x800:
        lo -= 0x1000
    return (jalr >> 7) & 0x1F, (src + (auipc & 0xFFFFF000) + lo) & 0xFFFFFFFF


def la(src, dst, rd):
    """8-byte `auipc rd, hi` + `addi rd, rd, lo` at `src` loading the address `dst`."""
    offset = (dst - src) & 0xFFFFFFFF
    hi = ((offset + 0x800) >> 12) & 0xFFFFF
    lo = (offset - (hi << 12)) & 0xFFF
    return struct.pack("<II", hi << 12 | rd << 7 | 0x17, lo << 20 | rd << 15 | rd << 7 | 0x13)


def decode_la(src, code):
    """(rd, address) for an 8-byte `auipc rd` + `addi rd, rd, imm` placed at `src`, or None."""
    if len(code) != 8:
        return None
    auipc, addi = struct.unpack("<II", code)
    rd = (auipc >> 7) & 0x1F
    if auipc & 0x7F != 0x17 or addi & 0x707F != 0x13 or (addi >> 15) & 0x1F != rd or (addi >> 7) & 0x1F != rd:
        return None
    lo = addi >> 20
    if lo & 0x800:
        lo -= 0x1000
    return rd, (src + (auipc & 0xFFFFF000) + lo) & 0xFFFFFFFF


LINE = re.compile(r"^\s*([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(.*)$")

CASES = [
    (0x5000, 0x5000, 1),
    (0x5000, 0x5004, 1),
    (0x5000, 0x53FC, 1),
    (0x8000, 0x5000, 1),
    (0x5000, 0x104FFE, 1),
    (0x105000, 0x5000, 1),
    (0x5000, 0x5004, 0),
    (0x5000, 0x5100, 5),
]

REJECTED = [(0x5000, 0x5001), (0x5000, 0x105002), (0x105002, 0x5000)]

# RAM code -> flash (wraps through 0), flash -> RAM, both directions of the 0x800 rounding.
CALLS = [(0x20002630, 0x3F000), (0x20002630, 0x3F7FE), (0x20002630, 0x3F800), (0x3F000, 0x20004DEC),
         (0x1BF32, 0x20007FEA), (0x5000, 0x5000)]


def decode(dis, addr):
    for line in dis.splitlines():
        m = LINE.match(line)
        if m and int(m.group(1), 16) == addr:
            target = re.search(r"0x([0-9a-f]+)", m.group(3))
            return m.group(2), int(target.group(1), 16) if target else None
    raise RuntimeError(f"nothing decoded at {addr:#x}:\n{dis}")


def selftest():
    for src, dst, rd in CASES:
        base = src & ~3
        blob = b"\x13\x00\x00\x00" * ((src - base) // 4) + jal(src, dst, rd)
        mnemonic, target = decode(disassemble(base, blob), src)
        if target != dst:
            raise RuntimeError(f"jal {src:#x} -> {dst:#x} decoded as {mnemonic} {target:#x}")
        if (mnemonic == "j") != (rd == 0):
            raise RuntimeError(f"jal rd={rd} decoded as {mnemonic!r}")
        if decode_jal(src, jal(src, dst, rd)) != (rd, dst):
            raise RuntimeError(f"decode_jal disagrees on {src:#x} -> {dst:#x} rd={rd}")
    for src, dst in REJECTED:
        try:
            jal(src, dst)
        except ValueError:
            continue
        raise RuntimeError(f"jal {src:#x} -> {dst:#x} was accepted")
    if j(0x5000, 0x5004) != jal(0x5000, 0x5004, 0):
        raise RuntimeError("j() disagrees with jal(rd=0)")
    if decode_jal(0x5000, b"\x13\x00\x00\x00") is not None:
        raise RuntimeError("decode_jal accepted a nop")
    for src, dst in CALLS:
        code = call(src, dst)
        if decode_call(src, code) != (1, dst):
            raise RuntimeError(f"call {src:#x} -> {dst:#x} decodes as {decode_call(src, code)}")
        dis = disassemble(src, code)
        lines = [m for m in map(LINE.match, dis.splitlines()) if m]
        if [m.group(2) for m in lines] != ["auipc", "jalr"]:
            raise RuntimeError(f"call {src:#x} -> {dst:#x} disassembles as:\n{dis}")
        hi = int(re.search(r"0x([0-9a-f]+)", lines[0].group(3)).group(1), 16)
        lo = re.search(r"(-?0x[0-9a-f]+)\(ra\)", lines[1].group(3))
        lo = int(lo.group(1), 16) if lo else 0  # llvm prints a zero offset as plain `jalr ra`
        if (src + (hi << 12) + lo) & 0xFFFFFFFF != dst:
            raise RuntimeError(f"llvm-objdump reads call {src:#x} -> {dst:#x} differently:\n{dis}")
    stock = bytes.fromhex("977001e0e780803b")  # firmware's call of 0x199e8 at RAM 0x20002630
    if decode_call(0x20002630, stock) != (1, 0x199E8):
        raise RuntimeError(f"decode_call misreads the stock call: {decode_call(0x20002630, stock)}")
    for src, dst in CALLS:
        code = la(src, dst, 11)
        if decode_la(src, code) != (11, dst) or decode_call(src, code) is not None:
            raise RuntimeError(f"la {src:#x} -> {dst:#x} decodes as {decode_la(src, code)}")
        dis = disassemble(src, code)
        lines = [m for m in map(LINE.match, dis.splitlines()) if m]
        if [m.group(2) for m in lines] not in (["auipc", "addi"], ["auipc", "mv"]):
            raise RuntimeError(f"la {src:#x} -> {dst:#x} disassembles as:\n{dis}")
        hi = int(re.search(r"0x([0-9a-f]+)", lines[0].group(3)).group(1), 16)
        lo = re.search(r"a1, a1(?:, (-?0x[0-9a-f]+))?$", lines[1].group(3).strip())
        lo = lo and int(lo.group(1) or "0", 16)  # llvm prints a zero offset as `mv a1, a1`
        if lo is None or (src + (hi << 12) + lo) & 0xFFFFFFFF != dst:
            raise RuntimeError(f"llvm-objdump reads la {src:#x} -> {dst:#x} differently:\n{dis}")
    stock = bytes.fromhex("976503e093858500")  # the BLE name address at RAM 0x200076ec
    if decode_la(0x200076EC, stock) != (11, 0x3D6F4):
        raise RuntimeError(f"decode_la misreads the stock load: {decode_la(0x200076EC, stock)}")
    print(f"rv selftest OK: {len(CASES)} jal encodings, {len(CALLS)} calls and {len(CALLS)} address "
          f"loads decoded correctly, {len(REJECTED)} rejected")


if __name__ == "__main__":
    selftest()

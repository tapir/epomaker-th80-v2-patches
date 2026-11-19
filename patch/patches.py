"""Patches and hook placement for the vendor image; consumed by build.py."""

from pathlib import Path
from typing import Callable, NamedTuple

from rv import call, decode_call, jal


class Patch(NamedTuple):
    addr: int
    old: bytes
    new: bytes | Callable[[dict[str, int]], bytes]
    why: str
    ram_code: bool = False  # addr is in .highcode (flash 0x5400-0x10ef7, executed from RAM)


IMAGE = (Path(__file__).resolve().parent.parent / "firmware/3720_v107.bin").read_bytes()

# Keymap layers: 128 slots x 4 bytes, slot = column * 6 + row (columns as in the TH80 pin map).
BASE_LAYER = 0x3CE80
FN_LAYERS = [0x3C080 + n * 0x200 for n in range(7)]
FN_KEY = bytes.fromhex("0a010000")
# 240 bytes copied to RAM gp+0x688 (and saved to 0x60000) whenever that page is blank,
# which every flash makes it.
DEFAULT_SETTINGS = 0x3D080

# Fn+Esc (factory reset) stays until the final build, while the defaults still change.
FN_KEEP = {
    0 * 6 + 0: bytes.fromhex("0a020000"),  # Fn+Esc: factory reset
    1 * 6 + 1: bytes.fromhex("0e000000"),  # Fn+1: Bluetooth device 1
    2 * 6 + 1: bytes.fromhex("0e000100"),  # Fn+2: Bluetooth device 2
    3 * 6 + 1: bytes.fromhex("0e000200"),  # Fn+3: Bluetooth device 3
}


# The CK75SE reads a 3-position mode switch on PB1 (low = BT) and PB2 (low = 2.4G); the TH80
# has the same switch on PB20/PB21, while its PB1 is the Win/Mac switch and PB2 knob A.
# Each site is the pin argument of a GPIO helper call: reads (mode keys 0x9706, switch
# decoder 0x14026), pull-up setup (0x142d6, 0x14566) and the drive-low before sleep.
PB1_SITES = [0x9746, 0x9786, 0x97AA, 0x97E8, 0x1404A, 0x14062, 0x1434C, 0x144B4, 0x144C2, 0x145BC]
PB2_SITES = [0x973C, 0x977C, 0x97A0, 0x97DE, 0x14028, 0x14038, 0x1433C, 0x14496, 0x144A4, 0x145AC]
C_LI_A1 = {1: bytes.fromhex("8545"), 2: bytes.fromhex("8945"), 20: bytes.fromhex("d145"), 21: bytes.fromhex("d545")}


def mode_switch_pin(addr, old_pin, new_pin):
    return Patch(addr, C_LI_A1[old_pin], C_LI_A1[new_pin], f"mode switch: PB{old_pin} -> PB{new_pin}",
                 ram_code=0x5400 <= addr < 0x10EF8)


RAM_OFFSET = 0x1FFFAE00  # .highcode (flash 0x5400-0x10ef7) runs at flash + this
TICK = 0x199E8  # flash function the RAM-code loops call once per 1 kHz key-scan tick
TICK_CALLS = [0x7830, 0x7A7C, 0x7B7E, 0xC698]  # every caller: USB, 2.4G and BT loops


def tick_call(site):
    old = IMAGE[site:site + 8]
    if decode_call(site + RAM_OFFSET, old) != (1, TICK):
        raise RuntimeError(f"{site:#x}: {old.hex()} is not a call of {TICK:#x}")
    return Patch(site, old, lambda syms: call(site + RAM_OFFSET, syms["hook_tick"]),
                 f"key-scan tick: call hook_tick instead of {TICK:#x}", ram_code=True)


def key(usage):
    return bytes([0x00, 0x00, usage, 0x00])


def consumer(usage):
    return bytes([0x03, 0x00, usage & 0xFF, usage >> 8])


def base_key(col, row, old, new, why):
    return Patch(BASE_LAYER + 4 * (col * 6 + row), old, new, why)


def fn_layer_cleared(layer):
    """Every Fn combo except FN_KEEP falls through to the base layer."""
    patches = []
    for s in range(128):
        addr = layer + 4 * s
        old = IMAGE[addr:addr + 4]
        if s in FN_KEEP:
            if old != FN_KEEP[s]:
                raise RuntimeError(f"Fn layer {layer:#x} slot {s} is {old.hex()}: misaligned layer?")
        elif old != bytes(4):
            patches.append(Patch(addr, old, bytes(4), f"Fn layer {layer:#x}: clear c{s // 6} r{s % 6}"))
    return patches


PATCHES: list[Patch] = [
    Patch(
        0x1BE4C,
        bytes.fromhex("ef504fa8"),  # jal ra, 0x110d0 (a0 = 4 set at 0x1be4a)
        lambda syms: jal(0x1BE4C, syms["hook_call"]),
        "main: run the early XT32M tune call through hook_call",
    ),
    base_key(14, 1, key(0x49), key(0x4C), "TH80 Delete (CK75SE: Insert)"),
    base_key(10, 5, FN_KEY, key(0xE6), "TH80 right Alt (CK75SE: Fn)"),
    base_key(1, 5, key(0xE3), FN_KEY, "TH80 left Win key: Fn (swapped with Fn by choice)"),
    base_key(11, 5, key(0xE4), key(0xE3), "TH80 Fn key: left Win (CK75SE: right Ctrl)"),
    base_key(13, 0, key(0x4C), consumer(0xE2), "knob press: Mute (no TH80 key; CK75SE: Delete)"),
    base_key(14, 0, bytes(4), consumer(0xE9), "knob clockwise: Volume Up (no TH80 key)"),
    base_key(14, 4, bytes(4), consumer(0xEA), "knob counter-clockwise: Volume Down (no TH80 key)"),
    *(p for layer in FN_LAYERS for p in fn_layer_cleared(layer)),
    Patch(DEFAULT_SETTINGS + 9, b"\x01", b"\x05", "default debounce 5 ms (CK75SE: 1, double presses)"),
    *(mode_switch_pin(a, 1, 20) for a in PB1_SITES),
    *(mode_switch_pin(a, 2, 21) for a in PB2_SITES),
    *(tick_call(a) for a in TICK_CALLS),
    Patch(0x1AA32, bytes.fromhex("eff02fd4"), lambda syms: jal(0x1AA32, syms["hook_led_set"]),
          "command 0x07 (set lighting): through hook_led_set"),
    Patch(0x1AA38, bytes.fromhex("eff00fdd"), lambda syms: jal(0x1AA38, syms["hook_led_get"]),
          "command 0x87 (get lighting): through hook_led_get"),
    # Sharkfin picks the device profile by this id alone: 3573 = TH80 V2, 3720 = CK75SE.
    Patch(0x19D8E, bytes.fromhex("130780f8"), bytes.fromhex("1307500f"), "identify: dev_id low byte 0xF5 (CK75SE: 0x88)"),
    Patch(0x19D94, bytes.fromhex("3947"), bytes.fromhex("3547"), "identify: dev_id high byte 0x0D (CK75SE: 0x0E)"),
]

HOOK_BASE = 0x3F000  # >= image end, 4-byte aligned; .text/.rodata land here
HOOK_RAM = 0x20000180  # knob state; see HOOK_RAM_WINDOW in build.py

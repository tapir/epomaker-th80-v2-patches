#!/usr/bin/env python3
"""Send a command to the TH80 V2 pin scanner (1209:5CA4) and print its status report.

  7E               flash/boot state, PA4 battery ADC, PB0
  7C PA15 PB19 P K LED test: LED power pins (0/1), pattern (1 = LEDs K..K+2 blue, rest
                   dim green; 2 = Esc lit while PB0 is high, F1 blinking; 0 = all off)
  7B               LEDs off, back to scanning
  7F               enter the vendor boot (3151:5057)
  leds BLUE [WHITE] light only these LED indices, e.g. "leds 0,12-13 79" (- = none)
"""
import struct
import sys
import time

import hid


def mv(raw):
    """ADC raw value at -12 dB gain -> millivolts (SDK ADC_VoltConverSignalPGA_MINUS_12dB)."""
    return (raw * 1050 + 256) // 512 - 3 * 1050


def parse_indices(spec):
    """'0,12-13' -> [0, 12, 13]; '-' -> []."""
    out = []
    for part in spec.split(",") if spec != "-" else []:
        lo, _, hi = part.partition("-")
        out += range(int(lo), int(hi or lo) + 1)
    if any(not 0 <= i < 128 for i in out):
        raise SystemExit("LED index out of range 0..127")
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    maps = bytes(0)
    if sys.argv[1] == "leds":
        cmd, args = 0x7C, [1, 1, 3, 0]
        for spec in (sys.argv[2:4] + ["-", "-"])[:2]:
            bits = bytearray(16)
            for idx in parse_indices(spec):
                bits[idx >> 3] |= 1 << (idx & 7)
            maps += bytes(bits)
    else:
        cmd = int(sys.argv[1], 16)
        args = [int(a, 0) for a in sys.argv[2:6]]
        args += [0] * (4 - len(args))

    dev = hid.device()
    dev.open(0x1209, 0x5CA4)
    dev.set_nonblocking(True)
    dev.write(b"\x00" + bytes([cmd, 0x55, 0xAA, 0x55, 0xAA] + args) + maps + bytes(55 - len(maps)))
    status, t0 = None, time.time()
    while status is None and time.time() - t0 < 3:
        try:
            r = dev.read(64)
        except OSError:
            break
        if r and r[0] == 0x5A and r[1] == cmd:
            status = bytes(r)
        elif not r:
            time.sleep(0.001)
    dev.close()
    if status is None:
        print("no status report")
        return 1

    u16 = lambda o: struct.unpack_from("<H", status, o)[0]
    if cmd == 0x7E:
        pa4 = [u16(40 + 2 * i) for i in range(4)]
        print("PA4 ADC at 1/100/300/600 ms: " +
              ", ".join("%d (%d mV)" % (r, mv(r)) for r in pa4))
        print("chip supply (VBAT channel): %d (%d mV)" % (u16(48), mv(u16(48))))
        print("PB0 level: %d" % status[50])
    elif cmd in (0x7C, 0x7B):
        print("args %s, SPI %s, SPI clock gate before: %#04x" % (
            list(status[40:44]), "timeout" if status[44] else "ok", status[45]))
    else:
        print(status[:40].hex(" "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Light chosen side LEDs (0-33, chain order) of the patched firmware, to map their positions.

    sudo python3 tools/side_test.py A [B]   side LEDs A..B blue, the others off
    sudo python3 tools/side_test.py mark W B  side LED W white, side LED B blue
    sudo python3 tools/side_test.py off       back to the stored side-light setting

Test patterns are not stored; replugging also ends them.
"""
import sys
import time

import hid


def send(dev, payload):
    pkt = [0x08, *payload] + [0] * (8 - 1 - len(payload))
    pkt.append(~sum(pkt) & 0xFF)  # 0x07/0x08 carry their checksum in byte 8
    dev.send_feature_report(bytes([0]) + bytes(pkt) + bytes(64 - len(pkt)))
    time.sleep(0.05)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 2
    if argv[0] == "off":
        payload = [0x80]
    elif argv[0] == "mark" and len(argv) == 3:
        payload = [0x82, int(argv[1]), int(argv[2])]
    else:
        first = int(argv[0])
        payload = [0x81, first, int(argv[1]) if len(argv) > 1 else first]
    if any(not 0 <= v <= 33 for v in payload[1:]):
        print("side LEDs are 0-33")
        return 2
    path = next((d["path"] for d in hid.enumerate(0x3151, 0x5056)
                 if d["usage_page"] == 0xFFFF and d["usage"] == 2), None)
    if path is None:
        print("3151:5056 not found")
        return 1
    dev = hid.device()
    dev.open_path(path)
    send(dev, payload)
    dev.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

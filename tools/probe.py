#!/usr/bin/env python3
"""Read-only status of the keyboard firmware (3151:5056) over its vendor interface.

    sudo python3 tools/probe.py
"""
import time

import hid

QUERIES = [
    ("identify", 0x8F),    # 8F <dev_id u32 LE> 00 00 <minor> <major>
    ("profile", 0x84),
    ("debounce", 0x86),    # [1] = ms
    ("lighting", 0x87),    # mode speed brightness flags R G B
    ("side light", 0x88),
]


def query(dev, op):
    pkt = [op, 0, 0, 0, 0, 0, 0]
    pkt.append(~sum(pkt) & 0xFF)  # byte 7 checksum: without it the firmware ignores the query
    dev.send_feature_report(bytes([0]) + bytes(pkt) + bytes(64 - len(pkt)))
    time.sleep(0.05)
    return bytes(dev.get_feature_report(0, 65))[1:]


def main():
    path = next((d["path"] for d in hid.enumerate(0x3151, 0x5056)
                 if d["usage_page"] == 0xFFFF and d["usage"] == 2), None)
    if path is None:
        print("3151:5056 not found (in 2.4G/BT mode it may still be on USB; in boot mode it is 3151:5057)")
        return 1
    dev = hid.device()
    dev.open_path(path)
    for name, op in QUERIES:
        print(f"{name:10s} {query(dev, op)[:12].hex(' ')}")
    r = query(dev, 0x8F)
    dev.close()
    print(f"dev_id {int.from_bytes(r[1:5], 'little')}, firmware v{r[8]}.{r[7]:02d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Switch the keyboard firmware (3151:5056) into the vendor boot (3151:5057) for flashing.

    sudo python3 tools/enter_boot.py
"""
import hid, subprocess, time

VID, PID = 0x3151, 0x5056

def build(payload, total=64):
    p = list(payload) + [0] * (total - len(payload))
    p[7] = (~sum(p[0:7])) & 0xFF
    return bytes(p)

def usbids():
    out = subprocess.run(["lsusb"], capture_output=True, text=True).stdout
    return {l.split()[5]: l for l in out.splitlines() if len(l.split()) > 5}

before = usbids()
print("before:", sorted(before))
path = [d["path"] for d in hid.enumerate(VID, PID) if d.get("interface_number") == 2][0]
dev = hid.device(); dev.open_path(path)
pkt = build([0x7F, 0x55, 0xAA, 0x55, 0xAA])
print("sending boot entry:", pkt[:10].hex(" "))
dev.send_feature_report(b"\x00" + pkt)
dev.close()

for i in range(20):
    time.sleep(1)
    now = usbids()
    new = set(now) - set(before)
    gone = set(before) - set(now)
    if new or gone:
        print("t+%ds new=%s gone=%s" % (i + 1, sorted(new), sorted(gone)))
        for k in new:
            print("   ", now[k])
        break
else:
    print("no re-enumeration seen in 20s")
    print("after:", sorted(usbids()))

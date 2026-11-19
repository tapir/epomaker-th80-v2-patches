#!/usr/bin/env python3
"""Flash a ROYUAN gen2 app image through the vendor USB bootloader (3151:5057).

Boot protocol (raw 64-byte feature reports, no app-mode checksum):
  init   [BA C0 cntLo cntHi len0 len1 len2]
  data   cnt x 64-byte chunks of image[20480:] (zero-padded to 64)
  verify [BA C2 cntLo cntHi s0 s1 s2 s3 len0 len1 len2 len3]
  reply  AB C0/C2 .. ; verify byte4: 55=ok AA=sum CC=readback BB=app-tag

The boot region (first 20 KB) is never sent, so the bootloader survives and the
board stays re-flashable. The app region is already erased by the boot on entry.
"""
import hid
import subprocess
import sys
import time

BOOT_VID, BOOT_PID = 0x3151, 0x5057
SKIP = 20480
APP_ID = "3151:5056"  # what the flashed app enumerates as


def usb_ids():
    out = subprocess.run(["lsusb"], capture_output=True, text=True).stdout
    return [l.split()[5] for l in out.splitlines() if len(l.split()) > 5]


def usb_3151():
    return [i for i in usb_ids() if i.startswith("3151:")]


def raw64(payload):
    return b"\x00" + bytes(payload) + bytes(64 - len(payload))


def main(image_path):
    data = open(image_path, "rb").read()
    payload = data[SKIP:]
    pad = (-len(payload)) % 64
    payload += bytes(pad)
    cnt = len(payload) // 64
    length = len(data) - SKIP
    checksum = sum(data[SKIP:]) & 0xFFFFFFFF
    print("image=%d payload=%d cnt=%d len=%#x sum=%#x" %
          (len(data), length, cnt, length, checksum))

    recs = hid.enumerate(BOOT_VID, BOOT_PID)
    if not recs:
        print("NOT in boot mode; 3151 devices:", usb_3151())
        return 1
    dev = hid.device()
    dev.open_path(recs[0]["path"])

    def reply(n=16):
        return bytes(dev.get_feature_report(0, 65))[1:1 + n]

    init = [0xBA, 0xC0, cnt & 0xFF, cnt >> 8,
            length & 0xFF, (length >> 8) & 0xFF, (length >> 16) & 0xFF]
    dev.send_feature_report(raw64(init))
    time.sleep(0.3)
    r = reply()
    print("init reply:", r.hex(" "))
    if r[0] != 0xAB or r[1] != 0xC0:
        print("init not acknowledged — aborting")
        return 2

    t0 = time.time()
    for i in range(cnt):
        dev.send_feature_report(raw64(payload[i * 64:(i + 1) * 64]))
        if i % 500 == 0:
            print("  chunk %d/%d  (%.1fs)" % (i, cnt, time.time() - t0))
        time.sleep(0.001)
    print("sent %d chunks in %.1fs" % (cnt, time.time() - t0))

    s = checksum
    verify = [0xBA, 0xC2, cnt & 0xFF, cnt >> 8,
              s & 0xFF, (s >> 8) & 0xFF, (s >> 16) & 0xFF, (s >> 24) & 0xFF,
              length & 0xFF, (length >> 8) & 0xFF,
              (length >> 16) & 0xFF, (length >> 24) & 0xFF]
    dev.send_feature_report(raw64(verify))
    time.sleep(0.5)
    try:
        r = reply()
        print("verify reply:", r.hex(" "), "-> byte4 =", hex(r[4]))
    except Exception as exc:
        print("verify read failed (device may have reset):", exc)
    dev.close()

    for i in range(20):
        time.sleep(1)
        if APP_ID in usb_ids():
            print("t+%ds APP MODE back: %s" % (i + 1, APP_ID))
            return 0
        if i % 5 == 0:
            print("t+%ds waiting for %s" % (i + 1, APP_ID))
    print("did not return to app mode: %s not on the bus" % APP_ID)
    return 3


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: sudo python3 tools/flash_boot.py IMAGE   (e.g. patch/build/th80.bin)")
    sys.exit(main(sys.argv[1]))

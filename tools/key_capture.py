#!/usr/bin/env python3
"""Print what the keyboard reports while keys are pressed, over USB (3151:5056) and through
the 2.4G dongle (3151:5052).

  sudo python3 tools/key_capture.py [seconds]   (default 15)

Decodes the boot keyboard report (interface 0), the full-keyboard bitmap (interface 1,
report 1), consumer keys (report 3), system keys (report 2) and shows vendor report 5 raw.
Prints on every change.
"""
import sys
import time

import hid

MODS = ["LCtrl", "LShift", "LAlt", "LGui", "RCtrl", "RShift", "RAlt", "RGui"]
NAMES = {0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab", 0x2C: "Space",
         0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\", 0x33: ";", 0x34: "'",
         0x35: "`", 0x36: ",", 0x37: ".", 0x38: "/", 0x39: "CapsLock", 0x46: "PrintScreen",
         0x47: "ScrollLock", 0x48: "Pause", 0x49: "Insert", 0x4A: "Home", 0x4B: "PageUp",
         0x4C: "Delete", 0x4D: "End", 0x4E: "PageDown", 0x4F: "Right", 0x50: "Left",
         0x51: "Down", 0x52: "Up"}
NAMES.update({0x04 + i: chr(ord("A") + i) for i in range(26)})
NAMES.update({0x1E + i: str((i + 1) % 10) for i in range(10)})
NAMES.update({0x3A + i: f"F{i + 1}" for i in range(12)})
CONSUMER = {0xE2: "Mute", 0xE9: "VolumeUp", 0xEA: "VolumeDown", 0xCD: "PlayPause",
            0xB5: "NextTrack", 0xB6: "PrevTrack", 0xB7: "Stop", 0x6F: "BrightnessUp",
            0x70: "BrightnessDown"}


def key_name(usage):
    return NAMES.get(usage, f"key{usage:#04x}")


def decode(iface, r):
    """Return (stream name, set of pressed names) or None for reports we ignore."""
    if iface == 0 and len(r) >= 8:
        down = {m for i, m in enumerate(MODS) if r[0] >> i & 1}
        down |= {key_name(u) for u in r[2:8] if u}
        return "keyboard", down
    if iface == 1 and r and r[0] == 1:
        down = {key_name(8 * i + b) for i, byte in enumerate(r[1:16]) for b in range(8)
                if byte >> b & 1}
        return "keyboard-nkro", down
    if iface == 1 and r and r[0] == 5:  # vendor report: settings changes, e.g. 03 = OS mode
        return "vendor", {" ".join(f"{b:02x}" for b in r[1:6])}
    if iface == 1 and r and r[0] in (2, 3) and len(r) >= 3:
        usage = r[1] | r[2] << 8
        name = CONSUMER.get(usage, f"usage{usage:#06x}") if r[0] == 3 else f"system{usage:#06x}"
        return ("consumer" if r[0] == 3 else "system"), ({name} if usage else set())
    return None


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    devs = {}
    for pid, src in ((0x5056, "usb"), (0x5052, "dongle")):
        for d in hid.enumerate(0x3151, pid):
            if d["interface_number"] in (0, 1) and d["path"] not in devs:
                h = hid.device()
                h.open_path(d["path"])
                h.set_nonblocking(True)
                devs[d["path"]] = (src, d["interface_number"], h)
    if not devs:
        print("neither 3151:5056 nor 3151:5052 found")
        return 1
    last = {}
    t0 = time.time()
    while time.time() - t0 < secs:
        idle = True
        for path, (src, iface, h) in list(devs.items()):
            try:
                r = h.read(64)
            except OSError:  # unplugged, or re-enumerated after a mode change
                print(f"{time.time() - t0:6.2f}s  {src} interface {iface} gone")
                h.close()
                del devs[path]
                continue
            if not r:
                continue
            idle = False
            got = decode(iface, r)
            stream = f"{src} {got[0]}" if got else None
            if got and last.get(stream) != got[1]:
                last[stream] = got[1]
                print(f"{time.time() - t0:6.2f}s  {stream:21s} {' + '.join(sorted(got[1])) or '(released)'}")
        if idle:
            time.sleep(0.002)
    for *_, h in devs.values():
        h.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

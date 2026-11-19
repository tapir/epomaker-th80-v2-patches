#!/usr/bin/env python3
"""Capture TH80 V2 pin-scanner reports (1209:5CA4).

  down/up  drive->sense : a held key lets the driven (low) pin pull another pin low
  base     pin=value    : a pin flipped while every pin is an input (mode switch, knob)

Runs until Ctrl-C, --max seconds, or --idle seconds after the last event with no key
held. --out saves the events as JSON.
Report: [0]=0xA5 [1]=drive(0..39, 40=baseline) [2:4]=PA_PIN [4:7]=PB_PIN [7]=seq
"""
import argparse
import json
import time

import hid

VID, PID = 0x1209, 0x5CA4
ALL = (1 << 40) - 1
IGNORE = (1 << 26) | (1 << 27)   # PB10/PB11: USB D-/D+, follow bus traffic


def pinname(i):
    return "PA%d" % i if i < 16 else "PB%d" % (i - 16)


def pins(w):
    return [i for i in range(40) if (w >> i) & 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=float, default=0, help="stop after N seconds")
    ap.add_argument("--idle", type=float, default=0,
                    help="stop N seconds after the last event")
    ap.add_argument("--out", help="save events to this JSON file")
    args = ap.parse_args()

    recs = hid.enumerate(VID, PID)
    if not recs:
        print("scanner not found (1209:5CA4)")
        return 1
    dev = hid.device()
    dev.open_path(recs[0]["path"])
    dev.set_nonblocking(1)

    t0 = time.time()
    events = []
    last_event = None

    def log(kind, **kw):
        nonlocal last_event
        last_event = time.time()
        ev = dict(t=round(last_event - t0, 2), kind=kind, **kw)
        events.append(ev)
        detail = " ".join(kw.get("pairs", [])) or " ".join(
            "%s=%d" % kv for kv in kw.get("pins", {}).items())
        print("%7.2fs %-4s %s" % (ev["t"], kind, detail), flush=True)

    def fmt(ps):
        return ["%s->%s" % (pinname(d), pinname(s)) for d, s in sorted(ps)]

    base = None
    last_drive = 40
    sweep = set()
    streak = {}   # (drive, sense) -> +n consecutive sweeps present, -n absent
    held = set()

    def close_sweep():
        pressed, released = [], []
        for p in sweep | set(streak):
            n = streak.get(p, 0)
            if p in sweep:
                n = n + 1 if n > 0 else 1
                if n == 2 and p not in held:   # debounce: 2 sweeps (~0.33 s)
                    held.add(p)
                    pressed.append(p)
            else:
                n = n - 1 if n < 0 else -1
                if n == -2:
                    if p in held:
                        held.discard(p)
                        released.append(p)
                    streak.pop(p, None)
                    continue
            streak[p] = n
        if pressed:
            log("down", pairs=fmt(pressed))
        if released:
            log("up", pairs=fmt(released))

    try:
        while True:
            now = time.time()
            if args.max and now - t0 > args.max:
                break
            if args.idle and last_event and not held and now - last_event > args.idle:
                break
            try:
                r = dev.read(64)
            except OSError:
                log("gone")
                break
            if not r:
                time.sleep(0.0005)
                continue
            if len(r) < 8 or r[0] != 0xA5:
                continue
            d = r[1]
            w = r[2] | r[3] << 8 | (r[4] | r[5] << 8 | r[6] << 16) << 16
            if d == 40:
                ch = (w ^ base) & ~IGNORE & ALL if base is not None else 0
                if ch:
                    log("base", pins={pinname(i): (w >> i) & 1 for i in pins(ch)})
                base = w
                continue
            if base is None:
                continue
            if d <= last_drive:
                close_sweep()
                sweep = set()
            last_drive = d
            for s in pins(base & ~w & ~(1 << d) & ~IGNORE & ALL):
                sweep.add((d, s))
    except KeyboardInterrupt:
        pass

    keys = []
    for ev in events:
        if ev["kind"] == "down" and ev["pairs"] not in keys:
            keys.append(ev["pairs"])
    print("\n%d distinct keys, in press order:" % len(keys))
    for i, k in enumerate(keys, 1):
        print("  %2d. %s" % (i, " ".join(k)))
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"baseline": base, "events": events}, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

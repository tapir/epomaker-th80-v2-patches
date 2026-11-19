#!/usr/bin/env python3
"""Flash re/scanner/scanner.bin through the vendor USB boot.

    sudo python3 tools/flash_scanner.py

If the scanner (1209:5CA4) is running it is told to enter the boot first; from the
keyboard firmware run tools/enter_boot.py before this.
"""
import importlib.util
import sys
import time
from pathlib import Path

import hid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("flash_boot", HERE / "flash_boot.py")
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)
fb.SKIP = 0  # the scanner image is the app alone, without the 20 KB boot prefix
fb.APP_ID = "1209:5ca4"

if not hid.enumerate(0x3151, 0x5057) and hid.enumerate(0x1209, 0x5CA4):
    dev = hid.device()
    dev.open(0x1209, 0x5CA4)
    dev.write(b"\x00" + bytes([0x7F, 0x55, 0xAA, 0x55, 0xAA]) + bytes(59))
    dev.close()
    for _ in range(30):
        time.sleep(1)
        if hid.enumerate(0x3151, 0x5057):
            break

sys.exit(fb.main(str(HERE.parent / "re/scanner/scanner.bin")))

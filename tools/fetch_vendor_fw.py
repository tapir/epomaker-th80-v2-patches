#!/usr/bin/env python3
"""Fetch and decompress ROYUAN vendor firmware images for a given device id.

The OTA backend serves raw-deflate blobs; the desktop driver inflates them before
handing the bytes to the vendor bootloader, so what lands here is the plaintext
image the keyboard runs.

    python3 tools/fetch_vendor_fw.py [DEV_ID ...]   # default 3720 (CK75SE): firmware/<dev>_<ver>.bin
"""
import json
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "firmware"
API = "https://api2.rongyuan.tech:3816/api/v2/get_fw_version"
DOWNLOAD = "https://api2.rongyuan.tech:3816/download/"


def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def main(dev_ids):
    for dev in dev_ids:
        try:
            meta = post(API, {"dev_id": int(dev)})
        except urllib.error.HTTPError as exc:  # unknown ids now get HTTP 500
            print("%s: no record (HTTP %d)" % (dev, exc.code))
            continue
        if meta.get("code") != 0:
            print("%s: no record (%s)" % (dev, meta.get("err_message")))
            continue
        info = meta["data"]
        blob = get(DOWNLOAD + info["file_path"])
        image = zlib.decompressobj(-15).decompress(blob)
        name = OUT / ("%s_%s.bin" % (dev, info["version_str"].replace("/", "_")))
        OUT.mkdir(exist_ok=True)
        name.write_bytes(image)
        print("%s: %-28s %6d -> %6d bytes  %s" % (
            dev, info["version_str"], len(blob), len(image), name))


if __name__ == "__main__":
    main(sys.argv[1:] or ["3720"])

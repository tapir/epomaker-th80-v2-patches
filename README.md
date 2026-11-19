# Epomaker TH80 V2: patched CK75SE firmware

The TH80 V2's own firmware is gone from this board: the vendor bootloader erases the app
before every flash, the chip's read-out is locked, and Epomaker never published a TH80 V2
(device id 3573) image. This repository turns the published firmware of a sibling board
on the same ROYUAN `ry6602` / WCH CH584M platform, the COOLKILLER CK75SE (`3720_v107`),
into firmware for the TH80 V2 by binary patching, and keeps the tools and notes that got
there.

## Status

Working with `patch/build/th80.bin`:

- All 79 keys in the TH80 layout. Left Win acts as Fn and the key right of R-Alt as Win
  (swapped by choice).
- Knob: clockwise / counter-clockwise = Volume Up / Down, press = Mute, over USB, 2.4G and
  BT. They are keymap slots, so they remap like keys.
- Mode switch: USB / 2.4G (stock dongle) / BT. Fn+1/2/3 picks the BT device.
- Win/Mac switch: sets the firmware's OS mode.
- Debounce 5 ms by default.
- Sharkfin (github.com/dniminenn/sharkfin) identifies it as a TH80 V2: keymap, knob,
  lighting effects, colours, rainbow and brightness work.
- Recovery without opening the case: hold Esc + L while plugging in.

The Fn layers hold only Fn+1/2/3 and Fn+Esc (factory reset); everything else is meant to
be mapped in Sharkfin. Not done yet: [TODO](#todo).

## Build

- `sh tools/get_toolchain.sh`: installs the toolchain into `toolchain/`. It is the
  WCH-patched xPack GCC 12.2.0 shipped with the QMK CH58x port; stock xPack lacks the WCH
  interrupt attribute and the implicit Zicsr the code relies on.
- `python3 patch/build.py`: `patch/build/th80.bin`, plus `patch/build/review.dis` with
  the disassembly of every patched spot. Details: `patch/README.md`.
- `make -C re/scanner`: the pin scanner (`scanner.bin`, `combined.bin`).
- `sh re/disasm.sh`: the CK75SE disassemblies the notes refer to.

The USB tools need Python 3 with `hid` (hidapi); reviews and disassembly need
`llvm-objdump` 17 or newer (WCH `+xwchc` support).

## Flash

The tools open hidraw devices: run them with `sudo` or add a udev rule for VID `3151`.

1. Mode switch on **USB**.
2. `sudo python3 tools/enter_boot.py`: the keyboard re-enumerates as `3151:5057`, the
   vendor boot, which has already erased the app.
3. `sudo python3 tools/flash_boot.py patch/build/th80.bin`.

Every flash resets the settings page: debounce, lighting and base-layer remaps return to
the firmware defaults; Fn-layer edits survive. In 2.4G and BT mode the keyboard stays on
USB while plugged in, so Sharkfin and the tools still reach it.

## Recovery

- **Esc + L**: mode switch on USB, hold Esc and L while plugging in. The keyboard comes up
  as `3151:5057`; flash any build to leave boot mode. Works as long as the patched firmware
  reaches its early startup.
- **J2** (case open): the 2-pin header next to the MCU is its PB22 boot pin. Short it,
  plug in, and the WCH ROM loader appears as `1a86:55e0`; keep J2 shorted and run
  `sudo wchisp flash --no-verify --no-reset re/scanner/combined.bin` (CK75SE boot + pin
  scanner), then open J2 and replug.

## Tools

| | |
|---|---|
| `tools/enter_boot.py` | keyboard → vendor boot (`7F 55 AA 55 AA`) |
| `tools/flash_boot.py IMAGE` | flash through the vendor boot (sends `image[0x5000:]`) |
| `tools/probe.py` | read-only: device id, firmware version, profile, debounce, lighting |
| `tools/key_capture.py [s]` | print what the keyboard sends, over USB and the 2.4G dongle |
| `tools/fetch_vendor_fw.py [ID]` | download a vendor image from the ROYUAN OTA server (default 3720) |
| `tools/get_toolchain.sh` | install the toolchain into `toolchain/` |
| `tools/flash_scanner.py` | flash the pin scanner |
| `tools/scanner_cmd.py` | pin-scanner commands: status, battery ADC, LED tests, enter boot |
| `tools/capture_pins.py` | log pin-scanner key and pin events |

## Layout

| | |
|---|---|
| `firmware/3720_v107.bin` | the CK75SE vendor image the patches apply to |
| `patch/` | patch list, hooks, build tool, `build/th80.bin` |
| `re/FINDINGS.md` | hardware, protocols and firmware internals |
| `re/scanner/` | bare-metal pin scanner used to map the TH80's pins |
| `re/wch_sdk/` | the part of WCH's `openwch/ch585` SDK the scanner builds from |
| `captures/` | raw scanner captures behind the pin map |
| `evidence/` | FCC internal photos, MCU marking photos |

## Hardware

- MCU: **WCH CH584M** (marked `RY6602`), QingKe RISC-V3C, 448 KiB flash, 96 KiB RAM, BLE,
  2.4G and USB full speed. Read-out and debug are locked.
- Original firmware: `ry6602_fq_ak_x159e_3m_1k_1k`, device id 3573, v1.05, USB `3151:5056`.
  The patched firmware reports id 3573 and v1.07 but keeps the CK75SE USB strings.
- Pin map, LED chain, protocols and firmware internals: `re/FINDINGS.md`.

## TODO

- LEDs:
  - Per-key effects are one LED off from the number row on. The CK75SE's LED tables
    (`0x3D4F8`, effect tables `0x3D300`/`0x3D35C`/`0x3D576`) assume its 14-key top row; the
    TH80 order is in `re/FINDINGS.md`.
  - Side lights (LEDs 82–115) stay dark: the CK75SE frame buffer holds 87 LEDs. Needs a
    116-LED buffer, side-light effects, and Sharkfin's edge-light commands (`0x08`/`0x88`;
    check the colour-mode 7/8 swap there too).
  - Drive the CK75SE's indicator states onto the TH80 strip (LEDs 79–81).
- Remove Fn+Esc (factory reset) from the Fn layers once the defaults stop changing.
- Sleep: the knob and Win/Mac pull-ups stay on in sleep (extra drain while a contact is
  closed); release or drive them low before sleep.
- Untested: pairing a new BT host (long press Fn+1/2/3).
- USB product string still says "CK75SE Gaming Keyboard".
- Final test: every key, the knob and the switches in USB / 2.4G / BT; battery level;
  sleep and wake.

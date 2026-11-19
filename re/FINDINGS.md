# TH80 V2 and CK75SE firmware: reverse-engineering notes

Addresses are flash addresses in `firmware/3720_v107.bin` (COOLKILLER CK75SE v1.07) unless
marked RAM. `sh re/disasm.sh` writes the disassemblies (`re/ck75se_app_rv32.dis`, left column
= flash address; `re/ck75se_boot.dis`). Decode as RV32 with llvm `--mattr=+m,+a,+c,+xwchc,
+zba,+zbb,+zbc,+zbs`: without `+xwchc` the QingKe core's compressed byte/halfword
loads/stores show as FP or `<unknown>`. GNU objdump on raw bytes (`-b binary`) decodes as
RV64, which turns `c.jal` into `c.addiw` and hides calls.

## MCU and access

- **WCH CH584M**, marked `RY6602` / `1500TF2x` (U2, QFN48): QingKe RISC-V3C, 448 KiB code
  flash, 32 KiB data flash, 96 KiB SRAM, BLE + 2.4G + USB full speed. Evidence: platform
  images carry the build tag `CH584M 1KKB 1M` and the WCH BLE stack `CH585_BLE_LIB_V1.4.9`,
  and contain this board's HID descriptors; marking photo `evidence/u2-ry6602-marking.png`
  (FCC exhibit, internal view 4). PCB silkscreen `RY6602-3M-AKCB-V0.1-20251218`.
- `wchisp info`: `CH584[0x8416]`, BTVER 02.30, UID `E8-F5-1E-5E-3D-0C-43-60`,
  `CFG_ROM_READ=0` (no read-out), `CFG_DEBUG_EN=0` (no 2-wire debug), `CFG_BOOT_EN=1`,
  `CFG_RESET_EN=0`, `DOWNLOAD_CFG=PB22`. The original firmware can't be dumped.
- **J2** (2-pin header by U2, near the `TX1`/`GND1`/`VDD-3V1` pads) is the PB22 download
  pin: shorted at power-up, the WCH ROM bootloader starts (`1a86:55e0`). Keep it shorted
  while flashing (opening it resets out of the ROM loader): `sudo wchisp flash --no-verify
  --no-reset IMAGE` (verify fails under read protection; `wchisp reset` times out, so
  replug instead).
- The original TH80 V2 firmware (`ry6602_fq_ak_x159e_3m_1k_1k`, id 3573, v1.05, USB
  `3151:5056` "TH80 V2") is gone: the vendor boot erases the app before every flash, and
  the ROYUAN OTA server has no 3573 record. The boot region now holds the CK75SE v1.07
  boot, written by the J2 flashes of `re/scanner/combined.bin`; it behaves like the
  original.

## TH80 V2 pin map (measured with the scanner)

Key matrix: 6 rows × 15 columns, 79 keys. Diodes conduct column → row: driving a row low
pulls the pressed key's column low. Raw captures: `captures/step1_top.json` …
`step8_switches.json`.

| col | C0 | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | C10 | C11 | C12 | C13 | C14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pin | PA13 | PA12 | PA11 | PA10 | PA7 | PA8 | PA9 | PB9 | PB8 | PB17 | PB16 | PB15 | PB14 | PB7 | PB6 |

| row | pin | columns used |
|---|---|---|
| R0 top (Esc, F1–F12) | PA5 | C0–C12 (13) |
| R1 number | PA6 | C0–C14 (15) |
| R2 Tab | PA0 | C0–C14 (15) |
| R3 Caps | PA1 | C0–C11, C13–C14 (14) |
| R4 Shift | PA2 | C0, C2–C13 (13) |
| R5 bottom | PA3 | C0–C2, C6, C10–C14 (9) |

Other inputs (active low, pull-up):
- Knob: A/B = PB3/PB2, A changes first when turning clockwise; one click = half a
  quadrature cycle (detents at 00 and 11). Push = PB4.
- Mode switch: PB20 low = BT, PB21 low = 2.4G, both high = USB. On USB the switch also
  disconnects the battery, so unplugging USB resets the chip; on BT/2.4G the battery runs it.
- Win/Mac switch: PB1 low = Mac.

Outputs and sensing:
- PA14 = WS2812 data (SPI0 MOSI, default pin mapping); chain order below.
- PA15 = LED power, high = on; alone it powers every LED. The CK75SE also switches PB19
  with it (`0x7926` on, `0x79D8` off); PB19 alone has no visible effect.
- PA4 = battery sense (ADC channel 0): ~1.03 V with the switch on BT, ~0 on USB. CK75SE
  routine `0x6CB0` (11-sample median).
- PB0 = low while USB power is present (USB detect or charger status). CK75SE checks it at
  `0x6D8E`, `0x7984`.
- USB D-/D+ = PB10/PB11; J2 = PB22. PB18 is a pull-up input the CK75SE reads (purpose
  unknown); PB5, PB12, PB13, PB23 are unused by it. None of these has a function found on
  the TH80.

### LED chain (PA14, 116 LEDs)

| LEDs | what |
|---|---|
| 0–12 | Esc, F1–F12, left to right |
| 13–27 | number row, right to left (Delete … `) |
| 28–42 | Tab row, left to right (Tab … PgUp) |
| 43–56 | Caps row, right to left (PgDn … Caps) |
| 57–69 | Shift row, left to right (LShift … Up) |
| 70–78 | bottom row, right to left (Right … LCtrl) |
| 79–81 | top-left strip, top to bottom |
| 82–115 | side lights, 34 on both sides |

Nothing lights from 116 on. The side order isn't mapped: it jumps between the sides (left
from the middle toward the back, part of the right, the rest of the left, the rest of the
right).

### CH584M GPIO registers (base `0x40001000`)

| offset | PA | PB | meaning |
|---|---|---|---|
| DIR | `0xA0` | `0xC0` | 0 = in, 1 = out |
| PIN | `0xA4` | `0xC4` | input |
| OUT | `0xA8` | `0xC8` | output |
| CLR | `0xAC` | `0xCC` | write 1 to clear |
| PU | `0xB0` | `0xD0` | pull-up |
| PD_DRV | `0xB4` | `0xD4` | pull-down (input) / drive strength (output) |
| SET | `0xB8` | `0xD8` | write 1 to set |

PA = pins 0–15, PB = pins 0–23.

## Vendor boot (`0x0000–0x4FFF`)

- USB `3151:5057` "USB Keyboard Boot", bcdDevice 1.01; one HID collection (usage page
  `0xFF01`) with 64-byte feature reports, no checksum.
- Flash: init `[BA C0 cntLo cntHi len0 len1 len2]`, then `cnt` × 64-byte chunks of
  `image[0x5000:]`, then verify `[BA C2 cntLo cntHi s0..s3 len0..len3]` (s = 32-bit byte
  sum). Replies `AB C0`/`AB C2 …`; verify byte 4: `55` ok, `AA` sum mismatch, `BB` app tag
  invalid, `CC` read-back error. `tools/flash_boot.py` implements it.
- Dispatcher `0x1354`: `0x008F` identify (`8F FF FF FF FF .. .. 70`), `0xC0BA` init, `0xC2BA`
  verify, `0xFFBA` (copies 4 bytes to `0x4004`). No read and no exit command.
- Startup `0x16FC`: flag word at `0x4000` == `0x55AA55AA` → USB flash mode; else the
  16-byte tag at `0x5300` must equal `"CH584M 1KKB 1M  "` (compare `0x16D0`, string at
  `0x1840`) to jump to the app at `0x5000`; otherwise flash mode. There is no integrity
  check beyond the tag.
- Flash mode first erases the app region (`0x15C0`: `0x5000`, length `0x5B000`); after a
  verified flash it erases the flag page (`0x1790`) and resets. So it survives power
  cycles until a flash completes.
- Page `0x4000–0x4FFF` holds only the flag and the app's dev id at `0x4004`; boot code
  ends at `0x18F7`.

## App protocol (interface 2, usage page `0xFFFF` usage 2)

64-byte feature reports, report ID 0. **Byte 7 = `~(byte0 + … + byte6) & 0xFF`**, except for
`07` and `08`, whose 7 parameters push it to byte 8 (`0x19CEE`); without it the firmware
ignores the packet and the kernel returns the previous buffer, which looks like an echo.
Commands (dispatcher `0x1A900`, jump tables `0x3D6A4` for `0x02–0x11` and
`0x3D5E4` for `0x7F–0xAE`; command and reply share RAM `0x2000F108`):

| command | handler | |
|---|---|---|
| `8F` | `0x19D86` | identify: `8F <dev_id u32 LE> 00 00 <minor> <major>` |
| `7F 55 AA 55 AA` | `0x19C74` | enter the vendor boot |
| `06 ms` / `86` | `0x19F4C` / `0x19F66` | debounce set / get (reply byte 1) |
| `07 mode speed bright flags R G B` / `87` | `0x19F74` / `0x1A008` | lighting of one mode |
| `08 mode speed bright flags R G B` / `88` | `0x1A0C4` / `0x1A11C` | side light |
| `0A` / `8A` | | keymap write / read (`[profile, 0xFF, page, 0]`, 8 × 64 B) |
| `10` / `90` | | Fn layer write / read (`[os, profile, 0xFF, page]`) |
| `04` / `84` | | profile set / get |

`tools/probe.py` reads the GET side.

## CK75SE app internals

### Memory map and startup

- `0x5000` = `j 0x10EF8`. The first stage there sets gp = `0x2000CCE8`, sp = `0x20018000`,
  copies flash `0x5004–0x5203` to RAM `0x20000000` and jumps to RAM `0x20000150`. That
  block holds the vector table (40 vectors, magic `0xF3F9BDA9` at `0x5014`; default
  handler at RAM `0x200000A0`) and the init that copies `.highcode` and `.data`, clears
  `.bss`, sets mtvec `0x20000003` and `mret`s to main.
- `.highcode` = flash `0x5400–0x10EF7`, **executed from RAM** `0x20000200–0x2000BCF7`
  (RAM = flash + `0x1FFFAE00`). The GPIO helpers, scan, LED, ADC and mode-key code live
  here: PC-relative instructions in it resolve at the RAM address, and a `jal` there can't
  reach flash code (`auipc`+`jalr` can).
- Flash `.text` from `0x10EF8`; `.rodata` (keymaps, LED tables) ends before `0x3E1C4`;
  `.data` image `0x3E1C4` → RAM `0x2000BCF8–0x2000C6A3`; `.bss` `0x2000C6A8–0x20013C9F`.
  The image ends at `0x3EB70`; the boot accepts up to `0x60000`.
- RAM `0x20000150–0x200001FF` (the RAM copy of the init code) is unreferenced after
  startup.
- From `0x20013CA0` (end of `.bss`) newlib's heap grows toward the stack (`_sbrk`
  `0x12136`); only `rand()` mallocs, once, 24 bytes. The stack starts at `0x20018000`; its
  deepest known frames are 4 KiB flash-page buffers (`0x1334C`, `0x13952`).
- main = `0x1BDF4`; SetSysClock `0x11E1E` runs first. `0x1BE4C` (`jal 0x110D0` with
  `a0 = 4`) is the first call after the clock setup.
- Enter boot `0x19C74`: erase, write, verify `0x55AA55AA` at `0x4000` (≤1000 tries), erase
  the settings page `0x60000`, write dev id `0xE88` to `0x4004` (`0x13742`), reset
  (`0x1B01E`). Flash routine: RAM `0x2000030A` (flash `0x550A–0x5873`), args (cmd 1 erase /
  2 write / 3 verify, addr, buf, len).

### Settings

240-byte block at RAM `gp+0x688` (`0x2000D370`): +4 halfword bits 1–2 = OS mode (0 Win,
1 Mac), +8 = current lighting mode, +9 = debounce, +0x0D–0x13 side light (command `08`),
per-mode lighting at +0x22 (speed),
+0x42 (brightness), +0x62 (flags), +0x82 (RGB, 3 bytes per mode). Loaded from code flash
`0x60000` (`0x13B24`); when that page is blank (every enter-boot erases it), the defaults at
`0x3D080` are copied in (`0x13AA8`) and saved. The live base keymap is at RAM `gp+0x488`.
Connection mode: data flash `0x6000` (16 bytes, `0x1B41A`), RAM `0x200104AC`.

### Keys

- Keymaps: 128 slots × 4 bytes per layer, slot = column × 6 + row (columns as in the pin
  map; slots 90–127 unused). Entry `[type, arg, code, arg2]` (Sharkfin's encoding):
  `00 00 usage 00` key, `03 00 lo hi` consumer, `0A n 00 00` special (1 Fn, 2 reset, 3 Win
  lock, 5 OS mode, 8 backlight toggle), `0E 00 n 00` connection (0–4 BT1–5, 5 2.4G, 6 USB),
  `0D ..` lighting. All-zero = dead key in the base layer, fall-through in a Fn layer.
- Stock base layer `0x3CE80`: matches the TH80 except slot 78 (C13 R0) Delete, 85 (C14
  R1) Insert, 65 (C10 R5) Fn, 71 (C11 R5) Right Ctrl. Fn layers at `0x3C080 + n × 0x200`,
  n = 0..6 (Win F-row: 0, 5, 6; Mac F-row: 1–4).
- Path: the matrix scans `0xA0D4`/`0xA4E4` (RAM code, 1 kHz) drive each of the 15 columns
  in turn and call `key_event(column, row, pressed)` = `0x9FEC` (RAM `0x20004DEC`) on a
  debounced change. It looks the slot up in the live keymap, runs the Fn/layer chain
  (`0x9B4C` … `0x8580`) and ends in the type dispatcher `0x9862` (table `0x3AE58`). Type
  `0x0A` handler `0x92B6` (RAM `0x200040B6`), sub-function table `0x3ADFC`; `0A 05 os 00`
  sets the OS mode and sends vendor report 5 `03 …`.
- GPIO helpers (RAM code), port 0 = PA / 1 = PB: write `0xCDA2` (port, pin, value), read
  `0xCDC8` (port, pin), pin mode `0xCCF4` (port, pin, mode 0 in / 1 out 5 mA / 2 out 20 mA,
  pull 0 none / 1 down / 2 up), `0xCDE4`.

### Mode switch

The CK75SE reads a 3-position switch on PB1 (low = BT) and PB2 (low = 2.4G), both high =
USB: the same scheme as the TH80's PB20/PB21. On the TH80, PB1 is the Win/Mac switch and
PB2 knob A, so each knob click flipped 2.4G/USB until the patch renamed all 20 PB1/PB2 pin
arguments.

- Decoder `0x14026` returns the connection mode (0–4 BT1–5 from the stored channel, 5 2.4G,
  6 USB, both pins low = USB) into RAM `0x200104AC`; boot-time select `0x14084`.
- Runtime poll `0x714E` (RAM code, slow tick): switches after 25 disagreeing polls.
- The mode-key handler `0x9706` (type `0x0E`) acts only with the switch in the matching
  position.
- Init `0x142D6` makes PB0/PB1/PB2/PB18 pull-up inputs; before sleep it drives PB1/PB2 low.

### Lighting

- WS2812 over SPI0 (`0x40004000`, PA14), one SPI byte per bit (1 = `0xF0`, 0 = `0xC0`),
  24 per LED in G R B order. Every 8 ms (event `0x80`) the effects render into frame A (RAM
  `0x2000E0B8`, 87 LEDs = 2088 B), `0x196D0` adds the indicators and copies A to frame B
  (`0x2000E8E0`), and the mode loop calls the DMA send `0x1422C(B, 2088)`, which returns
  at once while the previous frame is still going out.
- LED writers (RAM code; index, brightness %, R, G, B): `0x7C74` key LEDs 0–79 into A, and
  copies LED 76 (space bar) onto 83–86; `0x7D9C` any LED into A, 5× dimmer (indicators);
  `0x7E72` into B (factory LED test `0x7F52`). Colour transform:
  `sum = G·255/400 + R + B/2`, `R' = R²·250 / (sum·255)`, `G' = G²·250 / (sum·400)`,
  `B' = B²·250 / (sum·510)`, then × brightness / 100; it caps the current of mixed colours.
  Brightness levels 0–4 = 0/25/50/75/100 % (RAM `0x2000C638`).
- CK75SE chain: 0–79 keys, 80 Caps Lock (white), 81 unused, 82 charging (`0x1947A`, which
  also shows the battery level on keys 1–0), 83–86 space-bar underglow. Its top row has 14
  LEDs (LED 13 = its 14th key, where the TH80 has the knob), so from LED 14 on, the TH80
  chain is one LED earlier, indicators included.
- `0x3D3FC`: matrix (row, column) → layout position (row, x), 6 × 21 byte pairs, `ff ff` =
  no key; row 0 skips x1 (the indicator strip). `0x3D4F8`: layout (row, x) → LED index,
  6 × 21 bytes; serpentine from Esc over 80 key LEDs. The CK75SE's top row has 14 keys
  (TH80: 13), so its table is one LED off for the TH80 from the number row on.
  `0x3D300`, `0x3D35C`, `0x3D576`: effect order/group tables over LED indices.
- Command `0x07` stores mode, speed, brightness, flags and RGB per mode in the settings.
  Flags: low nibble = colour mode (0–6 preset colour, **7 own RGB, 8 rainbow**), high
  nibble = option. `0x13828`/`0x13BA4` load the current mode into the effect engine (RAM
  `0x2000D54C`: +0x1E colour mode, +0x32 option, +0x23 speed + 1); the effects
  (`0x14800–0x18E00`) test the colour mode. Dispatch: render table `0x3D1AC` (mode − 1,
  modes 1–24), key-press reactions `0x3D170` (mode − 5).
- Command `0x08` stores its 7 parameters at settings +0x0D (defaults `04 03 04 08 ff ff ff`:
  wave, speed 3, brightness 4, rainbow) and `0x88` reports them; nothing else reads them.

### Names

- USB strings (RAM-code handler at `0x68E0` sends each descriptor's own bLength): 1
  manufacturer `0x3B18C` (6 spaces), 2 product `0x3B15C` ("CK75SE Gaming Keyboard", room
  for 23 characters), 3 serial `0x3B144` ("0123456789").
- BLE: `0xC8C8` copies "CK75SE 5.0" (`0x3D6F4`, length 10 set at `0xC8D2`) into the
  29-byte name buffer RAM `0x2000C40C` (initialised to "ROYUAN KEYBOARD"). It becomes the
  GAP device name (`0x1B716`) and the scan response (`0xC9BC`, up to 29 characters); the
  advertising data (`0xC902`: template `0x3D700` = flags, keyboard appearance, HID UUID,
  Microsoft Swift Pair) carries it only up to 11 characters.
- The 2.4G dongle (`3151:5052`) reports its own strings.

### Timers and loops

TMR2 (1 kHz, `GetSysClock()/1000`) sets event bit `0x01` = key scan; TMR0 sets `0x80`
every 8th tick = mode-switch and battery polls. Each connection mode loops inside its own
RAM function (USB `0x77D4`, 2.4G `0xC842` → `0xC530`, BT `0x7B24`) and never returns to
main while the mode lasts. The loops call flash `0x199E8` once per scan tick, from
`0x7830`, `0x7A7C`, `0x7B7E` and `0xC698` (all `auipc`+`jalr`).

## Sharkfin (github.com/dniminenn/sharkfin)

- Picks the device record by the dev id from `0x8F` alone. 3573 = TH80 V2 (layout
  `Common79_TH80V2`, knob, side light, 3 profiles); 3720 = CK75SE.
- TH80 V2 keys have no fixed slots: Sharkfin finds each key by its factory entry in the
  board's keymap, so every TH80 key value must appear exactly once. The knob is three
  keys: `03 00 EA 00` (Vol−), `03 00 E2 00` (Mute), `03 00 E9 00` (Vol+).
- Its TH80 V2 profile (taken from the vendor app, so presumably the original firmware's
  convention) sends the colour modes 7 and 8 swapped relative to this firmware, for the
  lighting and the edge light alike; the CK75SE profile matches it.
- Edge light (`08`): modes 0 off, 1 static, 2 breathing, 3 spectrum, 4 wave, 5 snake;
  speed 0–4 is sent as shown (not inverted like the lighting's), brightness 0–4.
- It never flashes firmware.

## Pin scanner (`re/scanner/`)

Bare-metal CH584 app on WCH's `openwch/ch585` SDK (`re/wch_sdk`: the files it builds from,
upstream `db88919` plus `local-changes.patch`), linked at `0x5000` with the app tag at
`0x5300` so the vendor boot runs it. USB `1209:5CA4`, one 64-byte HID IN and OUT report.

- **Scan:** every ~2 ms, alternating a passive baseline (all 40 GPIOs input + pull-up,
  drive = 40) with an active step (one pin driven low, the rest read). IN report:
  `[0]=0xA5 [1]=drive [2:4]=PA_PIN [4:7]=PB_PIN [7]=seq`; a held key shows as a
  drive → pin pair, the knob and switches in the baseline.
- **Commands** (OUT report `CMD 55 AA 55 AA args`; `tools/scanner_cmd.py` sends them):
  - `0x7E`: status, plus PA4 ADC at 1/100/300/600 ms after releasing its pull-up, the
    chip supply, and PB0.
  - `0x7F`: enter the vendor boot the stock app's way (erase page `0x4000`, write
    `0x55AA55AA`, verify), then reset → `3151:5057`.
  - `0x7C PA15 PB19 P K`: LED test, scan paused. Pattern 1 = LEDs K..K+2 blue, the rest
    dim green; 2 = Esc lit while PB0 is high, F1 blinking; 3 = the blue and white LED
    bitmaps that follow the args (`tools/scanner_cmd.py leds BLUE WHITE`); 0 = off.
  - `0x7B`: LEDs off, scan resumes.

  Each answers with ~0.5 s of status reports: `[0]=0x5A [1]=cmd [2]=tries [3]=R8_CHIP_ID
  [4]=R8_GLOB_CFG_INFO`, then u32 LE `[8]` flag word, `[12]` tag word, `[16]/[20]/[24]`
  erase/write/verify rc, `[28]` MAC rc, `[32]` MAC; `[40..]` command-specific.
- Every hardware wait in the commands has a timeout: on BT/2.4G the battery keeps the
  chip running through a USB unplug, so a hang would persist.
- Flash writes go through WCH's `libISP585.a` (`FLASH_ROM_*`, runs from RAM).
- **Build:** `make -C re/scanner` → `scanner.bin` (app) and `combined.bin` (CK75SE boot +
  scanner, for the J2 ROM loader). The USB interrupt uses `"WCH-Interrupt-fast"`, which
  needs the WCH-patched GCC from `tools/get_toolchain.sh`.
- **Flash:** `sudo python3 tools/flash_scanner.py` (sends `0x7F` first if the scanner is
  running; from the keyboard firmware run `tools/enter_boot.py` first).
- **Capture:** `sudo python3 tools/capture_pins.py --idle 10 --max 180 --out
  captures/NAME.json` logs key pairs (`down/up drive->sense`) and resting-level changes
  (`base pin=value`), stopping 10 s after the last event. Hold each key ~1 s: presses
  shorter than two scan sweeps (~0.33 s) are ignored.

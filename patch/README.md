# patch/

Turns the vendor image `firmware/3720_v107.bin` (SHA-256 pinned in `build.py`) into
`patch/build/th80.bin`, plus `patch/build/review.dis` with the disassembly of every patched
region and of the hook blob.

## Build

```
python3 patch/build.py            # writes build/th80.bin and build/review.dis
python3 patch/build.py --selftest # the guards below, and no patches = the original image
python3 patch/rv.py               # jal and auipc+jalr encoders against llvm-objdump
```

Flash: `sudo python3 tools/enter_boot.py`, then `sudo python3 tools/flash_boot.py
patch/build/th80.bin` (it sends only `image[0x5000:]`, so the boot region is never
rewritten).

## Current patch set

| what | how |
|---|---|
| TH80 keymap | base layer `0x3CE80`: Delete, right Alt, Fn on left Win, Win on the Fn key, three knob slots (Mute C13 R0, Vol+ C14 R0, Vol− C14 R4) |
| Fn layers | all 7 at `0x3C080 + n × 0x200` cleared except Fn+1/2/3 (BT) and Fn+Esc (reset) |
| debounce | default settings `0x3D080` + 9: 1 → 5 ms |
| mode switch | the 20 PB1/PB2 pin arguments → PB20/PB21 |
| device id | identify reply `0x19D8E`/`0x19D94`: 3720 → 3573 (Sharkfin's TH80 V2 profile) |
| names | USB product string `0x3B15C` in place; the BLE name copy at `0xC8C8` loads `hook_ble_name` (`hooks/names.c`) with its length: "EPOMAKER TH80 V2" |
| Esc + L recovery | `0x1BE4C` → `hook_call` (`hooks/hook_call.c`): Esc + L held at power-up calls the stock enter-boot routine |
| knob, Win/Mac | the 4 scan-tick calls of `0x199E8` → `hook_tick` (`hooks/knob.c`): decodes the knob into `key_event()` presses of the knob slots, sets the OS mode from PB1 |
| lighting colours | commands `0x07`/`0x87`/`0x08`/`0x88` → `hook_led_set`/`_get`, `hook_sled_set`/`_get` (`hooks/led.c`): swap colour modes 7 and 8 for Sharkfin's TH80 V2 profile; an `0x08` mode byte with bit 7 set selects a side-LED test pattern instead (`tools/side_test.py`) |
| LED chain, side lights | the DMA send `0x1422C` → `hook_led_send` (`hooks/led_send.S`, `hooks/led.c`): turns the 87-LED CK75SE frame into the TH80's 116-LED chain and draws the side lights from the `0x08` settings |

## A patch

`patches.py` holds `PATCHES`, a list of `Patch(addr, old, new, why, ram_code=False)`. `old`
must equal the image bytes at `addr`; `new` is bytes of the same length, or a callable that
receives `{hook symbol: address}` so it can encode a call to a hook:

```python
Patch(0x1BE4C, bytes.fromhex("ef504fa8"), lambda syms: jal(0x1BE4C, syms["hook_call"]),
      "main: run the early XT32M tune call through hook_call")
```

- `rv.jal(src, dst)` / `rv.j(src, dst)`: 4-byte calls/jumps within ±1 MiB. A `jal` that
  replaces another `jal` must keep its `rd` and target the hook blob.
- `rv.call(src, dst)`: 8-byte `auipc ra` + `jalr ra`, reaching any address. A call pair
  that replaces another must call through `ra` and target the hook blob.
- `rv.la(src, dst, rd)`: 8-byte `auipc rd` + `addi rd`, an address load. One that replaces
  another must keep `rd` and point into the hook blob. `BLOB_DATA` in `patches.py` lists
  hook symbols whose bytes the build checks, for data that patches size elsewhere.
- A `jal`/`j` written over any other instruction must target the hook blob too: that is how
  a whole function is replaced (`0x1422C`).
- The build prints each redirected call's original target, which the hook calls itself
  (declared in `hooks/fw.ld`).
- A hook standing in for a whole function may clobber only the registers the original
  does: with GCC's `-fipa-ra` the firmware's callers can keep values in the others across
  the call. `hooks/led_send.S` saves them around its C body.

### `.highcode`: flash 0x5400-0x10EF7

The startup copies this block to RAM and executes it there (RAM address = flash address +
`0x1FFFAE00`), so its flash addresses are not execution addresses:

- a `jal` redirect there is refused: built from the flash address it would land on
  garbage, and from RAM a `jal` can't reach the flash hook blob anyway;
- an `auipc`+`jalr` redirect or `auipc`+`addi` address load is allowed when encoded at
  the RAM address (`call(site + 0x1FFFAE00, …)`); the build decodes both there;
- every patch in the region needs `ram_code=True`, stating that its address arithmetic
  accounts for the relocation;
- `review.dis` disassembles these regions at their RAM address and labels both.

### Never patchable, refused by the build

| range | what |
| --- | --- |
| `0x0000-0x4FFF` | vendor bootloader and its `0x4000` flag page |
| `0x5000-0x53FF` | app reset entry, the startup copy source, the boot-checked tag at `0x5300` |
| `0x550A-0x5873` | the firmware's flash erase/write routine |
| `0x10EF8-0x10F3F` | first-stage startup (sets `gp`/`sp`, copies `.highcode`, jumps to RAM) |
| `0x11E1E-0x11F2F` | `SetSysClock`, runs before the hook site |
| `0x13742-0x13765` | writes the dev id word into the boot's flag page at `0x4004` |
| `0x19C74-0x19CED` | stock enter-boot routine: erases and rewrites the boot flag and settings pages |
| `0x1BDF4-0x1BE4B` | `main()` up to the hook site; `0x1BE4C` itself stays patchable |

Nothing may extend past `0x60000`. Patches may not overlap.

## A hook

Put `.c`/`.S` files in `patch/hooks/`. They are compiled and linked into one blob at
`HOOK_BASE` (`0x3F000`, past the image end) by `hooks/hooks.ld`.

- `.text`/`.rodata` land in flash. `.bss` lands at `HOOK_RAM` (`0x20000180`), which must
  stay inside `0x20000150-0x200001FF`: the RAM copy of the startup's init code, the only
  RAM known to be unused once `main()` runs. Nothing zeroes it, so hooks clear their own
  state (`hook_call` calls `knob_init`).
- Buffers too large for that window go in section `.bufram` (`__attribute__((section(".bufram")))`)
  at `BUF_RAM` (`0x20013E00`), inside `0x20013D00-0x20015FFF`: RAM past the firmware's
  `.bss` that only newlib's heap (24 bytes, for `rand()`) and the stack's far end could
  reach; 8 KiB stay for the stack. Nothing zeroes it either.
- `.data` is rejected: hooks must not need initialized RAM; use `const` or literals.
- Firmware functions and variables are declared in `hooks/fw.ld` as
  `PROVIDE(fw_tick = 0x199E8);`, at the address where the code executes (RAM for
  `.highcode`), and referenced from C as `extern`.
- Hooks must not address anything through `gp`: the firmware owns it, and the build fails
  if the hook disassembly contains `(gp)`.
- Every global hook symbol is kept; static helpers nobody calls are dropped by
  `--gc-sections`.

After assembling, the build re-checks its own output: bytes below `0x5400` are identical to
the original, every differing byte lies in a declared patch or in the hook blob, and the blob
sits at `HOOK_BASE` behind `0xff` padding up to at most `0x60000`.

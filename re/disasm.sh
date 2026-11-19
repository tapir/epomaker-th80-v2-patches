#!/bin/sh
# Regenerate the CK75SE disassemblies the notes refer to (generated, so not committed):
#   re/ck75se_app_rv32.dis  app, left column = flash address
#   re/ck75se_boot.dis      vendor boot, 0x0000-0x4fff
# .highcode (flash 0x5400-0x10ef7) runs from RAM at flash + 0x1FFFAE00, so PC-relative
# targets inside it print as if it ran from flash.
set -eu
RE="$(cd "$(dirname "$0")" && pwd)"
OBJCOPY="$RE/../toolchain/riscv-none-elf-gcc/bin/riscv-none-elf-objcopy"
MATTR=+m,+a,+c,+xwchc,+zba,+zbb,+zbc,+zbs  # +xwchc: the QingKe core's own compressed forms
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

head -c 20480 "$RE/../firmware/3720_v107.bin" > "$tmp/ck75se_boot.bin"
tail -c +20481 "$RE/../firmware/3720_v107.bin" > "$tmp/ck75se_app.bin"
cd "$tmp"
for part in boot app; do
    "$OBJCOPY" -I binary -O elf32-littleriscv "ck75se_$part.bin" "ck75se_$part.o"
done
llvm-objdump -D --mattr=$MATTR ck75se_boot.o > "$RE/ck75se_boot.dis"
llvm-objdump -D --mattr=$MATTR --adjust-vma=0x5000 ck75se_app.o > "$RE/ck75se_app_rv32.dis"
wc -l "$RE/ck75se_boot.dis" "$RE/ck75se_app_rv32.dis"

#!/bin/sh
# Install the RISC-V GCC the scanner and the patch hooks are built with into toolchain/:
# the WCH-patched xPack GCC 12.2.0 shipped in the QMK CH58x port. Stock xPack builds
# differ: no "WCH-Interrupt-fast" (hardware-stacked interrupts) and no implicit Zicsr.
set -eu
REPO=https://github.com/O-H-M2/qmk_port_ch582.git
COMMIT=3cb1a0dc467512ba4f626427d59912b1d9baa91e
DIR=utils/Linux/riscv-none-elf-gcc
DEST="$(cd "$(dirname "$0")/.." && pwd)/toolchain"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git -C "$tmp" init -q
git -C "$tmp" remote add origin "$REPO"
git -C "$tmp" sparse-checkout set --no-cone "/$DIR/"
git -C "$tmp" fetch -q --depth 1 --filter=blob:none origin "$COMMIT"
git -C "$tmp" checkout -q FETCH_HEAD
mkdir -p "$DEST"
rm -rf "$DEST/riscv-none-elf-gcc"
mv "$tmp/$DIR" "$DEST/riscv-none-elf-gcc"
"$DEST/riscv-none-elf-gcc/bin/riscv-none-elf-gcc" --version | head -1

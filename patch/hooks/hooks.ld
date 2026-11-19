/* Hooks have no _start; naming any entry keeps ld from warning about a missing one. */
ENTRY(HOOK_BASE)
INCLUDE fw.ld

SECTIONS
{
  .text HOOK_BASE : { *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) }
  .bss HOOK_RAM (NOLOAD) : { *(.bss .bss.*) *(COMMON) }
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.riscv.attributes) }
}

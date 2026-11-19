/* Firmware symbols for hooks, as `PROVIDE(fw_name = 0xADDRESS);`: where the code executes,
   so .highcode functions (flash 0x5400-0x10ef7) get their RAM address (flash + 0x1FFFAE00). */

PROVIDE(fw_xt32m_tune = 0x110D0);  /* (a0 = tune value); main calls it with 4 at 0x1BE4C */
PROVIDE(fw_enter_boot = 0x19C74);  /* sets the boot flag at 0x4000, then resets */
PROVIDE(fw_tick = 0x199E8);        /* called once per 1 kHz key-scan tick, from RAM code */
PROVIDE(fw_key_event = 0x20004DEC); /* (column, row, pressed): flash 0x9FEC, runs from RAM */
PROVIDE(fw_special_key = 0x200040B6); /* (keymap entry, pressed) for type 0x0A: flash 0x92B6 */
PROVIDE(fw_led_set = 0x19F74);     /* feature command 0x07: store lighting params of a mode */
PROVIDE(fw_led_get = 0x1A008);     /* feature command 0x87: report them */

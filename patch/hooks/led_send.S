/* Entry of the firmware's LED DMA send (buf, len): flash 0x1422C jumps here. The stock
 * routine clobbers only a0, a4 and a5, and GCC's -fipa-ra lets its callers keep values in
 * the other caller-saved registers across the call, so led_send must not touch them. */
	.section .text.hook_led_send, "ax", @progbits
	.globl	hook_led_send
	.p2align 2
hook_led_send:
	addi	sp, sp, -64
	sw	ra, 60(sp)
	sw	a1, 56(sp)
	sw	a2, 52(sp)
	sw	a3, 48(sp)
	sw	a6, 44(sp)
	sw	a7, 40(sp)
	sw	t0, 36(sp)
	sw	t1, 32(sp)
	sw	t2, 28(sp)
	sw	t3, 24(sp)
	sw	t4, 20(sp)
	sw	t5, 16(sp)
	sw	t6, 12(sp)
	call	led_send
	lw	ra, 60(sp)
	lw	a1, 56(sp)
	lw	a2, 52(sp)
	lw	a3, 48(sp)
	lw	a6, 44(sp)
	lw	a7, 40(sp)
	lw	t0, 36(sp)
	lw	t1, 32(sp)
	lw	t2, 28(sp)
	lw	t3, 24(sp)
	lw	t4, 20(sp)
	lw	t5, 16(sp)
	lw	t6, 12(sp)
	addi	sp, sp, 64
	ret

#include <stdint.h>

#define REG32(a)  (*(volatile uint32_t *)(a))
#define PA_DIR    REG32(0x400010A0)
#define PA_PIN    REG32(0x400010A4)
#define PA_OUT    REG32(0x400010A8)
#define PA_CLR    REG32(0x400010AC)
#define PA_PU     REG32(0x400010B0)
#define PA_PD_DRV REG32(0x400010B4)
#define PB_DIR    REG32(0x400010C0)
#define PB_PIN    REG32(0x400010C4)
#define PB_PU     REG32(0x400010D0)
#define PB_PD_DRV REG32(0x400010D4)

/* A row driven low pulls the column of each pressed key low through its diode. */
#define ESC_ROW (1u << 5)   /* PA5, row 0 */
#define ESC_COL (1u << 13)  /* PA13, column 0 */
#define L_ROW   (1u << 1)   /* PA1, row 3 */
#define L_COL   (1u << 17)  /* PB17, column 9 */

void fw_xt32m_tune(uint32_t value);
void fw_enter_boot(void);
void knob_init(void);
void led_init(void);

static void spin(uint32_t n)
{
    while (n--)
        __asm__ volatile("");
}

static int col_low(uint32_t row, volatile uint32_t *pin, uint32_t col)
{
    int low;

    PA_CLR = row;
    PA_DIR |= row;
    spin(200);
    low = !(*pin & col);
    PA_DIR &= ~row;
    return low;
}

static int esc_l_held(void)
{
    uint32_t pa_dir = PA_DIR, pa_out = PA_OUT, pa_pu = PA_PU, pa_pd = PA_PD_DRV;
    uint32_t pb_dir = PB_DIR, pb_pu = PB_PU, pb_pd = PB_PD_DRV;
    int held = 0;

    PA_DIR = pa_dir & ~(ESC_ROW | L_ROW | ESC_COL);
    PA_PD_DRV = pa_pd & ~(ESC_ROW | L_ROW | ESC_COL);
    PA_PU = (pa_pu & ~(ESC_ROW | L_ROW)) | ESC_COL;
    PB_DIR = pb_dir & ~L_COL;
    PB_PD_DRV = pb_pd & ~L_COL;
    PB_PU = pb_pu | L_COL;
    spin(2000);
    /* A column already low with its row released is held down by something else. */
    if ((PA_PIN & ESC_COL) && (PB_PIN & L_COL)) {
        held = 1;
        for (int i = 0; i < 16 && held; i++) {
            spin(20000);
            held = col_low(ESC_ROW, &PA_PIN, ESC_COL) && col_low(L_ROW, &PB_PIN, L_COL);
        }
    }
    PA_OUT = pa_out;
    PA_DIR = pa_dir;
    PA_PU = pa_pu;
    PA_PD_DRV = pa_pd;
    PB_DIR = pb_dir;
    PB_PU = pb_pu;
    PB_PD_DRV = pb_pd;
    return held;
}

/* Replaces main()'s early fw_xt32m_tune(4) call. Esc + L held at power-up enters the
 * vendor boot's USB flash mode, so recovering from a bad patch never needs the case
 * opened. */
void hook_call(uint32_t value)
{
    knob_init();
    led_init();
    fw_xt32m_tune(value);
    if (esc_l_held())
        fw_enter_boot();   /* resets into the boot; returns only if the flag write failed */
}

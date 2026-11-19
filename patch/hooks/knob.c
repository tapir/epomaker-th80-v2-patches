#include <stdint.h>

#define REG32(a)  (*(volatile uint32_t *)(a))
#define REG16(a)  (*(volatile uint16_t *)(a))
#define PB_DIR    REG32(0x400010C0)
#define PB_PIN    REG32(0x400010C4)
#define PB_PU     REG32(0x400010D0)
#define PB_PD_DRV REG32(0x400010D4)
#define RTC_TICKS REG16(0x40001038)   /* 32768 Hz, wraps every 2 s */
#define MS(n)     ((uint16_t)((n) * 33))

#define WINMAC (1u << 1)  /* PB1, low = Mac */
#define KNOB_B (1u << 2)  /* PB2 */
#define KNOB_A (1u << 3)  /* PB3, changes first when turning clockwise */
#define KNOB_P (1u << 4)  /* PB4, knob push, low = pressed */
#define PINS   (WINMAC | KNOB_B | KNOB_A | KNOB_P)
#define MODE   ((1u << 20) | (1u << 21))  /* mode switch: PB20 low = BT, PB21 low = 2.4G */

/* Keymap slots reserved for the knob in patches.py, as (column, row). */
#define VOL_COL   14
#define VOLUP_ROW 0
#define VOLDN_ROW 4
#define MUTE_COL  13
#define MUTE_ROW  0

#define SET_OS(mac) (0x0000050Au | (uint32_t)(mac) << 16)  /* keymap entry 0A 05 os 00 */

uint32_t fw_tick(uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3);
void fw_release_keys(void);
void fw_key_event(uint32_t col, uint32_t row, uint32_t pressed);
void fw_special_key(uint32_t entry, uint32_t pressed);

static struct {
    uint8_t  ready;    /* 0 pull-ups off, 1 settling, 2 running */
    uint8_t  ab;       /* last knob sample: bit 1 = A, bit 0 = B */
    uint8_t  detent;   /* last detent reached: 0 or 3 */
    uint8_t  mid;      /* half step seen since leaving it (1 or 2), 0 = none */
    int8_t   pending;  /* clicks not sent yet, positive = clockwise */
    uint8_t  phase;    /* 0 idle, 1 volume key held, 2 pause after release */
    uint8_t  up;       /* the held key is volume up */
    uint8_t  push;     /* debounced knob push */
    uint8_t  mac;      /* Win/Mac state sent to the firmware, 2 = none yet */
    uint16_t t_key, t_push, t_mac;
} st;

/* Called from hook_call: st lives in RAM nothing zeroes. */
void knob_init(void)
{
    volatile uint8_t *p = (volatile uint8_t *)&st;

    for (unsigned i = 0; i < sizeof(st); i++)
        p[i] = 0;
}

/* The firmware rewrites these registers too, from interrupts as well. */
static uint32_t irq_off(void)
{
    uint32_t irq;

    __asm__ volatile("csrrc %0, 0x800, %1" : "=r"(irq) : "r"(0x88u) : "memory");
    return irq;
}

static void irq_on(uint32_t irq)
{
    __asm__ volatile("csrs 0x800, %0" : : "r"(irq & 0x88u) : "memory");
}

static void pullups_on(uint32_t pins)
{
    PB_DIR &= ~pins;
    PB_PD_DRV &= ~pins;
    PB_PU |= pins;
}

static void turn(uint8_t ab)
{
    if (ab == st.ab)
        return;
    st.ab = ab;
    if (ab == 1 || ab == 2) {
        st.mid = ab;
        return;
    }
    /* At a detent. Clockwise from 00 passes 10 (A first), from 11 it passes 01. */
    if (ab != st.detent && st.mid) {
        if (st.mid == (st.detent ? 1 : 2)) {
            if (st.pending < 8)
                st.pending++;
        } else if (st.pending > -8) {
            st.pending--;
        }
    }
    st.detent = ab;
    st.mid = 0;
}

/* One click = the volume key held 20 ms, then 10 ms released, so every click reaches the
 * host as its own press over USB, 2.4G and BT alike. */
static void send_turns(uint16_t now)
{
    if (st.phase == 2) {
        if ((uint16_t)(now - st.t_key) >= MS(10))
            st.phase = 0;
        return;
    }
    if (st.phase == 0) {
        if (!st.pending)
            return;
        st.up = st.pending > 0;
    } else if ((uint16_t)(now - st.t_key) < MS(20)) {
        return;
    }
    fw_key_event(VOL_COL, st.up ? VOLUP_ROW : VOLDN_ROW, st.phase == 0);
    if (st.phase == 1)
        st.pending += st.up ? -1 : 1;
    st.phase++;
    st.t_key = now;
}

/* Adopts `level` once it has differed from *state for `hold` ticks; returns 1 then. */
static int settle(uint8_t level, uint8_t *state, uint16_t *since, uint16_t now, uint16_t hold)
{
    if (level == *state) {
        *since = now;
        return 0;
    }
    if ((uint16_t)(now - *since) < hold)
        return 0;
    *state = level;
    return 1;
}

static void poll(void)
{
    uint16_t now = RTC_TICKS;
    uint32_t pin;
    uint8_t ab;

    if ((PB_PU & PINS) != PINS || (PB_DIR & PINS) || (PB_PD_DRV & PINS)) {
        uint32_t irq = irq_off();

        pullups_on(PINS);
        irq_on(irq);
        st.ready = 1;
        st.t_key = now;
        return;
    }
    pin = PB_PIN;
    ab = (pin & KNOB_A ? 2 : 0) | (pin & KNOB_B ? 1 : 0);
    if (st.ready != 2) {
        if (st.ready == 1 && (uint16_t)(now - st.t_key) < MS(2))
            return;
        st.ab = ab;
        st.detent = ab == 3 ? 3 : 0;
        st.mid = 0;
        st.push = !(pin & KNOB_P);
        st.mac = 2;
        st.t_push = st.t_mac = now;
        st.ready = 2;
        return;
    }
    turn(ab);
    send_turns(now);
    if (settle(!(pin & KNOB_P), &st.push, &st.t_push, now, MS(5)))
        fw_key_event(MUTE_COL, MUTE_ROW, st.push);
    if (settle(!(pin & WINMAC), &st.mac, &st.t_mac, now, MS(20))) {
        fw_special_key(SET_OS(st.mac), 1);
        fw_special_key(SET_OS(st.mac), 0);
    }
}

/* Replaces the tail call that ends the firmware's sleep preparation (0x143BE), which leaves
 * these pins as pull-up inputs: every closed knob, Win/Mac or mode-switch contact would draw
 * pull-up current for the whole sleep. A closed contact gets a pull-down instead, so no pin
 * conducts and none floats. After wake, 0x14566 restores the mode switch and poll() the
 * rest. */
void hook_sleep(void)
{
    uint32_t irq = irq_off(), closed;

    pullups_on(PINS | MODE);
    for (volatile int i = 0; i < 1000; i++)   /* the mode pins were driven low just before */
        ;
    closed = ~PB_PIN & (PINS | MODE);
    PB_PU &= ~closed;
    PB_PD_DRV |= closed;
    irq_on(irq);
    fw_release_keys();
}

/* Replaces the firmware's calls of fw_tick, made once per 1 kHz key-scan tick in every
 * connection mode. */
uint32_t hook_tick(uint32_t a0, uint32_t a1, uint32_t a2, uint32_t a3)
{
    poll();
    return fw_tick(a0, a1, a2, a3);
}

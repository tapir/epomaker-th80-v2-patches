#include <stdint.h>

#define REG8(a)  (*(volatile uint8_t *)(a))
#define REG16(a) (*(volatile uint16_t *)(a))
#define REG32(a) (*(volatile uint32_t *)(a))

#define SPI0_CTRL_MOD  REG8(0x40004000)
#define SPI0_CTRL_CFG  REG8(0x40004001)
#define SPI0_INT_FLAG  REG8(0x40004006)
#define SPI0_TOTAL_CNT REG16(0x4000400C)
#define SPI0_DMA_BEG   REG32(0x40004018)
#define SPI0_DMA_END   REG32(0x4000401C)
#define RTC_TICKS      REG16(0x40001038)   /* 32768 Hz */

/* Feature-report buffer: a command arrives in it and its reply leaves from it. Lighting
 * (0x07/0x87) and side light (0x08/0x88) share the layout
 * [op, mode, speed, brightness, (option << 4) | colour mode, R, G, B]. */
#define CMD ((volatile uint8_t *)0x2000F108)

#define BYTES   24   /* SPI bytes per LED: one per WS2812 bit, G R B, MSB first */
#define CK_LEDS 87   /* CK75SE frame: 80 keys, 3 indicators, 4 space-bar underglow */
#define TH_LEDS 116
#define SIDE    82   /* first TH80 side LED */
#define SIDE_N  (TH_LEDS - SIDE)
#define RAINBOW 8    /* colour mode; 7 = own RGB, 0-6 presets */

extern uint32_t fw_led_frame[CK_LEDS * BYTES / 4];
extern volatile uint8_t fw_side_light[7];   /* mode speed brightness flags R G B */
uint32_t fw_led_set(void);
uint32_t fw_led_get(void);
uint32_t fw_sled_set(void);
uint32_t fw_sled_get(void);

static uint32_t th[TH_LEDS * BYTES / 4] __attribute__((section(".bufram")));

static struct {
    uint32_t phase;    /* effect position, one cycle = 2^32 */
    uint16_t rtc;
    uint8_t  cycles;   /* completed cycles, for rainbow breathing */
    uint8_t  test;     /* 0x81 / 0x82 while a test pattern shows */
    uint8_t  a, b;     /* its side LEDs */
} sl;

/* Brightness 0-4 as the firmware's 0/25/50/75/100 %. */
static const uint8_t LEVEL[5] = {0, 64, 128, 191, 255};
/* Speed 0-4: one cycle in 8, 5.5, 4, 2.5 or 1.5 s. */
static const uint32_t RATE[5] = {16384, 23831, 32768, 52429, 87381};
/* Off, static, breathing, spectrum, wave, snake: cycle length as a shift of RATE. */
static const uint8_t SLOW[6] = {0, 0, 0, 2, 1, 0};
/* Side LED chain index -> position along the sides, for wave and snake. */
static const uint8_t SIDE_POS[SIDE_N] = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
    17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33,
};

/* Called from hook_call: sl lives in RAM nothing zeroes. */
void led_init(void)
{
    volatile uint8_t *p = (volatile uint8_t *)&sl;

    for (unsigned i = 0; i < sizeof(sl); i++)
        p[i] = 0;
}

/* Colour mode 7 = own RGB and 8 = rainbow in this firmware; Sharkfin's TH80 V2 profile
 * (taken from the vendor app) sends them the other way round. */
static void swap_rgb_rainbow(void)
{
    uint8_t b = CMD[4], mode = b & 0x0F;

    if (mode == 7 || mode == 8)
        CMD[4] = (b & 0xF0) | (15 - mode);
}

uint32_t hook_led_set(void)
{
    uint32_t r;

    swap_rgb_rainbow();
    r = fw_led_set();
    swap_rgb_rainbow();
    return r;
}

uint32_t hook_led_get(void)
{
    uint32_t r = fw_led_get();

    swap_rgb_rainbow();
    return r;
}

/* The CK75SE stores the side-light parameters but never draws them. A mode byte with bit 7
 * set selects a test pattern instead (tools/side_test.py); it isn't stored. */
uint32_t hook_sled_set(void)
{
    uint32_t r;

    if (CMD[1] & 0x80) {
        sl.test = CMD[1];
        sl.a = CMD[2];
        sl.b = CMD[3];
        return 0;
    }
    sl.test = 0;
    swap_rgb_rainbow();
    r = fw_sled_set();
    swap_rgb_rainbow();
    return r;
}

uint32_t hook_sled_get(void)
{
    uint32_t r = fw_sled_get();

    swap_rgb_rainbow();
    return r;
}

static void encode(uint8_t *p, uint32_t v)
{
    for (int i = 0; i < 8; i++, v <<= 1)
        p[i] = v & 0x80 ? 0xF0 : 0xC0;
}

/* The key LEDs' colour transform (0x7C74): squaring each channel and dividing by a weighted
 * sum caps the current of mixed colours. Then `scale` / 255. */
static void put(uint8_t *p, uint32_t r, uint32_t g, uint32_t b, uint32_t scale)
{
    uint32_t sum = g * 255 / 400 + r + b / 2;

    if (sum) {
        r = r * r * 250 / (sum * 255);
        g = g * g * 250 / (sum * 400);
        b = b * b * 250 / (sum * 510);
    } else {
        r = g = b = 0;
    }
    encode(p, g * scale / 255);
    encode(p + 8, r * scale / 255);
    encode(p + 16, b * scale / 255);
}

static void hue_rgb(uint32_t h, uint32_t c[3])
{
    uint32_t s, f;

    h &= 255;
    s = h / 43;
    f = (h - s * 43) * 6;
    c[0] = s == 0 || s == 5 ? 255 : s == 1 ? 255 - f : s == 4 ? f : 0;
    c[1] = s == 1 || s == 2 ? 255 : s == 0 ? f : s == 3 ? 255 - f : 0;
    c[2] = s == 3 || s == 4 ? 255 : s == 2 ? f : s == 5 ? 255 - f : 0;
}

static uint32_t tri(uint32_t x)
{
    x &= 255;
    return x < 128 ? x * 2 : (255 - x) * 2;
}

static void side_test(uint8_t *out)
{
    for (unsigned i = 0; i < SIDE_N; i++, out += BYTES) {
        if (sl.test == 0x81 && i >= sl.a && i <= sl.b)
            put(out, 0, 0, 255, 255);
        else if (sl.test == 0x82 && i == sl.a)
            put(out, 255, 255, 255, 255);
        else if (sl.test == 0x82 && i == sl.b)
            put(out, 0, 0, 255, 255);
        else
            put(out, 0, 0, 0, 0);
    }
}

/* Sharkfin's edge-light modes: 0 off, 1 static, 2 breathing, 3 spectrum, 4 wave, 5 snake. */
static void side_render(uint8_t *out)
{
    uint32_t mode = fw_side_light[0], speed = fw_side_light[1], bright = fw_side_light[2];
    uint32_t rainbow = (fw_side_light[3] & 0x0F) == RAINBOW;
    uint32_t own[3] = {fw_side_light[4], fw_side_light[5], fw_side_light[6]};
    uint16_t now = RTC_TICKS, dt = now - sl.rtc;
    uint32_t old = sl.phase, p8, head;

    sl.rtc = now;
    if (dt > 3277)   /* first frame, or frames resuming after the LEDs were off: no jump */
        dt = 3277;
    if (speed > 4)
        speed = 4;
    if (bright > 4)
        bright = 4;
    if (mode > 5)
        mode = 1;
    sl.phase += dt * (RATE[speed] >> SLOW[mode]);
    if (sl.phase < old)
        sl.cycles++;
    if (sl.test & 0x7F) {
        side_test(out);
        return;
    }
    p8 = sl.phase >> 24;
    head = (sl.phase >> 16) * SIDE_N >> 8;   /* snake head, 1/256 LED */

    for (unsigned i = 0; i < SIDE_N; i++, out += BYTES) {
        uint32_t pos = SIDE_POS[i], hue = pos * 256 / SIDE_N, level = 255, c[3];
        int32_t d;

        c[0] = own[0];
        c[1] = own[1];
        c[2] = own[2];
        switch (mode) {
        case 0:
            level = 0;
            break;
        case 2:
            level = tri(p8) * tri(p8) / 255;
            hue = sl.cycles * 43;
            break;
        case 3:
            hue = p8;
            rainbow = 1;
            break;
        case 4:
            if (rainbow)
                hue -= p8;
            else
                level = tri(hue - p8);
            break;
        case 5:
            d = (int32_t)head - (int32_t)(pos * 256);
            if (d < 0)
                d += SIDE_N * 256;
            level = d < 8 * 256 ? 255 - (uint32_t)d * 255 / (8 * 256) : 0;
            break;
        }
        if (rainbow)
            hue_rgb(hue, c);
        put(out, c[0], c[1], c[2], LEVEL[bright] * level / 255);
    }
}

static void copy(uint32_t *dst, const uint32_t *src, unsigned leds)
{
    for (unsigned n = leds * BYTES / 4; n; n--)
        *dst++ = *src++;
}

/* Called by hook_led_send (led_send.S) with the stock routine's arguments. CK75SE LED 13 is
 * its 14th top-row key, where the TH80 has its knob; from its LED 14 on, the TH80 chain is
 * one LED earlier, the 3 indicators included. */
void led_send(const uint32_t *buf, uint32_t len)
{
    if (!(SPI0_INT_FLAG & 0x01))   /* the previous frame is still going out */
        return;
    if (buf == fw_led_frame && len == sizeof(fw_led_frame)) {
        copy(th, fw_led_frame, 13);
        copy(th + 13 * BYTES / 4, fw_led_frame + 14 * BYTES / 4, SIDE - 13);
        side_render((uint8_t *)(th + SIDE * BYTES / 4));
        buf = th;
        len = sizeof(th);
    }
    SPI0_CTRL_MOD &= ~0x10;
    SPI0_DMA_BEG = (uint32_t)buf;
    SPI0_DMA_END = (uint32_t)buf + len;
    SPI0_TOTAL_CNT = len;
    SPI0_INT_FLAG = 0x09;
    SPI0_CTRL_CFG |= 0x01;
}

#include <stdint.h>

/* Byte 4 of the feature-report buffer: (option << 4) | colour mode. The lighting command
 * arrives in this buffer and its reply leaves from it. */
#define LED_FLAGS (*(volatile uint8_t *)0x2000F10C)

uint32_t fw_led_set(void);
uint32_t fw_led_get(void);

/* Colour mode 7 = own RGB and 8 = rainbow in this firmware; Sharkfin's TH80 V2 profile
 * (taken from the vendor app) sends them the other way round. */
static void swap_rgb_rainbow(void)
{
    uint8_t b = LED_FLAGS, mode = b & 0x0F;

    if (mode == 7 || mode == 8)
        LED_FLAGS = (b & 0xF0) | (15 - mode);
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

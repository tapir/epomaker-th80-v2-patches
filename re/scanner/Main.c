/********************************** (C) COPYRIGHT *******************************
 * File Name          : Main.c
 * Author             : WCH
 * Version            : V1.1
 * Date               : 2022/01/25
 * Description        : TH80 V2 pin scanner (from the WCH CH585 USB HID example)
 *********************************************************************************
 * Copyright (c) 2021 Nanjing Qinheng Microelectronics Co., Ltd.
 * Attention: This software (modified or not) and binary are used for 
 * microcontroller manufactured by Nanjing Qinheng Microelectronics.
 *******************************************************************************/

#include "CH58x_common.h"

#define DevEP0SIZE    0x40
#define DevEP1SIZE    0x40
const uint8_t MyDevDescr[] = {0x12,0x01,0x10,0x01,0x00,0x00,0x00,DevEP0SIZE,0x09,0x12,0xA4,0x5C,0x00,0x00,0x00,0x00,0x00,0x01};
const uint8_t MyCfgDescr[] = {
    0x09,0x02,0x29,0x00,0x01,0x01,0x04,0xA0,0x23,
    0x09,0x04,0x00,0x00,0x02,0x03,0x00,0x00,0x05,
    0x09,0x21,0x00,0x01,0x00,0x01,0x22,0x22,0x00,
    0x07,0x05,0x81,0x03,DevEP1SIZE,0x00,0x01,
    0x07,0x05,0x01,0x03,DevEP1SIZE,0x00,0x01
};
const uint8_t HIDDescr[] = {  0x06, 0x00,0xff,
                              0x09, 0x01,
                              0xa1, 0x01,
                              0x09, 0x02,                                                   // Usage Page
                              0x15, 0x00,                                                   //Logical  Minimun
                              0x26, 0x00,0xff,                                              //Logical  Maximun
                              0x75, 0x08,                                                   //Report Size
                              0x95, 0x40,                                                   //Report Counet
                              0x81, 0x06,                                                   //Input
                              0x09, 0x02,                                                   // Usage Page
                              0x15, 0x00,                                                   //Logical  Minimun
                              0x26, 0x00,0xff,                                              //Logical  Maximun
                              0x75, 0x08,                                                   //Report Size
                              0x95, 0x40,                                                   //Report Counet
                              0x91, 0x06,                                                   //Output
                              0xC0};

/**********************************************************/
uint8_t        DevConfig, Ready = 0;
uint8_t        SetupReqCode;
uint16_t       SetupReqLen;
const uint8_t *pDescr;
uint8_t        Report_Value = 0x00;
uint8_t        Idle_Value = 0x00;
uint8_t        USB_SleepStatus = 0x00;

uint8_t HID_Buf[DevEP1SIZE] = {0,0,0,0};

__attribute__((aligned(4))) uint8_t EP0_Databuf[64 + 64 + 64]; //ep0(64)+ep4_out(64)+ep4_in(64)
__attribute__((aligned(4))) uint8_t EP1_Databuf[64 + 64];      //ep1_out(64)+ep1_in(64)
__attribute__((aligned(4))) uint8_t EP2_Databuf[64 + 64];      //ep2_out(64)+ep2_in(64)
__attribute__((aligned(4))) uint8_t EP3_Databuf[64 + 64];      //ep3_out(64)+ep3_in(64)

/*********************************************************************
 * @fn      USB_DevTransProcess
 *
 * @return  none
 */
void USB_DevTransProcess(void)
{
    uint8_t len, chtype;
    uint8_t intflag, errflag = 0;

    intflag = R8_USB_INT_FG;

    if(intflag & RB_UIF_TRANSFER)
    {
        if((R8_USB_INT_ST & MASK_UIS_TOKEN) != MASK_UIS_TOKEN)
        {
            switch(R8_USB_INT_ST & (MASK_UIS_TOKEN | MASK_UIS_ENDP))
            {
                case UIS_TOKEN_IN:
                {
                    switch(SetupReqCode)
                    {
                        case USB_GET_DESCRIPTOR:
                            len = SetupReqLen >= DevEP0SIZE ? DevEP0SIZE : SetupReqLen;
                            memcpy(pEP0_DataBuf, pDescr, len);
                            SetupReqLen -= len;
                            pDescr += len;
                            R8_UEP0_T_LEN = len;
                            R8_UEP0_CTRL ^= RB_UEP_T_TOG;
                            break;
                        case USB_SET_ADDRESS:
                            R8_USB_DEV_AD = (R8_USB_DEV_AD & RB_UDA_GP_BIT) | SetupReqLen;
                            R8_UEP0_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
                            break;

                        case USB_SET_FEATURE:
                            break;

                        default:
                            R8_UEP0_T_LEN = 0;
                            R8_UEP0_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
                            Ready = 1;
                            PRINT("Ready_STATUS = %d\n",Ready);
                            break;
                    }
                }
                break;

                case UIS_TOKEN_OUT:
                {
                    len = R8_USB_RX_LEN;
                }
                break;

                case UIS_TOKEN_OUT | 1:
                {
                    if(R8_USB_INT_ST & RB_UIS_TOG_OK)
                    {
                        R8_UEP1_CTRL ^= RB_UEP_R_TOG;
                        len = R8_USB_RX_LEN;
                        DevEP1_OUT_Deal(len);
                    }
                }
                break;

                case UIS_TOKEN_IN | 1:
                    R8_UEP1_CTRL ^= RB_UEP_T_TOG;
                    R8_UEP1_CTRL = (R8_UEP1_CTRL & ~MASK_UEP_T_RES) | UEP_T_RES_NAK;
                    Ready = 1;
                    PRINT("Ready_IN_EP1 = %d\n",Ready);
                    break;
            }
            R8_USB_INT_FG = RB_UIF_TRANSFER;
        }

        if(R8_USB_INT_ST & RB_UIS_SETUP_ACT)
        {
            R8_UEP0_CTRL = RB_UEP_R_TOG | RB_UEP_T_TOG | UEP_R_RES_ACK | UEP_T_RES_NAK;
            SetupReqLen = pSetupReqPak->wLength;
            SetupReqCode = pSetupReqPak->bRequest;
            chtype = pSetupReqPak->bRequestType;

            len = 0;
            errflag = 0;
            if((pSetupReqPak->bRequestType & USB_REQ_TYP_MASK) != USB_REQ_TYP_STANDARD)
            {
                if(pSetupReqPak->bRequestType & 0x40)
                {
                }
                else if(pSetupReqPak->bRequestType & 0x20)
                {
                    switch(SetupReqCode)
                    {
                        case DEF_USB_SET_IDLE: /* 0x0A: SET_IDLE */
                            Idle_Value = EP0_Databuf[3];
                            break;

                        case DEF_USB_SET_REPORT: /* 0x09: SET_REPORT */
                            break;

                        case DEF_USB_SET_PROTOCOL: /* 0x0B: SET_PROTOCOL */
                            Report_Value = EP0_Databuf[2];
                            break;

                        case DEF_USB_GET_IDLE: /* 0x02: GET_IDLE */
                            EP0_Databuf[0] = Idle_Value;
                            len = 1;
                            break;

                        case DEF_USB_GET_PROTOCOL: /* 0x03: GET_PROTOCOL */
                            EP0_Databuf[0] = Report_Value;
                            len = 1;
                            break;

                        default:
                            errflag = 0xFF;
                    }
                }
            }
            else
            {
                switch(SetupReqCode)
                {
                    case USB_GET_DESCRIPTOR:
                    {
                        switch(((pSetupReqPak->wValue) >> 8))
                        {
                            case USB_DESCR_TYP_DEVICE:
                            {
                                pDescr = MyDevDescr;
                                len = MyDevDescr[0];
                            }
                            break;

                            case USB_DESCR_TYP_CONFIG:
                            {
                                pDescr = MyCfgDescr;
                                len = MyCfgDescr[2];
                            }
                            break;

                            case USB_DESCR_TYP_HID:
                                switch((pSetupReqPak->wIndex) & 0xff)
                                {
                                    case 0:
                                        pDescr = (uint8_t *)(&MyCfgDescr[18]);
                                        len = 9;
                                        break;

                                    default:
                                        errflag = 0xff;
                                        break;
                                }
                                break;

                            case USB_DESCR_TYP_REPORT:
                            {
                                if(((pSetupReqPak->wIndex) & 0xff) == 0)
                                {
                                    pDescr = HIDDescr;
                                    len = sizeof(HIDDescr);
                                }
                                else
                                    len = 0xff;
                            }
                            break;

                            case USB_DESCR_TYP_STRING:
                            {
                                switch((pSetupReqPak->wValue) & 0xff)
                                {
                                    default:
                                        errflag = 0xFF;
                                        break;
                                }
                            }
                            break;

                            default:
                                errflag = 0xff;
                                break;
                        }
                        if(SetupReqLen > len)
                            SetupReqLen = len;
                        len = (SetupReqLen >= DevEP0SIZE) ? DevEP0SIZE : SetupReqLen;
                        memcpy(pEP0_DataBuf, pDescr, len);
                        pDescr += len;
                    }
                    break;

                    case USB_SET_ADDRESS:
                        SetupReqLen = (pSetupReqPak->wValue) & 0xff;
                        break;

                    case USB_GET_CONFIGURATION:
                        pEP0_DataBuf[0] = DevConfig;
                        if(SetupReqLen > 1)
                            SetupReqLen = 1;
                        break;

                    case USB_SET_CONFIGURATION:
                        DevConfig = (pSetupReqPak->wValue) & 0xff;
                        break;

                    case USB_CLEAR_FEATURE:
                    {
                        if((pSetupReqPak->bRequestType & USB_REQ_RECIP_MASK) == USB_REQ_RECIP_ENDP)
                        {
                            switch((pSetupReqPak->wIndex) & 0xff)
                            {
                                case 0x81:
                                    R8_UEP1_CTRL = (R8_UEP1_CTRL & ~(RB_UEP_T_TOG | MASK_UEP_T_RES)) | UEP_T_RES_NAK;
                                    break;
                                case 0x01:
                                    R8_UEP1_CTRL = (R8_UEP1_CTRL & ~(RB_UEP_R_TOG | MASK_UEP_R_RES)) | UEP_R_RES_ACK;
                                    break;
                                default:
                                    errflag = 0xFF;
                                    break;
                            }
                        }
                        else if((pSetupReqPak->bRequestType & USB_REQ_RECIP_MASK) == USB_REQ_RECIP_DEVICE)
                        {
                            if(pSetupReqPak->wValue == 1)
                            {
                                USB_SleepStatus &= ~0x01;
                            }
                        }
                        else
                        {
                            errflag = 0xFF;
                        }
                    }
                    break;

                    case USB_SET_FEATURE:
                        if((pSetupReqPak->bRequestType & USB_REQ_RECIP_MASK) == USB_REQ_RECIP_ENDP)
                        {
                            switch(pSetupReqPak->wIndex)
                            {
                                case 0x81:
                                    R8_UEP1_CTRL = (R8_UEP1_CTRL & ~(RB_UEP_T_TOG | MASK_UEP_T_RES)) | UEP_T_RES_STALL;
                                    break;
                                case 0x01:
                                    R8_UEP1_CTRL = (R8_UEP1_CTRL & ~(RB_UEP_R_TOG | MASK_UEP_R_RES)) | UEP_R_RES_STALL;
                                    break;
                                default:
                                    errflag = 0xFF;
                                    break;
                            }
                        }
                        else if((pSetupReqPak->bRequestType & USB_REQ_RECIP_MASK) == USB_REQ_RECIP_DEVICE)
                        {
                            if(pSetupReqPak->wValue == 1)
                            {
                                USB_SleepStatus |= 0x01;
                            }
                        }
                        else
                        {
                            errflag = 0xFF;
                        }
                        break;

                    case USB_GET_INTERFACE:
                        pEP0_DataBuf[0] = 0x00;
                        if(SetupReqLen > 1)
                            SetupReqLen = 1;
                        break;

                    case USB_SET_INTERFACE:
                        break;

                    case USB_GET_STATUS:
                        if((pSetupReqPak->bRequestType & USB_REQ_RECIP_MASK) == USB_REQ_RECIP_ENDP)
                        {
                            pEP0_DataBuf[0] = 0x00;
                            switch(pSetupReqPak->wIndex)
                            {
                                case 0x81:
                                    if((R8_UEP1_CTRL & (RB_UEP_T_TOG | MASK_UEP_T_RES)) == UEP_T_RES_STALL)
                                    {
                                        pEP0_DataBuf[0] = 0x01;
                                    }
                                    break;

                                case 0x01:
                                    if((R8_UEP1_CTRL & (RB_UEP_R_TOG | MASK_UEP_R_RES)) == UEP_R_RES_STALL)
                                    {
                                        pEP0_DataBuf[0] = 0x01;
                                    }
                                    break;
                            }
                        }
                        else if((pSetupReqPak->bRequestType & USB_REQ_RECIP_MASK) == USB_REQ_RECIP_DEVICE)
                        {
                            pEP0_DataBuf[0] = 0x00;
                            if(USB_SleepStatus)
                            {
                                pEP0_DataBuf[0] = 0x02;
                            }
                            else
                            {
                                pEP0_DataBuf[0] = 0x00;
                            }
                        }
                        pEP0_DataBuf[1] = 0;
                        if(SetupReqLen >= 2)
                        {
                            SetupReqLen = 2;
                        }
                        break;

                    default:
                        errflag = 0xff;
                        break;
                }
            }
            if(errflag == 0xff)
            {
                //                  SetupReqCode = 0xFF;
                R8_UEP0_CTRL = RB_UEP_R_TOG | RB_UEP_T_TOG | UEP_R_RES_STALL | UEP_T_RES_STALL; // STALL
                Ready = 1;
                PRINT("Ready_Stall = %d\n",Ready);
            }
            else
            {
                if(chtype & 0x80)
                {
                    len = (SetupReqLen > DevEP0SIZE) ? DevEP0SIZE : SetupReqLen;
                    SetupReqLen -= len;
                }
                else
                    len = 0;
                R8_UEP0_T_LEN = len;
                R8_UEP0_CTRL = RB_UEP_R_TOG | RB_UEP_T_TOG | UEP_R_RES_ACK | UEP_T_RES_ACK;
            }

            R8_USB_INT_FG = RB_UIF_TRANSFER;
        }
    }


    else if(intflag & RB_UIF_BUS_RST)
    {
        R8_USB_DEV_AD = 0;
        R8_UEP0_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
        R8_UEP1_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
        R8_UEP2_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
        R8_UEP3_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
        R8_USB_INT_FG = RB_UIF_BUS_RST;
    }
    else if(intflag & RB_UIF_SUSPEND)
    {
        if(R8_USB_MIS_ST & RB_UMS_SUSPEND)
        {
            Ready = 0;
            PRINT("Ready_Sleep = %d\n",Ready);
        }
        else
        {
            Ready = 1;
            PRINT("Ready_WeakUp = %d\n",Ready);
        }
        R8_USB_INT_FG = RB_UIF_SUSPEND;
    }
    else
    {
        R8_USB_INT_FG = intflag;
    }
}

/*********************************************************************
 * @fn      DevHIDReport
 *
 */
void DevHIDReport(uint8_t data0,uint8_t data1,uint8_t data2,uint8_t data3)
{
    HID_Buf[0] = data0;
    HID_Buf[1] = data1;
    HID_Buf[2] = data2;
    HID_Buf[3] = data3;
    memcpy(pEP1_IN_DataBuf, HID_Buf, sizeof(HID_Buf));
    DevEP1_IN_Deal(DevEP1SIZE);
}

/*********************************************************************
 * @fn      DevWakeup
 *
 * @return  none
 */
void DevWakeup(void)
{
    R16_PIN_CONFIG &= ~(RB_UDP_PU_EN);
    R8_UDEV_CTRL |= RB_UD_LOW_SPEED;
    mDelaymS(2);
    R8_UDEV_CTRL &= ~RB_UD_LOW_SPEED;
    R16_PIN_CONFIG |= RB_UDP_PU_EN;
}

/*********************************************************************
 * @fn      DebugInit
 *
 * @return  none
 */
void DebugInit(void)
{
    GPIOA_SetBits(GPIO_Pin_14);
    GPIOPinRemap(ENABLE, RB_PIN_UART0);
    GPIOA_ModeCfg(GPIO_Pin_15, GPIO_ModeIN_PU);
    GPIOA_ModeCfg(GPIO_Pin_14, GPIO_ModeOut_PP_5mA);
    UART0_DefInit();
}

/*********************************************************************
 * @fn      main
 *
 * @return  none
 */
/* ---- TH80 V2 pin scanner ---- */
__attribute__((section(".app_tag"), used)) const uint8_t app_tag[16] = "CH584M 1KKB 1M  ";

#define BOOT_FLAG_ADDR 0x4000
#define BOOT_FLAG      0x55AA55AAu   /* vendor boot enters USB flash mode on this, then erases the page itself */

static volatile uint8_t cmd_req;     /* flash ops run from main(), not the USB ISR */
static uint8_t  cmd_arg[4];          /* report bytes after the 55 AA 55 AA magic */
static uint8_t  status[64];
static uint16_t status_left;         /* reports still to send as status instead of scan data */
static uint8_t  reset_after_status;
static uint8_t  led_mode;            /* LED test running: the scan would reconfigure its pins */
static uint8_t  led_pattern;
static uint32_t led_tick;

#define LED_N 128  /* longer than the chain; extra data falls off the end */
__attribute__((aligned(4))) static uint8_t led_frame[40 + LED_N * 24 + 40];
static uint8_t  led_bits[2][LED_N / 8];   /* pattern 3: blue map, white map */

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

/* Every hardware wait is bounded: with the mode switch on BT/2.4G the battery keeps the
 * chip running through a USB unplug, so a hang would persist. */
static int spi0_dma_send(uint8_t *p, uint16_t len)
{
    R8_SPI0_CTRL_MOD &= ~RB_SPI_FIFO_DIR;
    R32_SPI0_DMA_BEG = (uint32_t)p;
    R32_SPI0_DMA_END = (uint32_t)(p + len);
    R16_SPI0_TOTAL_CNT = len;
    R8_SPI0_INT_FLAG = RB_SPI_IF_CNT_END | RB_SPI_IF_DMA_END;
    R8_SPI0_CTRL_CFG |= RB_SPI_DMA_ENABLE;
    for (uint32_t n = 0; !(R8_SPI0_INT_FLAG & RB_SPI_IF_CNT_END); n++)
        if (n > 1000000) {
            R8_SPI0_CTRL_CFG &= ~RB_SPI_DMA_ENABLE;
            return 1;
        }
    R8_SPI0_CTRL_CFG &= ~RB_SPI_DMA_ENABLE;
    return 0;
}

static uint16_t adc_once(void)
{
    R8_ADC_CONVERT |= RB_ADC_START;
    for (uint32_t n = 0; R8_ADC_CONVERT & (RB_ADC_START | RB_ADC_EOC_X); n++)
        if (n > 100000)
            return 0xFFFF;
    return R16_ADC_DATA & RB_ADC_DATA;
}

/* WS2812 over SPI0 the way the CK75SE drives it: MOSI = PA14, one SPI byte per LED bit
 * (0xF0 = 1, 0xC0 = 0) at 6.24 MHz, GRB order. 40 zero bytes (> 50 us low) on each side
 * reset the chain. */
static uint32_t led_color(uint8_t pattern, uint8_t first, int i)
{
    if (pattern == 1)   /* LEDs first..first+2 blue, the rest dim green */
        return (unsigned)(i - first) < 3 ? 64u : 12u << 16;
    if (pattern == 2 && i == 0)   /* Esc shows PB0, refreshed from main() */
        return (R32_PB_PIN & 1) ? 0x404040 : 0;
    if (pattern == 2 && i == 1)   /* F1 blinks to show the firmware is running */
        return (led_tick / 240) & 1 ? 0x404040 : 0;
    if (pattern == 3 && (led_bits[0][i >> 3] >> (i & 7) & 1))
        return 64u;
    if (pattern == 3 && (led_bits[1][i >> 3] >> (i & 7) & 1))
        return 0x303030;
    return 0;
}

static int led_show(uint8_t pattern, uint8_t first)
{
    uint8_t *p = led_frame + 40;

    memset(led_frame, 0, sizeof(led_frame));
    for (int i = 0; i < LED_N; i++) {
        uint32_t grb = led_color(pattern, first, i);
        for (int b = 23; b >= 0; b--)
            *p++ = (grb >> b) & 1 ? 0xF0 : 0xC0;
    }
    return spi0_dma_send(led_frame, sizeof(led_frame));
}

/* PA4 (ADC input 0) at 1/100/300/600 ms after its pull-up is released: a divider behind
 * a filter cap needs time to settle. Then the chip's own supply and PB0. */
static void adc_report(uint8_t *p)
{
    static const uint16_t at_ms[4] = {1, 100, 300, 600};
    uint16_t raw, t = 0;

    GPIOA_ModeCfg(GPIO_Pin_4, GPIO_ModeIN_Floating);
    ADC_ExtSingleChSampInit(SampleFreq_4_or_2, ADC_PGA_1_4);
    ADC_ChannelCfg(CH_EXTIN_0);
    for (int i = 0; i < 4; i++) {
        mDelaymS(at_ms[i] - t);
        t = at_ms[i];
        raw = adc_once();
        p[2 * i] = raw;
        p[2 * i + 1] = raw >> 8;
    }
    ADC_InterBATSampInit();
    mDelaymS(1);
    raw = adc_once();
    p[8] = raw;
    p[9] = raw >> 8;
    p[10] = R32_PB_PIN & 1;
}

/* 0x7E: report flash state, PA4 ADC and PB0. 0x7F: set the boot flag the way the stock
 * firmware does (erase, write, verify), then reset into the boot once the status went out.
 * 0x7C: LED test, cmd_arg = PA15 level, PB19 level, pattern, first marker LED; pattern 3
 * takes the blue and white LED bitmaps that follow the args. 0x7B: LEDs off, scan again. */
static void RunCmd(uint8_t cmd)
{
    uint32_t rc_e = ~0u, rc_w = ~0u, rc_v = ~0u, rc_m, irq;
    uint32_t buf[1], mac[2] = {0, 0};   /* the lib requires RAM, 4-byte aligned buffers */
    uint8_t tries = 0;

    rc_m = GetMACAddress(mac);
    if (cmd == 0x7F) {
        do {
            tries++;
            buf[0] = BOOT_FLAG;
            SYS_DisableAllIrq(&irq);   /* the USB ISR runs code from flash */
            rc_e = FLASH_ROM_ERASE(BOOT_FLAG_ADDR, 0x1000);
            rc_w = FLASH_ROM_WRITE(BOOT_FLAG_ADDR, buf, 4);
            rc_v = FLASH_ROM_VERIFY(BOOT_FLAG_ADDR, buf, 4);
            SYS_RecoverIrq(irq);
        } while (rc_v && tries < 3);
        reset_after_status = (rc_v == 0);
    }
    memset(status, 0, sizeof(status));
    if (cmd == 0x7E)
        adc_report(&status[40]);
    if (cmd == 0x7C) {
        led_mode = 1;
        R32_PA_DIR = 0;   /* release whichever pin the scan last drove low */
        R32_PB_DIR = 0;
        GPIOA_ModeCfg(GPIO_Pin_14 | GPIO_Pin_15, GPIO_ModeOut_PP_5mA);
        GPIOB_ModeCfg(GPIO_Pin_19, GPIO_ModeOut_PP_5mA);
        if (cmd_arg[0]) GPIOA_SetBits(GPIO_Pin_15); else GPIOA_ResetBits(GPIO_Pin_15);
        if (cmd_arg[1]) GPIOB_SetBits(GPIO_Pin_19); else GPIOB_ResetBits(GPIO_Pin_19);
        mDelaymS(20);   /* LED supply ramp-up */
        status[45] = R8_SLP_CLK_OFF1;
        sys_safe_access_enable();
        R8_SLP_CLK_OFF1 &= ~RB_SLP_CLK_SPI0;
        sys_safe_access_disable();
        SPI0_MasterDefInit();
        SPI0_CLKCfg(10);
        memcpy(&status[40], cmd_arg, sizeof(cmd_arg));
        led_pattern = cmd_arg[2];
        status[44] = led_show(cmd_arg[2], cmd_arg[3]);
    }
    if (cmd == 0x7B && led_mode) {
        status[44] = led_show(0, 0);
        GPIOA_ResetBits(GPIO_Pin_15);
        GPIOB_ResetBits(GPIO_Pin_19);
        led_mode = 0;
    }
    status[0] = 0x5A; status[1] = cmd; status[2] = tries;
    status[3] = R8_CHIP_ID; status[4] = R8_GLOB_CFG_INFO;
    put32(&status[8],  *(volatile uint32_t *)BOOT_FLAG_ADDR);
    put32(&status[12], *(volatile uint32_t *)0x5300);
    put32(&status[16], rc_e);
    put32(&status[20], rc_w);
    put32(&status[24], rc_v);
    put32(&status[28], rc_m);
    put32(&status[32], mac[0]);
    put32(&status[36], mac[1]);
    status_left = 250;
}

#define REG32(a) (*(volatile uint32_t *)(a))
#define PA_DIR REG32(0x400010A0)
#define PA_PIN REG32(0x400010A4)
#define PA_OUT REG32(0x400010A8)
#define PA_PU  REG32(0x400010B0)
#define PB_DIR REG32(0x400010C0)
#define PB_PIN REG32(0x400010C4)
#define PB_OUT REG32(0x400010C8)
#define PB_PU  REG32(0x400010D0)

static uint8_t drive = 0;   /* active-scan pin 0..39 */
static uint8_t seq = 0;
static uint8_t phase = 0;   /* 0 = passive baseline, 1 = active scan (alternating) */

/* Alternate passive baseline (all inputs+pullup, drive=40) with active scan
 * (drive one pin low, read the rest). The frequent baseline lets us watch the
 * mode-switch and encoder pins change state without losing USB. A pressed key
 * shorts its row/col so the connected pin reads low during active scan. */
static void ScanStep(void)
{
    uint8_t buf[64];
    uint32_t pa, pb;
    uint8_t d;
    memset(buf, 0, sizeof(buf));
    PA_DIR = 0; PB_DIR = 0;
    PA_PU = 0xFFFF; PB_PU = 0xFFFFFF;
    PA_OUT = 0; PB_OUT = 0;
    if (phase) {
        d = drive;
        if (d < 16)      PA_DIR = (1u << d);
        else if (d < 40) PB_DIR = (1u << (d - 16));
        drive++; if (drive >= 40) drive = 0;
    } else {
        d = 40;   /* passive: every pin is an input */
    }
    phase ^= 1;
    mDelayuS(50);
    pa = PA_PIN; pb = PB_PIN;
    buf[0] = 0xA5; buf[1] = d;
    buf[2] = pa & 0xFF; buf[3] = (pa >> 8) & 0xFF;
    buf[4] = pb & 0xFF; buf[5] = (pb >> 8) & 0xFF; buf[6] = (pb >> 16) & 0xFF;
    buf[7] = seq++;
    memcpy(pEP1_IN_DataBuf, buf, 64);
    DevEP1_IN_Deal(64);
}

int main()
{
    HSECFG_Capacitance(HSECap_18p);
    SetSysClock(SYSCLK_FREQ);
    pEP0_RAM_Addr = EP0_Databuf;
    pEP1_RAM_Addr = EP1_Databuf;
    USB_DeviceInit();
    PFIC_EnableIRQ(USB_IRQn);
    mDelaymS(100);
    /* TODO: gate on EP1-IN completion (Ready must be volatile) so a report can't be
     * overwritten while in flight. */
    while (1) {
        if (cmd_req) {
            uint8_t c = cmd_req;
            cmd_req = 0;
            RunCmd(c);
        }
        if (status_left) {
            memcpy(pEP1_IN_DataBuf, status, sizeof(status));
            DevEP1_IN_Deal(sizeof(status));
            if (--status_left == 0 && reset_after_status)
                PFIC_SystemReset();
        } else if (!led_mode) {
            ScanStep();
        } else if (led_pattern == 2 && ++led_tick % 25 == 0) {
            led_show(2, 0);
        }
        mDelaymS(2);
    }
}

/*********************************************************************
 * @fn      DevEP1_OUT_Deal
 *
 * @return  none
 */
void DevEP1_OUT_Deal(uint8_t l)
{
    /* hidraw may or may not strip the leading report-ID byte */
    const uint8_t *b = pEP1_OUT_DataBuf;
    for (uint8_t o = 0; o <= 1; o++)
        if (l >= o + 9 && b[o] >= 0x7B && b[o] <= 0x7F && b[o + 1] == 0x55
            && b[o + 2] == 0xAA && b[o + 3] == 0x55 && b[o + 4] == 0xAA) {
            memcpy(cmd_arg, b + o + 5, sizeof(cmd_arg));
            if (b[o] == 0x7C && l >= o + 9 + sizeof(led_bits))
                memcpy(led_bits, b + o + 9, sizeof(led_bits));
            cmd_req = b[o];
            return;
        }
}


/*********************************************************************
 * @fn      USB_IRQHandler
 *
 * @return  none
 */
__attribute__((interrupt("WCH-Interrupt-fast")))
__attribute__((section(".highcode")))
void USB_IRQHandler(void)
{
    USB_DevTransProcess();
}

/**==================================================================================================================
 **【文件名称】  main.c
 **【功能】      PC 状态监视器：通过 UART1 接收电脑发来的 CPU/内存/温度数据，实时显示在 1.8" LCD
 **【硬件】      魔女 STM32F407VET6 核心板 + 1.8" ST7735 8针 SPI 屏
 **【接线】      GND-GND  VCC-3.3V  SCL-PA5  SDA-PA7  RES-3.3V  DC-PA12  CS-PA8  BLK-PA15
 **【协议】      一行文本，\n 结尾，字段用空格分隔：
 **               C <cpu%> <mem%> <temp℃>
 **               例： C 12 34 56
 **【备注】      核心板无 W25Q128，故不使用外部 Flash 字库；
 **               汉字用 font.h 内的编译期字模（LCD_ShowChinese）。
====================================================================================================================*/
#include "stm32f4xx.h"
#include "bsp_led.h"
#include "bsp_UART.h"
#include "bsp_LCD_ST7735.h"
#include <stdlib.h>



/******************************************************************************
 * 毫秒延时（168MHz，依赖 -O3 + One ELF Section per Function）
 ******************************************************************************/
static volatile uint32_t ulTimesMS;
static void delay_ms(uint16_t ms)
{
    ulTimesMS = ms * 16500;
    while (ulTimesMS)
        ulTimesMS--;
}



/******************************************************************************
 * 全局状态：PC 发来的三个数值
 ******************************************************************************/
static volatile uint8_t  g_cpu  = 0;      // CPU 占用 %
static volatile uint8_t  g_mem  = 0;      // 内存占用 %
static volatile uint8_t  g_temp = 0;      // 温度 ℃
static volatile uint8_t  g_updated = 0;   // 收到新数据标志
static volatile uint8_t  g_live    = 0;   // 已收到过数据（用于显示 LIVE/WAIT）
static volatile uint32_t g_lastRxMs = 0;  // 最后接收时刻（用 LED 计数近似，仅作掉线提示）



/******************************************************************************
 * 函  数： parsePCStatus
 * 功  能： 解析一行 "C 12 34 56"，更新 g_cpu/g_mem/g_temp
 ******************************************************************************/
static void parsePCStatus(uint8_t *buf, uint16_t len)
{
    char  line[64];
    char *p;
    uint16_t i;

    if (len == 0 || len >= sizeof(line)) return;

    /* 拷贝并补结束符（串口数据不一定以 \0 结尾） */
    for (i = 0; i < len && i < sizeof(line) - 1; i++)
    {
        char c = (char)buf[i];
        if (c == '\r' || c == '\n') break;
        line[i] = c;
    }
    line[i] = '\0';

    p = line;
    while (*p == ' ') p++;                 /* 跳过前导空格 */

    if (*p != 'C' && *p != 'c') return;    /* 只认 C 开头的帧 */
    p++;
    while (*p == ' ') p++;

    {
        int v1 = atoi(p);                  /* CPU */
        while (*p && *p != ' ') p++;
        while (*p == ' ') p++;

        int v2 = atoi(p);                  /* MEM */
        while (*p && *p != ' ') p++;
        while (*p == ' ') p++;

        int v3 = atoi(p);                  /* TEMP */

        if (v1 < 0) v1 = 0; if (v1 > 100) v1 = 100;
        if (v2 < 0) v2 = 0; if (v2 > 100) v2 = 100;
        if (v3 < 0) v3 = 0; if (v3 > 125) v3 = 125;

        g_cpu  = (uint8_t)v1;
        g_mem  = (uint8_t)v2;
        g_temp = (uint8_t)v3;
        g_updated = 1;
        g_live = 1;
    }
}



/******************************************************************************
 * 函  数： drawBar
 * 功  能： 画一条进度条：背景框 + 填充
 ******************************************************************************/
static void drawBar(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint8_t pct, uint16_t color)
{
    uint16_t fill;

    LCD_Fill(x, y, x + w - 1, y + h - 1, DARKBLUE);        /* 底槽 */
    if (pct > 100) pct = 100;
    fill = (uint16_t)((uint32_t)w * pct / 100);
    if (fill > 0)
        LCD_Fill(x, y, x + fill - 1, y + h - 1, color);    /* 填充 */
}



/******************************************************************************
 * 函  数： drawScreen
 * 功  能： 刷新整屏
 ******************************************************************************/
static void drawScreen(void)
{
    static char s[24];

    LCD_Fill(0, 0, 128, 160, BLACK);                       /* 深色背景 */

    /* 标题 */
    LCD_ShowChinese( 6, 4, 3, 16, BLACK, WHITE);           /* 采 */
    LCD_ShowChinese(22, 4, 4, 16, BLACK, WHITE);           /* 集 */

    LCD_Line(0, 24, 127, 24, GRAY);

    /* ---- CPU ---- */
    sprintf(s, "CPU %3d%%", g_cpu);
    LCD_String(4, 30, s, 16, BLACK, GREEN);
    drawBar(4, 48, 120, 8, g_cpu, GREEN);

    /* ---- MEM ---- */
    sprintf(s, "MEM %3d%%", g_mem);
    LCD_String(4, 64, s, 16, BLACK, CYAN);
    drawBar(4, 82, 120, 8, g_mem, CYAN);

    /* ---- TEMP ---- */
    sprintf(s, "TEMP %3dC", g_temp);
    LCD_String(4, 98, s, 16, BLACK, YELLOW);

    /* 状态行：收到数据 / 等待中 */
    if (g_live)
        LCD_String(4, 126, "LIVE", 16, BLACK, WHITE);
    else
        LCD_String(4, 126, "WAIT", 16, BLACK, GRAY);
}



/******************************************************************************
 * 主函数
 ******************************************************************************/
int main(void)
{
    uint16_t rxNum;

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);

    UART1_Init(115200);                                    /* 板载 USB 转 TTL */
    Led_Init();
    LCD_Init();

    /* 开机画面 */
    LCD_Fill(0, 0, 128, 160, BLACK);
    LCD_String(10, 60, "PC MONITOR", 16, BLACK, WHITE);
    LCD_String(10, 80, "READY",      16, BLACK, GREEN);
    delay_ms(600);

    drawScreen();

    while (1)
    {
        rxNum = UART1_GetRxNum();                          /* >0 表示收到一帧 */

        if (rxNum > 0)
        {
            parsePCStatus(UART1_GetRxData(), rxNum);
            UART1_ClearRx();                               /* 必须清 0，才能接收下一帧 */

            if (g_updated)
            {
                drawScreen();                              /* 刷新显示 */
                g_updated = 0;
            }
        }

        LED_BLUE_TOGGLE;                                   /* 心跳：程序在跑 */
        delay_ms(120);
    }
}


// 文件末尾保留空行

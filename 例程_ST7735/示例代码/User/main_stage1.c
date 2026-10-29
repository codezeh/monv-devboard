/**==================================================================================================================
 **【文件名称】  main_stage1.c
 **【功能】      阶段 1 硬件自测：编码器 / 3 个按键 / 蜂鸣器 / 屏幕 全部验证
 **【用法】      确认 BSP/KNOB 加入工程后，把本文件加入工程并"排除"原来的 main.c
 **              （或直接把本文件内容覆盖 User/main.c 并做好备份）
 **【接线】      EC11:  VCC->3.3V  GND->GND  A->PC6  B->PC7  SW->PC0
 **              确认键: VCC->3.3V  GND->GND  OUT->PE2
 **              返回键: VCC->3.3V  GND->GND  OUT->PE3
 **              蜂鸣器(有源): VCC->3.3V  GND->GND  IO->PC9
 **              屏幕: 保持原来的 5 根线不动（SCL-PA5 SDA-PA7 CS-PA8 DC-PA12 BLK-PA15）
 **【自测通过标准】
 **              1) 转编码器：RAW 数值连续变化，DET 每格 ±1
 **              2) 按轴 / 按两个键：对应计数 +1，蜂鸣器"嘀"一声
 **              3) 串口助手（COM5 115200）同步打印同样内容
====================================================================================================================*/
#include "stm32f4xx.h"
#include "bsp_led.h"
#include "bsp_UART.h"
#include "bsp_LCD_ST7735.h"
#include "bsp_knob.h"
#include <stdio.h>
#include <string.h>


/* ------------------------------------------------------------------
 * 自测状态
 * ------------------------------------------------------------------ */
static uint32_t s_cntSw   = 0;
static uint32_t s_cntOk   = 0;
static uint32_t s_cntBack = 0;

static int8_t   s_dir     = 0;      /* +1 顺时针, -1 逆时针, 0 未知 */
static uint16_t s_dirHold = 0;      /* 方向保持计时(单位: 循环次数) */

static int32_t  s_rawCnt  = 0;      /* 编码器原始计数(4 倍频) */
static int32_t  s_detCnt  = 0;      /* 折算后的"格"数 */


/* ------------------------------------------------------------------
 * 只重画某一行的值（局部刷新，不闪）
 *   y     : 该行顶部坐标
 *   label : 左侧固定标签
 *   value : 右侧数值
 *   color : 数值颜色
 * ------------------------------------------------------------------ */
static void drawRow(uint16_t y, const char *label, const char *value, uint16_t color)
{
    LCD_Fill(0, y, 127, y + 15, BLACK);                 /* 只清这一行 */
    LCD_String(4,  y, (char *)label, 16, BLACK, GRAY);
    LCD_String(64, y, (char *)value, 16, BLACK, color);
}


/* ------------------------------------------------------------------
 * 静态部分：标题 + 分隔线，只画一次
 * ------------------------------------------------------------------ */
static void drawStatic(void)
{
    LCD_Fill(0, 0, 128, 160, BLACK);

    LCD_String(4, 4, "KNOB TEST", 16, BLACK, WHITE);
    LCD_Line(0, 22, 127, 22, DARKBLUE);

    LCD_Line(0, 76, 127, 76, DARKBLUE);

    LCD_String(4, 142, "PC6/PC7 TIM8", 16, BLACK, GRAYBLUE);
}


/* ------------------------------------------------------------------
 * 主函数
 * ------------------------------------------------------------------ */
int main(void)
{
    int16_t  delta;
    char     buf[24];
    uint16_t loop = 0;

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);

    UART1_Init(115200);          /* 板载 USB 转 TTL，接电脑 */
    Delay_Init();
    Led_Init();
    LCD_Init();
    Knob_Init();

    /* 开机画面 */
    LCD_Fill(0, 0, 128, 160, BLACK);
    LCD_String(10, 56, "KNOB",  16, BLACK, WHITE);
    LCD_String(10, 76, "SELFTEST", 16, BLACK, CYAN);
    BZ_Beep(80);
    Delay_ms(500);

    drawStatic();

    UART1_SendString("\r\n=== STAGE1 SELFTEST ===\r\n");
    UART1_SendString("Turn encoder / press SW / PE2 / PE3, watch LCD + serial\r\n");

    while (1)
    {
        /* ===== 编码器 ===== */
        delta = Knob_GetDelta();
        if (delta != 0)
        {
            s_rawCnt = Knob_GetTotal();
            s_detCnt += delta;
            s_dir     = (delta > 0) ? 1 : -1;
            s_dirHold = 60;                     /* 保持约 1.2 秒 */

            UART1_SendString("ENC raw=%ld det=%ld dir=%s\r\n",
                             (long)s_rawCnt, (long)s_detCnt,
                             (delta > 0) ? "CW" : "CCW");
        }

        /* ===== 按键（必须先 Scan 再取事件） ===== */
        Key_Scan10ms();

        if (Key_GetPress(KEY_ID_SW))
        {
            s_cntSw++;
            BZ_Beep(30);
            UART1_SendString("KEY SW   cnt=%lu\r\n", (unsigned long)s_cntSw);
        }

        if (Key_GetPress(KEY_ID_OK))
        {
            s_cntOk++;
            BZ_Beep(30);
            UART1_SendString("KEY OK   cnt=%lu\r\n", (unsigned long)s_cntOk);
        }

        if (Key_GetPress(KEY_ID_BACK))
        {
            s_cntBack++;
            BZ_Beep(30);
            UART1_SendString("KEY BACK cnt=%lu\r\n", (unsigned long)s_cntBack);
        }

        /* ===== 刷新显示（每 20ms 一轮） ===== */
        if (++loop >= 2)
        {
            loop = 0;

            /* 原始计数 */
            sprintf(buf, "%ld", (long)s_rawCnt);
            drawRow(26, "RAW", buf, WHITE);

            /* 折算格数 */
            sprintf(buf, "%ld", (long)s_detCnt);
            drawRow(44, "DET", buf, YELLOW);

            /* 方向 */
            if (s_dirHold > 0)
            {
                s_dirHold--;
                sprintf(buf, "%s", (s_dir > 0) ? "CW >>" : "<< CCW");
                drawRow(60, "DIR", buf, GREEN);
            }
            else
            {
                sprintf(buf, "--");
                drawRow(60, "DIR", buf, GRAY);
            }

            /* 三个按键计数 */
            sprintf(buf, "%lu", (unsigned long)s_cntSw);
            drawRow(82, "SW", buf, CYAN);

            sprintf(buf, "%lu", (unsigned long)s_cntOk);
            drawRow(100, "OK", buf, CYAN);

            sprintf(buf, "%lu", (unsigned long)s_cntBack);
            drawRow(118, "BACK", buf, CYAN);
        }

        LED_BLUE_TOGGLE;        /* 心跳 */
        Delay_ms(10);           /* Key_Scan10ms 的节拍 */
    }
}

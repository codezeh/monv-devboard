/**==================================================================================================================
 **【文件名称】  main_skin_demo.c
 **【功能】      纯半身像显示：画面只放人物，没有血条、没有标题栏
 **【设计】      人物占满 128x160，背景是一块纯色（深蓝灰 0x3A2C），
 **              和参考图一致。像素块由 PC 端 NEAREST 放大产生。
 **【操作】
 **   旋钮左右  : 切换状态（IDLE/WALK/HURT/JUMP/ATTACK/SLEEP）
 **   OK 键     : 受伤
 **   BACK 键   : 回到待机
 **   串口命令  : SI SW SH SJ SA SZ
 **   串口图像  : tools/mcstream.py -p COMx  （推流高分辨率精灵）
 **【Flash 优化】
 **   本文件不使用 LCD_String / LCD_ShowChinese，
 **   链接器会把字模表丢掉（约省 10KB+ Flash）。
====================================================================================================================*/
#include "stm32f4xx.h"
#include "bsp_led.h"
#include "bsp_UART.h"
#include "bsp_LCD_ST7735.h"
#include "bsp_knob.h"
#include "bsp_skin.h"

#define SCREEN_W    128
#define SCREEN_H    160
#define BG_COLOR    0x3A2C      /* 深蓝灰背景，衬得出黑发白衣 */

/* 自动轮播：无操作时自动切状态，方便一次看全效果 */
#define AUTO_DEMO   1
#define AUTO_MS     2500

static uint16_t    s_autoMs = 0;
static uint8_t     s_manual = 0;
static uint16_t    s_bx     = 0;      /* 像左上角（居中） */
static uint16_t    s_by     = 0;


/* ==================================================================
 * 根据当前精灵尺寸算居中位置
 * ================================================================== */
static void layout_update(void)
{
    uint16_t w = 0, h = 0;

    Skin_GetSize(&w, &h);

    s_bx = (uint16_t)(((int)SCREEN_W - (int)w) / 2);
    s_by = (uint16_t)(((int)SCREEN_H - (int)h) / 2);
    if (s_bx > SCREEN_W) s_bx = 0;
    if (s_by > SCREEN_H) s_by = 0;
}


/* ==================================================================
 * 重绘背景（清屏为纯色）
 * ================================================================== */
static void draw_bg(void)
{
    LCD_Fill(0, 0, SCREEN_W - 1, SCREEN_H - 1, BG_COLOR);
}


/* ==================================================================
 * UART：状态命令 + PC 推流图像
 * ================================================================== */
static void handle_uart(void)
{
    uint16_t n;
    uint8_t *p;
    uint8_t  r;

    n = UART1_GetRxNum();
    if (n == 0) return;

    p = UART1_GetRxData();

    /* ---- PC 推流精灵（块以 'C' 开头） ---- */
    if (p[0] == 'C')
    {
        r = Skin_StreamChunk(p, n);
        if (r == 2)
        {
            uint16_t w, h;
            Skin_GetSize(&w, &h);
            layout_update();
            draw_bg();
            UART1_SendString("MSK OK %u %u\r\n", w, h);
        }
        UART1_ClearRx();
        return;
    }

    /* ---- 状态命令 ---- */
    if (n >= 2 && (p[0] == 'S' || p[0] == 's'))
    {
        switch ((char)p[1])
        {
        case 'I': case 'i': Skin_SetState(SKIN_IDLE);   break;
        case 'W': case 'w': Skin_SetState(SKIN_WALK);   break;
        case 'H': case 'h': Skin_SetState(SKIN_HURT);   break;
        case 'J': case 'j': Skin_SetState(SKIN_JUMP);   break;
        case 'A': case 'a': Skin_SetState(SKIN_ATTACK); break;
        case 'Z': case 'z': Skin_SetState(SKIN_SLEEP);  break;
        default: break;
        }
        s_manual = 1;
        s_autoMs = 0;
        UART1_SendString("-> %s\r\n", Skin_GetStateName(Skin_GetState()));
    }

    UART1_ClearRx();
}


/* ==================================================================
 * 主函数
 * ================================================================== */
int main(void)
{
    int16_t delta;

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);

    UART1_Init(921600);              /* 推流用高速率；不稳就改 460800 */
    Delay_Init();
    Led_Init();
    LCD_Init();
    Knob_Init();

    layout_update();
    draw_bg();

    /* 开机提示音（不放文字，画面就是一张图） */
    BZ_Beep(60);

    UART1_SendString("\r\n=== SKIN PORTRAIT ===\r\n");
    UART1_SendString("state: SI SW SH SJ SA SZ\r\n");
    UART1_SendString("image: mcstream.py -p COMx\r\n");

    while (1)
    {
        /* ---------- 旋钮：切状态 ---------- */
        delta = Knob_GetDelta();
        if (delta != 0)
        {
            int16_t st = (int16_t)Skin_GetState() + ((delta > 0) ? 1 : -1);
            if (st < 0)              st = SKIN_ST_COUNT - 1;
            if (st >= SKIN_ST_COUNT) st = 0;
            Skin_SetState((SkinState_t)st);
            s_manual = 1;
            s_autoMs = 0;
        }

        Key_Scan10ms();

        if (Key_GetPress(KEY_ID_OK))
        {
            Skin_SetState(SKIN_HURT);
            BZ_Beep(20);
            s_manual = 1;
            s_autoMs = 0;
        }

        if (Key_GetPress(KEY_ID_BACK))
        {
            Skin_SetState(SKIN_IDLE);
            BZ_Beep(20);
            s_manual = 1;
            s_autoMs = 0;
        }

        /* 编码器轴按下：静音切换（这里复用为"回退到内置精灵"的调试入口） */
        if (Key_GetPress(KEY_ID_SW))
        {
            Skin_SetState(SKIN_ATTACK);
            s_manual = 1;
            s_autoMs = 0;
        }

        handle_uart();

        /* ---------- 自动轮播 ---------- */
#if AUTO_DEMO
        if (!s_manual)
        {
            s_autoMs += 33;
            if (s_autoMs >= AUTO_MS)
            {
                int16_t st = (int16_t)Skin_GetState() + 1;
                if (st >= SKIN_ST_COUNT) st = 0;
                Skin_SetState((SkinState_t)st);
                s_autoMs = 0;
            }
        }
#endif

        /* ---------- 动画与绘制 ---------- */
        Skin_Tick(33);
        Skin_Render(s_bx, s_by, BG_COLOR);

        LED_BLUE_TOGGLE;
        Delay_ms(33);                /* ≈30fps */
    }
}

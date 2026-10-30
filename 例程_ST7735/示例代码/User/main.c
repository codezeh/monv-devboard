/**==================================================================================================================
 **【文件名称】  main.c
 **【功能】      Minecraft 半身像显示：画面全屏放人物，没有状态栏、没有标题栏
 **【设计要点】  人物占满 128x160，背景是一整块纯色（深蓝灰 0x3A2C），
 **              和参考图一致。像素块由 PC 端 NEAREST 放大产生。
 **【操作】
 **   旋钮左右  : 切换状态（IDLE/WALK/HURT/JUMP/ATTACK/SLEEP）
 **   OK 键     : 受伤
 **   BACK 键   : 回到待机
 **   串口状态  : SI待机 SW走 SH伤 SJ跳 SA攻 SZ睡 SR跑 SK潜
 **   串口扭头  : H+档位(0..24, 12=正前方, 5度一档)；SF=交还本地动画
 **   串口图像  : tools/mcstream.py -p COMx （推流高清精灵）
 **【Flash 优化】
 **   本文件不用 LCD_String / LCD_ShowChinese，链接器会把字模表丢掉（约省 10KB+）。
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
static uint16_t    s_bx     = 0;      /* 图左上角（居中算出来） */
static uint16_t    s_by     = 0;


/* ==================================================================
 * 按当前精灵尺寸算居中位置
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
 * UART：状态命令 + 扭头角度 + 推流图像，统一交给 Skin_FeedStream 解析
 * ================================================================== */

static void handle_uart(void)
{
    uint8_t  buf[256];
    uint16_t n;

    /* 从环形缓冲取字节，不受主循环轮询时机影响：
     * 刷屏要十几毫秒，期间到达的数据先进环形缓冲，不会被覆盖。 */
    while ((n = UART1_RingRead(buf, sizeof(buf))) > 0)
    {
        Skin_FeedStream(buf, n);
    }
}


/* ==================================================================
 * 主函数
 * ================================================================== */
int main(void)
{
    int16_t delta;
    uint8_t i;

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);

    UART1_Init(921600);              /* 推流用高速率；不稳就降到 460800 */
    Delay_Init();
    Led_Init();
    LCD_Init();
    Knob_Init();

    layout_update();
    draw_bg();

    /* 开机提示音（不放文字，画面就是一张图） */
    BZ_Beep(60);

    UART1_SendString("\r\n=== SKIN PORTRAIT ===\r\n");
    UART1_SendString("state: SI SW SH SJ SA SZ SR SK | head: H+idx | SF\r\n");
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

        /* 编码器轴按下：切到 ATTACK（借用成调试入口） */
        if (Key_GetPress(KEY_ID_SW))
        {
            Skin_SetState(SKIN_ATTACK);
            s_manual = 1;
            s_autoMs = 0;
        }

        handle_uart();

        /* 收到状态命令：停止自动轮播并回一行日志 */
        if (Skin_ConsumeCmdFlag())
        {
            s_manual = 1;
            s_autoMs = 0;
            UART1_SendString("-> %s\r\n", Skin_GetStateName(Skin_GetState()));
        }

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
        if (Skin_IsStreamed())
        {
            /* 推流模式：只在收到新帧时重绘，其余时间全速收串口 */
            Skin_IdleTick(2);
            if (Skin_ConsumeFrameFlag()) Skin_Render(s_bx, s_by, BG_COLOR);
            else                         Delay_ms(2);
        }
        else
        {
            Skin_Tick(33);
            Skin_Render(s_bx, s_by, BG_COLOR);
            LED_BLUE_TOGGLE;
            /* 33ms 的等待拆成 16 次 2ms：保证推流期间串口每 2ms 被取走一次。
             * 否则一帧 5.9KB 会在 33ms 内堆满驱动缓冲并被覆盖（丢数据）。 */
            for (i = 0; i < 16; i++)
            {
                handle_uart();
                Delay_ms(2);
            }
        }
    }
}

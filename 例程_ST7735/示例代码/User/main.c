/**==================================================================================================================
 **銆愭枃浠跺悕绉般??  main_skin_demo.c
 **銆愬姛鑳姐??      绾?鍗婅韩鍍忔樉绀猴細鐢婚潰鍙?鏀句汉鐗╋紝娌℃湁琛?鏉°?佹病鏈夋爣棰樻爮
 **銆愯?捐?°??      浜虹墿鍗犳弧 128x160锛岃儗鏅?鏄?涓?鍧楃函鑹诧紙娣辫摑鐏? 0x3A2C锛夛紝
 **              鍜屽弬鑰冨浘涓?鑷淬?傚儚绱犲潡鐢? PC 绔? NEAREST 鏀惧ぇ浜х敓銆?
 **銆愭搷浣溿??
 **   鏃嬮挳宸﹀彸  : 鍒囨崲鐘舵?侊紙IDLE/WALK/HURT/JUMP/ATTACK/SLEEP锛?
 **   OK 閿?     : 鍙椾激
 **   BACK 閿?   : 鍥炲埌寰呮満
 **   涓插彛鍛戒护  : SI SW SH SJ SA SZ
 **   涓插彛鍥惧儚  : tools/mcstream.py -p COMx  锛堟帹娴侀珮鍒嗚鲸鐜囩簿鐏碉級
 **銆怓lash 浼樺寲銆?
 **   鏈?鏂囦欢涓嶄娇鐢? LCD_String / LCD_ShowChinese锛?
 **   閾炬帴鍣ㄤ細鎶婂瓧妯¤〃涓㈡帀锛堢害鐪? 10KB+ Flash锛夈??
====================================================================================================================*/
#include "stm32f4xx.h"
#include "bsp_led.h"
#include "bsp_UART.h"
#include "bsp_LCD_ST7735.h"
#include "bsp_knob.h"
#include "bsp_skin.h"

#define SCREEN_W    128
#define SCREEN_H    160
#define BG_COLOR    0x3A2C      /* 娣辫摑鐏拌儗鏅?锛岃‖寰楀嚭榛戝彂鐧借。 */

/* 鑷?鍔ㄨ疆鎾?锛氭棤鎿嶄綔鏃惰嚜鍔ㄥ垏鐘舵?侊紝鏂逛究涓?娆＄湅鍏ㄦ晥鏋? */
#define AUTO_DEMO   1
#define AUTO_MS     2500

static uint16_t    s_autoMs = 0;
static uint8_t     s_manual = 0;
static uint16_t    s_bx     = 0;      /* 鍍忓乏涓婅?掞紙灞呬腑锛? */
static uint16_t    s_by     = 0;


/* ==================================================================
 * 鏍规嵁褰撳墠绮剧伒灏哄?哥畻灞呬腑浣嶇疆
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
 * 閲嶇粯鑳屾櫙锛堟竻灞忎负绾?鑹诧級
 * ================================================================== */
static void draw_bg(void)
{
    LCD_Fill(0, 0, SCREEN_W - 1, SCREEN_H - 1, BG_COLOR);
}


/* ==================================================================
 * UART锛氱姸鎬佸懡浠? + PC 鎺ㄦ祦鍥惧儚
 * ================================================================== */

static void handle_uart(void)
{
    uint8_t  buf[256];
    uint16_t n;

    /* 从环形缓冲里取字节，不受本次轮询时机影响：
     * 刷屏要十几毫秒，期间到达的数据先进环形缓冲，不会被覆盖。 */
    while ((n = UART1_RingRead(buf, sizeof(buf))) > 0)
    {
        Skin_FeedStream(buf, n);
    }
}


/* ==================================================================
 * 涓诲嚱鏁?
 * ================================================================== */
int main(void)
{
    int16_t delta;
    uint8_t i;

    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);

    UART1_Init(921600);              /* 鎺ㄦ祦鐢ㄩ珮閫熺巼锛涗笉绋冲氨鏀? 460800 */
    Delay_Init();
    Led_Init();
    LCD_Init();
    Knob_Init();

    layout_update();
    draw_bg();

    /* 寮?鏈烘彁绀洪煶锛堜笉鏀炬枃瀛楋紝鐢婚潰灏辨槸涓?寮犲浘锛? */
    BZ_Beep(60);

    UART1_SendString("\r\n=== SKIN PORTRAIT ===\r\n");
    UART1_SendString("state: SI SW SH SJ SA SZ\r\n");
    UART1_SendString("image: mcstream.py -p COMx\r\n");

    while (1)
    {
        /* ---------- 鏃嬮挳锛氬垏鐘舵?? ---------- */
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

        /* 缂栫爜鍣ㄨ酱鎸変笅锛氶潤闊冲垏鎹?锛堣繖閲屽?嶇敤涓?"鍥為??鍒板唴缃?绮剧伒"鐨勮皟璇曞叆鍙ｏ級 */
        if (Key_GetPress(KEY_ID_SW))
        {
            Skin_SetState(SKIN_ATTACK);
            s_manual = 1;
            s_autoMs = 0;
        }

        handle_uart();

        /* 接到状态命令：停止自动轮播并回一行日志 */
        if (Skin_ConsumeCmdFlag())
        {
            s_manual = 1;
            s_autoMs = 0;
            UART1_SendString("-> %s\r\n", Skin_GetStateName(Skin_GetState()));
        }

        /* ---------- 鑷?鍔ㄨ疆鎾? ---------- */
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

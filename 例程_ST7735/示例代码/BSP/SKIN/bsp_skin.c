/**==================================================================================================================
 ** FILE   : bsp_skin.c
 ** BRIEF  : Bust renderer -- FULL-FRAME animation (plan C)
 **
 ** All animation frames are pre-rendered on the PC (real 3D arm rotation)
 ** and stored RLE-compressed in Flash. The firmware only:
 **   1. picks a frame by (state, phase)
 **   2. RLE-decodes it into the output buffer
 **   3. pushes to LCD
 **
 ** No part maps, no arm compositing, no alignment problems.
 ** RAM: one output buffer only (~34KB)
 **
 ** State -> frame table (see skin_anim.c):
 **   0 IDLE   1 WALK   2 RUN   3 ATTACK   4 JUMP   5 SNEAK   6 SLEEP
 **   HURT reuses IDLE frames + red tint at runtime
====================================================================================================================*/
#include "bsp_skin.h"
#include "bsp_LCD_ST7735.h"
#include "bsp_UART.h"
#include "skin_anim.h"
#include "skin_head.h"

/* ---------------- output buffer ---------------- */
static uint16_t s_dstBuf[SKIN_MAX_W * SKIN_MAX_H];

static uint16_t s_out_w = ANIM_W;
static uint16_t s_out_h = ANIM_H;

/* ---------------- built-in fallback sprite ---------------- */
static uint8_t s_streamed = 0;

/* ---------------- state machine ---------------- */
static SkinState_t s_state = SKIN_IDLE;
static uint16_t    s_phase = 0;

/* streaming fallback (kept for compatibility with mcstream) */
static uint16_t s_rxW = 0, s_rxH = 0;
static uint32_t s_rxPixels = 0, s_rxTotal = 0;
static uint8_t  s_rxRunCnt = 0;
static uint16_t s_rxColor = 0;
static uint8_t  s_rxStage = 0;
static uint16_t s_rxCurLo = 0;
static uint8_t  s_rxActive = 0;
static uint16_t s_ovBuf[SKIN_MAX_W * SKIN_MAX_H];  /* streamed override */

/* ---------------- 字节流解析器状态 ----------------
 * USB-CDC 会把多次小写入合并成一帧送达，驱动又只有一个接收槽（无队列），
 * 按"UART 空闲间隙"分包必然丢块 -> 推流帧永远凑不齐像素 -> 扭头不动。
 * 改为"字节流 + 长度前缀"：随便被切碎还是合并都能正确解析。
 */
#define P_IDLE    0
#define P_CTYPE   1
#define P_CLEN    2
#define P_CPAY    3
#define P_DTYPE   4
#define P_DLENLO  5
#define P_DLENHI  6
#define P_DPAY    7
#define P_SCMD    8
#define P_HCMD    9

static uint8_t  s_pState    = P_IDLE;
static uint8_t  s_pType     = 0;
static uint16_t s_pRemain   = 0;
static uint8_t  s_ctl[4];
static uint8_t  s_ctlPos    = 0;
static uint8_t  s_frameFlag = 0;    /* 1 = 有新提交的推流帧待绘制 */
static uint8_t  s_cmdFlag   = 0;    /* 1 = 收到状态命令 */
static uint32_t s_idleMs    = 0;    /* 推流静默计时 */

/* ---------------- 头部层（扭头角度） ----------------
 * 角度以"档位下标"表示，0..HEAD_COUNT-1，正前方是 HEAD_MID。
 * 由 'H' 命令直接设置（1 字节），不参与推流，所以身体动画照常本地播放。
 */
static uint8_t s_headIdx = HEAD_MID;


/* ==================================================================
 * helpers
 * ================================================================== */
static uint16_t tint_color(uint16_t c, uint8_t mode)
{
    uint16_t r, g, b;
    if (mode == 0) return c;

    r = (uint16_t)((c >> 11) & 0x1F);
    g = (uint16_t)((c >> 5)  & 0x3F);
    b = (uint16_t)(c & 0x1F);

    if (mode == 1) { r >>= 1; g >>= 1; b >>= 1; }
    else { r = (uint16_t)((r * 2 + 31 * 3) / 5);
           g = (uint16_t)((g * 2) / 5);
           b = (uint16_t)((b * 2) / 5); }
    return (uint16_t)((r << 11) | (g << 5) | b);
}


/* ==================================================================
 * state -> (anim row, tint)
 * ================================================================== */
static uint8_t state_to_row(SkinState_t st)
{
    switch (st)
    {
    case SKIN_IDLE:   return 0;
    case SKIN_WALK:   return 1;
    case SKIN_RUN:    return 2;
    case SKIN_ATTACK: return 3;
    case SKIN_JUMP:   return 4;
    case SKIN_SNEAK:  return 5;
    case SKIN_SLEEP:  return 6;
    case SKIN_HURT:   return 0;      /* reuse IDLE frames */
    default:          return 0;
    }
}

static uint8_t state_to_tint(SkinState_t st)
{
    switch (st)
    {
    case SKIN_HURT:  return 2;       /* red */
    case SKIN_SLEEP: return 1;       /* dark */
    default:         return 0;
    }
}


/* ==================================================================
 * state API
 * ================================================================== */
void Skin_SetState(SkinState_t st)
{
    if (st >= SKIN_ST_COUNT) return;
    /* 状态切换只记录状态，不打断推流帧的显示。
     * 退出推流由 'SF' 命令或 Skin_IdleTick 的 3 秒超时负责，
     * 否则走路时 IDLE/WALK 频繁切换会把扭头帧立刻顶掉。 */
    if (st == s_state) return;
    s_state = st;
    s_phase = 0;
}

SkinState_t Skin_GetState(void)   { return s_state; }
uint8_t     Skin_IsStreamed(void) { return s_streamed; }

void Skin_GetSize(uint16_t *w, uint16_t *h)
{
    if (w) *w = s_out_w;
    if (h) *h = s_out_h;
}

const char *Skin_GetStateName(SkinState_t st)
{
    switch (st)
    {
    case SKIN_IDLE:   return "IDLE";
    case SKIN_WALK:   return "WALK";
    case SKIN_HURT:   return "HURT";
    case SKIN_JUMP:   return "JUMP";
    case SKIN_ATTACK: return "ATTACK";
    case SKIN_SLEEP:  return "SLEEP";
    case SKIN_RUN:    return "RUN";
    case SKIN_SNEAK:  return "SNEAK";
    default:          return "?";
    }
}

void Skin_Tick(uint16_t dt)
{
    uint16_t per;
    switch (s_state)
    {
    case SKIN_IDLE:   per = 2000; break;
    case SKIN_WALK:   per = 560;  break;   /* 8 frames */
    case SKIN_RUN:    per = 320;  break;   /* faster */
    case SKIN_HURT:   per = 400;  break;
    case SKIN_JUMP:   per = 720;  break;
    case SKIN_ATTACK: per = 480;  break;
    case SKIN_SLEEP:  per = 3200; break;
    case SKIN_SNEAK:  per = 2400; break;
    default:          per = 1000; break;
    }
    s_phase += dt;
    while (s_phase >= per) s_phase -= per;
}


/* ==================================================================
 * fall back to built-in sprite
 * ================================================================== */
void Skin_UseFlash(void)
{
    s_streamed = 0;
    s_out_w = ANIM_W;
    s_out_h = ANIM_H;
    s_rxActive = 0;
    s_idleMs   = 0;
}


/* ==================================================================
 * 串口字节流解析（自定界，与 UART 空闲间隙无关）
 * ------------------------------------------------------------------
 * 空闲态认三种起始字节：
 *   'C' type len(1B) 负载     旧格式，mcstream.py 一次性推皮肤在用
 *   'D' type len(2B) 负载     新格式，实时扭头帧（负载可达 64KB）
 *   'S' 命令字                状态命令 SI/SW/SH/SJ/SA/SZ/SR/SK/SF
 * type: 0 = BEGIN(负载 w,h)  1 = DATA(RLE 字节)  2 = END(提交整帧)
 * RLE 每组 3 字节：[count][color_lo][color_hi]，count=1..255
 * ================================================================== */
static void stream_begin(uint8_t w, uint8_t h)
{
    if (w == 0 || h == 0 || w > SKIN_MAX_W || h > SKIN_MAX_H)
    {
        s_rxActive = 0;
        return;
    }
    s_rxW     = w;
    s_rxH     = h;
    s_rxTotal = (uint32_t)w * h;
    s_rxPixels = 0;
    s_rxRunCnt = 0;
    s_rxStage  = 0;
    s_rxActive = 1;
}

static void stream_rle_byte(uint8_t v)
{
    switch (s_rxStage)
    {
    case 0: s_rxRunCnt = v; s_rxStage = 1; break;
    case 1: s_rxCurLo  = v; s_rxStage = 2; break;
    default:
        s_rxColor = (uint16_t)(s_rxCurLo | ((uint16_t)v << 8));
        s_rxStage = 0;
        while (s_rxRunCnt > 0 && s_rxPixels < s_rxTotal)
        {
            s_ovBuf[s_rxPixels++] = s_rxColor;
            s_rxRunCnt--;
        }
        break;
    }
}

static void stream_payload_byte(uint8_t type, uint8_t v)
{
    if (type == 1)
    {
        if (s_rxActive) stream_rle_byte(v);
    }
    else if (type == 0)                 /* BEGIN 负载：w, h */
    {
        if (s_ctlPos < (uint8_t)sizeof(s_ctl)) s_ctl[s_ctlPos++] = v;
    }
}

static void stream_payload_done(uint8_t type)
{
    if (type == 0)
    {
        if (s_ctlPos >= 2) stream_begin(s_ctl[0], s_ctl[1]);
        else               s_rxActive = 0;
    }
    else if (type == 2)                 /* END：像素齐了才提交 */
    {
        if (s_rxActive)
        {
            s_rxActive = 0;
            if (s_rxTotal > 0 && s_rxPixels >= s_rxTotal)
            {
                s_streamed  = 1;
                s_out_w     = s_rxW;
                s_out_h     = s_rxH;
                s_frameFlag = 1;
                s_idleMs    = 0;
                /* 回 1 字节 ACK：让 PC 端（和调测脚本）能确认整帧真的被接受，
                 * 而不是靠肉眼猜屏幕有没有变。 */
                {
                    uint8_t ack = 'K';
                    UART1_SendData(&ack, 1);
                }
            }
            else
            {
                /* 诊断：帧不完整时报已收/总量，用于判定是丢数据还是协议错 */
                UART1_SendString("!%u/%u\r\n",
                                 (unsigned int)s_rxPixels, (unsigned int)s_rxTotal);
            }
        }
    }
    s_ctlPos = 0;
}

static void stream_state_cmd(uint8_t c)
{
    switch (c)
    {
    case 'I': case 'i': Skin_SetState(SKIN_IDLE);   break;
    case 'W': case 'w': Skin_SetState(SKIN_WALK);   break;
    case 'H': case 'h': Skin_SetState(SKIN_HURT);   break;
    case 'J': case 'j': Skin_SetState(SKIN_JUMP);   break;
    case 'A': case 'a': Skin_SetState(SKIN_ATTACK); break;
    case 'Z': case 'z': Skin_SetState(SKIN_SLEEP);  break;
    case 'R': case 'r': Skin_SetState(SKIN_RUN);    break;
    case 'K': case 'k': Skin_SetState(SKIN_SNEAK);  break;
    case 'F': case 'f': Skin_UseFlash();            break;  /* 交还本地 Flash 动画 */
    default: return;
    }
    s_cmdFlag = 1;
}

void Skin_FeedStream(const uint8_t *buf, uint16_t len)
{
    uint16_t i;
    uint8_t  b;

    if (buf == 0) return;

    for (i = 0; i < len; i++)
    {
        b = buf[i];
        switch (s_pState)
        {
        case P_IDLE:
            if      (b == 'C')                     s_pState = P_CTYPE;
            else if (b == 'D')                   { s_pState = P_DTYPE; s_ctlPos = 0; }
            else if (b == 'S' || b == 's')         s_pState = P_SCMD;
            else if (b == 'H' || b == 'h')         s_pState = P_HCMD;
            /* 其它字节丢掉，等待重新同步 */
            break;

        case P_CTYPE:
            s_pType = b; s_ctlPos = 0; s_pState = P_CLEN;
            break;

        case P_CLEN:
            s_pRemain = b;
            s_pState  = P_CPAY;
            if (s_pRemain == 0) { stream_payload_done(s_pType); s_pState = P_IDLE; }
            break;

        case P_CPAY:
            stream_payload_byte(s_pType, b);
            if (--s_pRemain == 0) { stream_payload_done(s_pType); s_pState = P_IDLE; }
            break;

        case P_DTYPE:
            s_pType = b; s_ctlPos = 0; s_pState = P_DLENLO;
            break;

        case P_DLENLO:
            s_pRemain = b; s_pState = P_DLENHI;
            break;

        case P_DLENHI:
            s_pRemain = (uint16_t)(s_pRemain | ((uint16_t)b << 8));
            s_pState  = P_DPAY;
            if (s_pRemain == 0) { stream_payload_done(s_pType); s_pState = P_IDLE; }
            break;

        case P_DPAY:
            stream_payload_byte(s_pType, b);
            if (--s_pRemain == 0) { stream_payload_done(s_pType); s_pState = P_IDLE; }
            break;

        case P_SCMD:
            s_pState = P_IDLE;
            stream_state_cmd(b);
            break;

        case P_HCMD:                    /* 'H' + 1 字节角度档 */
            s_pState = P_IDLE;
            if (b < HEAD_COUNT) s_headIdx = b;
            {
                uint8_t ack = 'h';
                UART1_SendData(&ack, 1);   /* 回 ACK，便于 PC 端自检 */
            }
            break;

        default:
            s_pState = P_IDLE;
            break;
        }
    }
}

uint8_t Skin_ConsumeFrameFlag(void)
{
    uint8_t v = s_frameFlag;
    s_frameFlag = 0;
    return v;
}

uint8_t Skin_ConsumeCmdFlag(void)
{
    uint8_t v = s_cmdFlag;
    s_cmdFlag = 0;
    return v;
}

void Skin_IdleTick(uint16_t ms)
{
    if (!s_streamed) { s_idleMs = 0; return; }
    s_idleMs += ms;
    if (s_idleMs >= 3000)               /* 3 秒无新帧：交还本地动画 */
    {
        Skin_UseFlash();
        s_pState   = P_IDLE;            /* 清掉可能残留在解析中途的状态 */
        s_rxActive = 0;
        s_idleMs   = 0;
    }
}


/* ==================================================================
 * 头部层叠加：把头 RLE 解到 s_dstBuf 上（透明像素跳过）
 * ------------------------------------------------------------------
 * 这就是"头和身体分开"的关键：身体帧来自 Flash（30fps 本地播放），
 * 头按当前扭头角度单独贴上去，两者互不干扰。
 * ================================================================== */
static void blit_head(const AnimFrame_t *fr, uint16_t w, uint16_t h,
                      int16_t dx, int16_t dy, uint8_t tint)
{
    uint32_t i = 0, n = 0, tot;
    uint16_t sx = 0, sy = 0;
    uint8_t  run;
    uint16_t col;

    if (fr == 0 || fr->data == 0) return;
    tot = (uint32_t)w * h;

    while (i + 2 < fr->len && n < tot)
    {
        run = fr->data[i++];
        col = (uint16_t)(fr->data[i] | ((uint16_t)fr->data[i + 1] << 8));
        i += 2;
        if (run == 0) break;

        if (col == SKIN_TRANSPARENT)
        {
            /* 整段透明：只推进坐标，不逐像素写 */
            uint16_t adv = run;
            uint32_t left = tot - n;
            if ((uint32_t)adv > left) adv = (uint16_t)left;
            n  += adv;
            sy  = (uint16_t)(sy + (sx + adv) / w);
            sx  = (uint16_t)((sx + adv) % w);
            continue;
        }

        col = tint_color(col, tint);    /* HURT 时头也要跟着变红 */
        while (run-- > 0 && n < tot)
        {
            int32_t X = (int32_t)sx + dx;
            int32_t Y = (int32_t)sy + dy;
            if (X >= 0 && Y >= 0 && X < (int32_t)w && Y < (int32_t)h)
            {
                s_dstBuf[(uint32_t)Y * w + (uint32_t)X] = col;
            }
            n++;
            if (++sx >= w) { sx = 0; sy++; }
        }
    }
}

void Skin_SetHeadIdx(uint8_t idx)
{
    if (idx < HEAD_COUNT) s_headIdx = idx;
}

uint8_t Skin_GetHeadIdx(void) { return s_headIdx; }


/* ==================================================================
 * RLE decode one frame into s_dstBuf
 * ================================================================== */
static void decode_frame(const AnimFrame_t *fr, uint16_t w, uint16_t h, uint8_t tint)
{
    uint32_t i = 0, out = 0, tot;
    uint16_t run;
    uint16_t col;

    if (fr == 0 || fr->data == 0) return;

    tot = (uint32_t)w * h;

    while (i + 2 < fr->len && out < tot)
    {
        run = fr->data[i++];
        col = (uint16_t)(fr->data[i] | ((uint16_t)fr->data[i + 1] << 8));
        i += 2;

        if (run == 0) break;

        col = tint_color(col, tint);
        while (run-- > 0 && out < tot)
        {
            s_dstBuf[out++] = col;
        }
    }
}


/* ==================================================================
 * render: pick frame by state+phase, decode, push
 * ================================================================== */
void Skin_Render(uint16_t x, uint16_t y, uint16_t bgColor)
{
    uint8_t row, tint;
    uint16_t per, idx, i;
    uint32_t n;

    /* streamed override image takes priority if present */
    if (s_streamed)
    {
        n = (uint32_t)s_out_w * s_out_h;
        if (n <= (uint32_t)SKIN_MAX_W * SKIN_MAX_H)
        {
            uint16_t *src = s_ovBuf;
            for (i = 0; i < n; i++) s_dstBuf[i] = src[i];
            LCD_Image(x, y, s_out_w, s_out_h, (const u8 *)s_dstBuf);
            return;
        }
    }

    row  = state_to_row(s_state);
    tint = state_to_tint(s_state);

    /* frames per state = ANIM_FRAMES; phase maps to frame index */
    switch (s_state)
    {
    case SKIN_IDLE:
    case SKIN_SLEEP:  per = 2000; break;
    case SKIN_WALK:   per = 560;  break;
    case SKIN_RUN:    per = 320;  break;
    case SKIN_HURT:   per = 400;  break;
    case SKIN_JUMP:   per = 720;  break;
    case SKIN_ATTACK: per = 480;  break;
    case SKIN_SNEAK:  per = 2400; break;
    default:          per = 1000; break;
    }
    if (per == 0) per = 1000;

    idx = (uint16_t)(((uint32_t)s_phase * ANIM_FRAMES) / per);
    if (idx >= ANIM_FRAMES) idx = ANIM_FRAMES - 1;

    decode_frame(&g_anim[row][idx], ANIM_W, ANIM_H, tint);

    /* 分层状态：把当前角度的头贴上去（身体动画不受影响） */
    if (g_anim_layered[row] && s_headIdx < HEAD_COUNT)
    {
        blit_head(&g_head[s_headIdx], ANIM_W, ANIM_H,
                  g_head_off[row][idx][0], g_head_off[row][idx][1], tint);
    }

    LCD_Image(x, y, ANIM_W, ANIM_H, (const u8 *)s_dstBuf);
}

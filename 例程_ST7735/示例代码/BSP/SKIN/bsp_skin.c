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
}


/* ==================================================================
 * streaming receive (optional override image; kept for compatibility)
 * ================================================================== */
uint8_t Skin_StreamChunk(const uint8_t *buf, uint16_t len)
{
    uint8_t type, plen;

    if (buf == 0 || len < 3) return 0;
    if (buf[0] != 'C') return 0;

    type = buf[1];
    plen = buf[2];
    if ((uint16_t)(3 + plen) > len) plen = (uint8_t)(len - 3);

    if (type == 0)
    {
        if (plen < 2) return 0;
        s_rxW = buf[3];
        s_rxH = buf[4];
        if (s_rxW == 0 || s_rxH == 0) return 0;
        if (s_rxW > SKIN_MAX_W || s_rxH > SKIN_MAX_H) return 0;
        s_rxTotal = (uint32_t)s_rxW * s_rxH;
        s_rxActive = 1;
        s_rxPixels = 0; s_rxRunCnt = 0; s_rxStage = 0;
        return 1;
    }

    if (type == 1)
    {
        uint16_t i;
        uint8_t  v;
        if (!s_rxActive) return 0;
        for (i = 0; i < plen && s_rxPixels < s_rxTotal; i++)
        {
            v = buf[3 + i];
            switch (s_rxStage)
            {
            case 0: s_rxRunCnt = v; s_rxStage = 1; break;
            case 1: s_rxCurLo = v;  s_rxStage = 2; break;
            case 2:
                s_rxColor = (uint16_t)(s_rxCurLo | ((uint16_t)v << 8));
                s_rxStage = 0;
                while (s_rxRunCnt > 0 && s_rxPixels < s_rxTotal)
                {
                    s_ovBuf[s_rxPixels++] = s_rxColor;
                    s_rxRunCnt--;
                }
                break;
            default: s_rxStage = 0; break;
            }
        }
        return 1;
    }

    if (type == 2)
    {
        if (!s_rxActive) return 0;
        s_rxActive = 0;
        if (s_rxPixels < s_rxTotal) return 0;
        s_streamed = 1;
        s_out_w = s_rxW;
        s_out_h = s_rxH;
        return 2;
    }

    return 0;
}


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

    LCD_Image(x, y, ANIM_W, ANIM_H, (const u8 *)s_dstBuf);
}

/**==================================================================================================================
 **【文件名称�??  bsp_skin.h
 **【功能�??      Minecraft 玩�?�半�?�? —�?? �?�?"固件内置精灵"�?"PC 推流精灵"两�?�来�?
 **
 **【为�?么�?�支�? PC 推流�?
 **   Flash �?�? 2.2KB，只能存 22x26 的精灵（×4 放大�? 88x104，看�?糊）�?
 **   PC �?�? CPU 和内存，�?以渲染任意分辨率（比�? 96x112 原生，不放大）�??
 **   �?以：清晰度受限于传输带�?�和 RAM，�?�不�? Flash�?
 **
 **【传输带宽实测�??96x112 = 10752 像素
 **   原�?? RGB565   = 21504 B  �? @921600 �? 233ms（太�?�?
 **   RLE 压缩�?    = �? 3400 B �? @921600 仅需 37ms  �?
 **   压缩�? 6.3x（分辨率越高越好，因为色块更连续�?
 **
 **【数�?来源优先级�??
 **   1. PC 通过 UART 推流（清晰�?�可换皮肤，但需要电脑连�?�?
 **   2. 固件内置 22x26 精灵（�?�线也能显示，质量低�?
 **   �?机默认用内置，PC �?旦推流成功就�?动切�?�?
====================================================================================================================*/
#ifndef __BSP_SKIN_H
#define __BSP_SKIN_H

#include "stm32f4xx.h"
#include "skin_bust.h"        /* �?动生成：SKIN_TEX_W / SKIN_TEX_H */

/* ---------------- 内置精灵的放大�?�数（仅离线模式�?�? ---------------- */
#define SKIN_SCALE       4

/* ---------------- 推流精灵的最大尺寸（RAM 缓冲按�?�分配） ----------------
 * PC 送来的是"已经�?屏幕像素尺�??"的图像（PC �?�? NEAREST 放大），
 * 固件�? 1:1 存放显示，这样才能得到硬边的 Minecraft 像素块�??
 *
 * 当前方�?�：32x40 精灵 ×4 = 128x160，�?�好满屏�?
 * 两个缓冲�? 128*160*2 = 40960 字节，合�? 80KB（F407 �? 128KB�? */
#define SKIN_MAX_W       128
#define SKIN_MAX_H       160

/* 透明色：纹理�? alpha<128 的像素存成这�?值（RLE 里也用它表示透明�? */
#define SKIN_TRANSPARENT 0xF81F




/* ---------------- 状�?? ---------------- */
typedef enum
{
    SKIN_IDLE = 0,
    SKIN_WALK,
    SKIN_HURT,
    SKIN_JUMP,
    SKIN_ATTACK,
    SKIN_SLEEP,
    SKIN_RUN,
    SKIN_SNEAK,
    SKIN_ST_COUNT
} SkinState_t;


/* ---------------- 状�?�接�? ---------------- */
void        Skin_SetState(SkinState_t st);
SkinState_t Skin_GetState(void);
const char *Skin_GetStateName(SkinState_t st);

/* 推进动画，建�?�? 33ms 调一�? */
void        Skin_Tick(uint16_t dt);

/* 渲染当前帧到屏幕 */
void        Skin_Render(uint16_t x, uint16_t y, uint16_t bgColor);


/* ==================================================================
 * PC 推流接口
 * ------------------------------------------------------------------
 * 分块传输协�??（每块�?�过�?�? UART 空闲�?�?送达）：
 *
 *   块头 3 字节�?
 *     [0] 固定 'C'
 *     [1] 类型�? 0 = START（负�? 2 字节：w, h�?
 *                1 = DATA （负载为 RLE 字节流）
 *                2 = END  （无负载，提交）
 *     [2] 负载长度
 *
 *   RLE 编码�?3 字节�?组）�?
 *     [count][color_lo][color_hi]
 *     count = 1..255，color = RGB565 小�??�?0xF81F = 透明
 *
 * 用法（PC �?按顺序发）：
 *   Skin_StreamBegin(w, h)  �? 内部等价于收�? START
 *   然后每收到一�? DATA 就调 Skin_StreamData(payload, len)
 *   �?�? Skin_StreamEnd()
 * ================================================================== */

/* 处理�?块收到的 UART 数据（自动识�? START/DATA/END�?
 * 返回�? 0 = 失败/忽略, 1 = 处理了数�?, 2 = 整帧接收完成 */
uint8_t Skin_StreamChunk(const uint8_t *buf, uint16_t len);

/* �?否�?�在使用 PC 推流的精�? */
uint8_t Skin_IsStreamed(void);

/* ��λͼ�Ƿ��Ѿ�����PC ���͹������ز�λ��Ϣ�� */


/* 当前精灵尺�?�（调试�?�? */
void    Skin_GetSize(uint16_t *w, uint16_t *h);

/* 回�??到固件内�?精灵 */
void    Skin_UseFlash(void);

#endif /* __BSP_SKIN_H */

/**==================================================================================================================
 **【文件名称】  bsp_skin.h
 **【功能】      Minecraft 玩家半身像显示（头/身体分层渲染）
 **
 **【两层结构】
 **   身体层  skin_anim.c  —— 7 状态 x 8 帧，每帧不含头
 **   头部层  skin_head.c  —— 25 个 yaw 角度（-60..+60，5 度一档），只有头
 **   每帧：解压身体帧 -> 按当前角度把头部层贴上去 -> 上屏
 **   于是「头在转」和「身体在动」可以同时发生，且完全本地 30fps。
 **   例外：SLEEP 的 Head.rx=-14（头明显垂下），保留整帧烘焙，该状态头不转。
 **
 **【数据来源优先级】
 **   1. PC 推流整帧（清晰、可换皮肤，需要电脑连着）—— mcstream.py
 **   2. Flash 内置动画（离线也能动，默认就是这条）
 **   本机默认用内置动画；PC 一旦推流成功就自动切过去，发 SF 交还。
====================================================================================================================*/
#ifndef __BSP_SKIN_H
#define __BSP_SKIN_H

#include "stm32f4xx.h"
#include "skin_bust.h"        /* 自动生成：SKIN_TEX_W / SKIN_TEX_H */

/* ---------------- 内置精灵的放大倍数（仅离线模式用） ---------------- */
#define SKIN_SCALE       4

/* ---------------- 推流/显示缓冲的最大尺寸 ----------------
 * PC 送来的是「已经是屏幕像素尺寸」的图像（PC 端做 NEAREST 放大），
 * 固件按 1:1 存放显示，这样才能得到硬边的 Minecraft 像素块。
 * 当前方案：126x160 直接铺满屏幕。
 * 两个缓冲各 128*160*2 = 40960 字节，合计 80KB（F407 共 128KB）。
 */
#define SKIN_MAX_W       128
#define SKIN_MAX_H       160

/* 透明色：纹理里 alpha<128 的像素存成这个值（RLE 里也用它表示透明） */
#define SKIN_TRANSPARENT 0xF81F


/* ---------------- 状态 ---------------- */
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


/* ---------------- 状态接口 ---------------- */
void        Skin_SetState(SkinState_t st);
SkinState_t Skin_GetState(void);
const char *Skin_GetStateName(SkinState_t st);

/* 推进动画，建议每 33ms 调一次 */
void        Skin_Tick(uint16_t dt);

/* 渲染当前帧到屏幕（含头部层叠加） */
void        Skin_Render(uint16_t x, uint16_t y, uint16_t bgColor);


/* ==================================================================
 * 串口协议（字节流，长度前缀自定界）
 * ------------------------------------------------------------------
 * 四种起始字节：
 *   'C' + type + len(1B) + payload   旧格式，mcstream.py 推整帧皮肤用
 *   'D' + type + len(2B) + payload   新格式，负载可达 64KB
 *   'S' + 命令字                     状态命令 SI/SW/SH/SJ/SA/SZ/SR/SK/SF
 *   'H' + 1 字节档位                 左右角度（0..HEAD_YAW_COUNT-1）
 *   'V' + 1 字节档位                 俯仰角度（0..HEAD_TILT_COUNT-1）
 *
 * type: 0 = BEGIN（负载 w,h）  1 = DATA（RLE 字节流）  2 = END（提交）
 * RLE 每组 3 字节：[count][color_lo][color_hi]，count=1..255
 *
 * 不依赖 UART 空闲间隙分包：写入被合并或被切碎都能正确解析。
 * ================================================================== */
void    Skin_FeedStream(const uint8_t *buf, uint16_t len);

/* 取「有新推流帧待绘制」标志，读后清零 */
uint8_t Skin_ConsumeFrameFlag(void);

/* 取「收到状态命令」标志，读后清零 */
uint8_t Skin_ConsumeCmdFlag(void);

/* 推流静默计时；超过 3 秒没有新帧就自动交还本地 Flash 动画 */
void    Skin_IdleTick(uint16_t ms);

/* 设置头部姿态档位；身体动画不受影响
 *   yawIdx  0..HEAD_YAW_COUNT-1   左右（正前方 HEAD_YAW_MID）
 *   tiltIdx 0..HEAD_TILT_COUNT-1  俯仰（平视 HEAD_TILT_MID） */
void    Skin_SetHead(uint8_t yawIdx, uint8_t tiltIdx);

/* 是否正在显示 PC 推流的精灵 */
uint8_t Skin_IsStreamed(void);

/* 当前精灵尺寸（调试用） */
void    Skin_GetSize(uint16_t *w, uint16_t *h);

/* 回到固件内置动画 */
void    Skin_UseFlash(void);

#endif /* __BSP_SKIN_H */

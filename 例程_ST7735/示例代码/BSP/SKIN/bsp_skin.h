/**==================================================================================================================
 **銆愭枃浠跺悕绉般??  bsp_skin.h
 **銆愬姛鑳姐??      Minecraft 鐜╁?跺崐韬?鍍? 鈥斺?? 鏀?鎸?"鍥轰欢鍐呯疆绮剧伒"涓?"PC 鎺ㄦ祦绮剧伒"涓ょ?嶆潵婧?
 **
 **銆愪负浠?涔堣?佹敮鎸? PC 鎺ㄦ祦銆?
 **   Flash 鍙?鍓? 2.2KB锛屽彧鑳藉瓨 22x26 鐨勭簿鐏碉紙脳4 鏀惧ぇ鍚? 88x104锛岀湅鐫?绯婏級銆?
 **   PC 绔?鏈? CPU 鍜屽唴瀛橈紝鍙?浠ユ覆鏌撲换鎰忓垎杈ㄧ巼锛堟瘮濡? 96x112 鍘熺敓锛屼笉鏀惧ぇ锛夈??
 **   鎵?浠ワ細娓呮櫚搴﹀彈闄愪簬浼犺緭甯﹀?藉拰 RAM锛岃?屼笉鏄? Flash銆?
 **
 **銆愪紶杈撳甫瀹藉疄娴嬨??96x112 = 10752 鍍忕礌
 **   鍘熷?? RGB565   = 21504 B  鈫? @921600 闇? 233ms锛堝お鎱?锛?
 **   RLE 鍘嬬缉鍚?    = 绾? 3400 B 鈫? @921600 浠呴渶 37ms  鉁?
 **   鍘嬬缉姣? 6.3x锛堝垎杈ㄧ巼瓒婇珮瓒婂ソ锛屽洜涓鸿壊鍧楁洿杩炵画锛?
 **
 **銆愭暟鎹?鏉ユ簮浼樺厛绾с??
 **   1. PC 閫氳繃 UART 鎺ㄦ祦锛堟竻鏅般?佸彲鎹㈢毊鑲わ紝浣嗛渶瑕佺數鑴戣繛鐫?锛?
 **   2. 鍥轰欢鍐呯疆 22x26 绮剧伒锛堢?荤嚎涔熻兘鏄剧ず锛岃川閲忎綆锛?
 **   寮?鏈洪粯璁ょ敤鍐呯疆锛孭C 涓?鏃︽帹娴佹垚鍔熷氨鑷?鍔ㄥ垏鎹?銆?
====================================================================================================================*/
#ifndef __BSP_SKIN_H
#define __BSP_SKIN_H

#include "stm32f4xx.h"
#include "skin_bust.h"        /* 鑷?鍔ㄧ敓鎴愶細SKIN_TEX_W / SKIN_TEX_H */

/* ---------------- 鍐呯疆绮剧伒鐨勬斁澶у?嶆暟锛堜粎绂荤嚎妯″紡鐢?锛? ---------------- */
#define SKIN_SCALE       4

/* ---------------- 鎺ㄦ祦绮剧伒鐨勬渶澶у昂瀵革紙RAM 缂撳啿鎸夋?ゅ垎閰嶏級 ----------------
 * PC 閫佹潵鐨勬槸"宸茬粡鏄?灞忓箷鍍忕礌灏哄??"鐨勫浘鍍忥紙PC 绔?鍋? NEAREST 鏀惧ぇ锛夛紝
 * 鍥轰欢鎸? 1:1 瀛樻斁鏄剧ず锛岃繖鏍锋墠鑳藉緱鍒扮‖杈圭殑 Minecraft 鍍忕礌鍧椼??
 *
 * 褰撳墠鏂规?堬細32x40 绮剧伒 脳4 = 128x160锛屾?ｅソ婊″睆銆?
 * 涓や釜缂撳啿鍚? 128*160*2 = 40960 瀛楄妭锛屽悎璁? 80KB锛團407 鏈? 128KB锛? */
#define SKIN_MAX_W       128
#define SKIN_MAX_H       160

/* 閫忔槑鑹诧細绾圭悊閲? alpha<128 鐨勫儚绱犲瓨鎴愯繖涓?鍊硷紙RLE 閲屼篃鐢ㄥ畠琛ㄧず閫忔槑锛? */
#define SKIN_TRANSPARENT 0xF81F




/* ---------------- 鐘舵?? ---------------- */
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


/* ---------------- 鐘舵?佹帴鍙? ---------------- */
void        Skin_SetState(SkinState_t st);
SkinState_t Skin_GetState(void);
const char *Skin_GetStateName(SkinState_t st);

/* 鎺ㄨ繘鍔ㄧ敾锛屽缓璁?姣? 33ms 璋冧竴娆? */
void        Skin_Tick(uint16_t dt);

/* 娓叉煋褰撳墠甯у埌灞忓箷 */
void        Skin_Render(uint16_t x, uint16_t y, uint16_t bgColor);


/* ==================================================================
 * PC 鎺ㄦ祦鎺ュ彛
 * ------------------------------------------------------------------
 * 鍒嗗潡浼犺緭鍗忚??锛堟瘡鍧楅?氳繃涓?娆? UART 绌洪棽涓?鏂?閫佽揪锛夛細
 *
 *   鍧楀ご 3 瀛楄妭锛?
 *     [0] 鍥哄畾 'C'
 *     [1] 绫诲瀷锛? 0 = START锛堣礋杞? 2 瀛楄妭锛歸, h锛?
 *                1 = DATA 锛堣礋杞戒负 RLE 瀛楄妭娴侊級
 *                2 = END  锛堟棤璐熻浇锛屾彁浜わ級
 *     [2] 璐熻浇闀垮害
 *
 *   RLE 缂栫爜锛?3 瀛楄妭涓?缁勶級锛?
 *     [count][color_lo][color_hi]
 *     count = 1..255锛宑olor = RGB565 灏忕??锛?0xF81F = 閫忔槑
 *
 * 鐢ㄦ硶锛圥C 绔?鎸夐『搴忓彂锛夛細
 *   Skin_StreamBegin(w, h)  鈫? 鍐呴儴绛変环浜庢敹鍒? START
 *   鐒跺悗姣忔敹鍒颁竴鍧? DATA 灏辫皟 Skin_StreamData(payload, len)
 *   鏈?鍚? Skin_StreamEnd()
 * ================================================================== */

/* 把 UART 收到的字节原样全部喂进来（内部按长度前缀自定界）
 *   'C' type len(1B) payload   旧格式：mcstream.py 一次性推皮肤
 *   'D' type len(2B) payload   新格式：实时扭头帧（负载可达 64KB）
 *   'S' cmd                    状态命令 SI/SW/SH/SJ/SA/SZ/SR/SK/SF
 * 不依赖 UART 空闲间隙：写入被合并或被切碎都能正确解析。
 * type: 0 = BEGIN(w,h)  1 = DATA(RLE 字节)  2 = END(提交整帧) */
void    Skin_FeedStream(const uint8_t *buf, uint16_t len);

/* 取"有新推流帧待绘制"标志，读后清零 */
uint8_t Skin_ConsumeFrameFlag(void);

/* 取"收到状态命令"标志，读后清零 */
uint8_t Skin_ConsumeCmdFlag(void);

/* 推流静默计时；超过 3 秒没有新帧就自动交还本地 Flash 动画 */
void    Skin_IdleTick(uint16_t ms);

/* 设置扭头角度档位（0..HEAD_COUNT-1）；身体动画不受影响 */
void    Skin_SetHeadIdx(uint8_t idx);
uint8_t Skin_GetHeadIdx(void);

/* 鏄?鍚︽?ｅ湪浣跨敤 PC 鎺ㄦ祦鐨勭簿鐏? */
uint8_t Skin_IsStreamed(void);

/* 部位图是否已就绪（PC 推送过逐像素部位信息） */


/* 褰撳墠绮剧伒灏哄?革紙璋冭瘯鐢?锛? */
void    Skin_GetSize(uint16_t *w, uint16_t *h);

/* 鍥為??鍒板浐浠跺唴缃?绮剧伒 */
void    Skin_UseFlash(void);

#endif /* __BSP_SKIN_H */

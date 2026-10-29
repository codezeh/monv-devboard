/**==================================================================================================================
 **【文件名称】  bsp_knob.c
 **【功能】      机械旋钮(TIM8 硬件编码器) / 按键消抖 / 蜂鸣器 / DWT 延时
 **【适配】      STM32F407VET6 + STM32F4xx 标准外设库(SPL)
====================================================================================================================*/
#include "bsp_knob.h"

/* ==================================================================
 * 配置区：改这里就行
 * ================================================================== */

/* 蜂鸣器类型：1 = 有源（IO 拉高即响，推荐买这种）
 *             0 = 无源（需要 PWM 方波，本文件已内置 TIM3_CH4 方案） */
#define BZ_ACTIVE_BUZZER      1

/* EC11 一格(一个定位档)对应多少个计数
 * TIM8 用 TI12 模式是 4 倍频，绝大多数 EC11 每格 = 4 个计数
 * 如果转动一格跳了两个数，把这个值改成 2；如果转两格才动一下，改成 8 */
#define KNOB_CNT_PER_DETENT   4

/* 消抖时间 = KNOB_DEBOUNCE_MS / 10 次调用 */
#define KNOB_DEBOUNCE_TICK    2        /* 2 × 10ms = 20ms */


/* ==================================================================
 * 内部变量
 * ================================================================== */
static volatile int16_t s_lastCnt  = 0;
static volatile int32_t s_total    = 0;
static          int16_t s_remainder = 0;

typedef struct {
    uint8_t stable;   /* 消抖后的稳定状态：1=按下 */
    uint8_t cnt;      /* 消抖计数 */
    uint8_t edge;     /* 新按下事件标志（读一次清一次） */
} KeyState_t;

static KeyState_t s_key[KEY_ID_NUM];

/* 按键 → 端口/引脚 映射表 */
static GPIO_TypeDef * const s_keyPort[KEY_ID_NUM] = { GPIOC, GPIOE, GPIOE };
static const uint16_t       s_keyPin [KEY_ID_NUM] = { GPIO_Pin_0, GPIO_Pin_2, GPIO_Pin_3 };


/* ==================================================================
 * DWT 延时（Cortex-M4 周期计数器）
 *   优点：不占用任何中断、不依赖编译优化等级、精度到 CPU 周期
 * ================================================================== */
void Delay_Init(void)
{
    /* 使能 DWT 的周期计数器 */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;
}

void Delay_ms(uint32_t ms)
{
    uint32_t start  = DWT->CYCCNT;
    uint32_t ticks  = ms * (SystemCoreClock / 1000U);

    /* 无符号减法天然处理计数器回绕 */
    while ((DWT->CYCCNT - start) < ticks)
    {
        /* 空转 */
    }
}

void Delay_us(uint32_t us)
{
    uint32_t start = DWT->CYCCNT;
    uint32_t ticks = us * (SystemCoreClock / 1000000U);

    while ((DWT->CYCCNT - start) < ticks)
    {
    }
}


/* ==================================================================
 * 编码器：PC6 = TIM8_CH1, PC7 = TIM8_CH2，硬件编码器模式
 * ================================================================== */
static void encoder_init(void)
{
    GPIO_InitTypeDef        gpio;
    TIM_TimeBaseInitTypeDef tb;
    TIM_ICInitTypeDef       ic;

    /* 时钟：TIM8 挂在 APB2 */
    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOC, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_TIM8,  ENABLE);

    /* PC6 / PC7 → 复用功能 TIM8，上拉输入（编码器内部开关接地） */
    GPIO_PinAFConfig(GPIOC, GPIO_PinSource6, GPIO_AF_TIM8);
    GPIO_PinAFConfig(GPIOC, GPIO_PinSource7, GPIO_AF_TIM8);

    gpio.GPIO_Pin   = GPIO_Pin_6 | GPIO_Pin_7;
    gpio.GPIO_Mode  = GPIO_Mode_AF;
    gpio.GPIO_Speed = GPIO_Speed_100MHz;
    gpio.GPIO_OType = GPIO_OType_PP;
    gpio.GPIO_PuPd  = GPIO_PuPd_UP;
    GPIO_Init(GPIOC, &gpio);

    /* 时基：不分频，自动重装拉满（编码器靠 CNT 自增自减） */
    tb.TIM_Prescaler         = 0;
    tb.TIM_CounterMode       = TIM_CounterMode_Up;
    tb.TIM_Period            = 0xFFFF;
    tb.TIM_ClockDivision     = TIM_CKD_DIV1;
    tb.TIM_RepetitionCounter = 0;
    TIM_TimeBaseInit(TIM8, &tb);

    /* 编码器接口模式：TI1 和 TI2 都计数（4 倍频，最灵敏） */
    TIM_EncoderInterfaceConfig(TIM8,
                               TIM_EncoderMode_TI12,
                               TIM_ICPolarity_Rising,
                               TIM_ICPolarity_Rising);

    /* 输入滤波：机械编码器抖动很大，滤波器拉满(0x0F)最稳 */
    ic.TIM_ICPolarity  = TIM_ICPolarity_Rising;
    ic.TIM_ICSelection = TIM_ICSelection_DirectTI;
    ic.TIM_ICPrescaler = TIM_ICPSC_DIV1;
    ic.TIM_ICFilter    = 0x0F;

    ic.TIM_Channel = TIM_Channel_1;
    TIM_ICInit(TIM8, &ic);

    ic.TIM_Channel = TIM_Channel_2;
    TIM_ICInit(TIM8, &ic);

    TIM_SetCounter(TIM8, 0);
    s_lastCnt = 0;
    TIM_Cmd(TIM8, ENABLE);
}


int16_t Knob_GetDelta(void)
{
    int16_t now;
    int16_t diff;
    int16_t detent;

    /* TIM8 是 16 位计数器，按 16 位读取再转有符号处理回绕 */
    now  = (int16_t)(uint16_t)(TIM8->CNT);
    diff = (int16_t)(now - s_lastCnt);
    s_lastCnt = now;

    if (diff == 0) return 0;

    s_total += diff;

    /* 把 4 倍频计数折算成"格"，余数留着下次一起算，保证不丢步 */
    s_remainder += diff;
    detent = (int16_t)(s_remainder / KNOB_CNT_PER_DETENT);
    s_remainder = (int16_t)(s_remainder - detent * KNOB_CNT_PER_DETENT);

    return detent;
}

int32_t Knob_GetTotal(void)
{
    return s_total;
}


/* ==================================================================
 * 按键：PC0 / PE2 / PE3，模块输出"高电平有效"，所以配下拉输入
 *   —— 如果你的模块是"按下拉低"的裸按键板，把 GPIO_PuPd_DOWN 改成
 *      GPIO_PuPd_UP，并把下面 Key_Scan10ms 里 raw 取反即可
 * ================================================================== */
static void keys_init(void)
{
    GPIO_InitTypeDef gpio;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOC | RCC_AHB1Periph_GPIOE, ENABLE);

    gpio.GPIO_Mode  = GPIO_Mode_IN;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    gpio.GPIO_PuPd  = GPIO_PuPd_DOWN;

    gpio.GPIO_Pin = GPIO_Pin_0;                    /* PC0 = 编码器轴按下 */
    GPIO_Init(GPIOC, &gpio);

    gpio.GPIO_Pin = GPIO_Pin_2 | GPIO_Pin_3;       /* PE2 确认 / PE3 返回 */
    GPIO_Init(GPIOE, &gpio);
}

void Key_Scan10ms(void)
{
    uint8_t i;
    uint8_t raw;

    for (i = 0; i < KEY_ID_NUM; i++)
    {
        raw = (GPIO_ReadInputDataBit(s_keyPort[i], s_keyPin[i]) != Bit_RESET) ? 1 : 0;

        if (raw != s_key[i].stable)
        {
            if (++s_key[i].cnt >= KNOB_DEBOUNCE_TICK)
            {
                s_key[i].stable = raw;
                s_key[i].cnt    = 0;

                if (raw)                    /* 只在"按下"那一刻置事件 */
                {
                    s_key[i].edge = 1;
                }
            }
        }
        else
        {
            s_key[i].cnt = 0;
        }
    }
}

uint8_t Key_GetPress(uint8_t id)
{
    if (id >= KEY_ID_NUM) return 0;

    if (s_key[id].edge)
    {
        s_key[id].edge = 0;                 /* 读一次就清，避免重复触发 */
        return 1;
    }
    return 0;
}

uint8_t Key_IsDown(uint8_t id)
{
    if (id >= KEY_ID_NUM) return 0;
    return s_key[id].stable;
}


/* ==================================================================
 * 蜂鸣器：PC9
 * ================================================================== */
#if (BZ_ACTIVE_BUZZER == 0)
/* 无源蜂鸣器：PC9 = TIM3_CH4，输出约 2.7kHz 方波 */
static void buzzer_init(void)
{
    GPIO_InitTypeDef        gpio;
    TIM_TimeBaseInitTypeDef tb;
    TIM_OCInitTypeDef       oc;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOC, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM3,  ENABLE);

    GPIO_PinAFConfig(GPIOC, GPIO_PinSource9, GPIO_AF_TIM3);

    gpio.GPIO_Pin   = GPIO_Pin_9;
    gpio.GPIO_Mode  = GPIO_Mode_AF;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    gpio.GPIO_OType = GPIO_OType_PP;
    gpio.GPIO_PuPd  = GPIO_PuPd_UP;
    GPIO_Init(GPIOC, &gpio);

    /* APB1 定时器时钟 84MHz：84MHz/(83+1)=1MHz，1MHz/371 ≈ 2695Hz */
    tb.TIM_Prescaler         = 84 - 1;
    tb.TIM_CounterMode       = TIM_CounterMode_Up;
    tb.TIM_Period            = 371 - 1;
    tb.TIM_ClockDivision     = TIM_CKD_DIV1;
    tb.TIM_RepetitionCounter = 0;
    TIM_TimeBaseInit(TIM3, &tb);

    oc.TIM_OCMode      = TIM_OCMode_PWM1;
    oc.TIM_OutputState = TIM_OutputState_Enable;
    oc.TIM_Pulse       = 371 / 2;              /* 50% 占空比 */
    oc.TIM_OCPolarity  = TIM_OCPolarity_High;
    TIM_OC4Init(TIM3, &oc);

    TIM_Cmd(TIM3, DISABLE);                    /* 默认不响 */
}

void BZ_On (void) { TIM_Cmd(TIM3, ENABLE);  }
void BZ_Off(void) { TIM_Cmd(TIM3, DISABLE); }
#else
/* 有源蜂鸣器：PC9 推挽输出，拉高即响 */
static void buzzer_init(void)
{
    GPIO_InitTypeDef gpio;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOC, ENABLE);

    gpio.GPIO_Pin   = GPIO_Pin_9;
    gpio.GPIO_Mode  = GPIO_Mode_OUT;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    gpio.GPIO_OType = GPIO_OType_PP;
    gpio.GPIO_PuPd  = GPIO_PuPd_UP;
    GPIO_Init(GPIOC, &gpio);

    GPIO_ResetBits(GPIOC, GPIO_Pin_9);         /* 默认不响 */
}

void BZ_On (void) { GPIO_SetBits  (GPIOC, GPIO_Pin_9); }
void BZ_Off(void) { GPIO_ResetBits(GPIOC, GPIO_Pin_9); }
#endif

void BZ_Beep(uint16_t ms)
{
    BZ_On();
    Delay_ms(ms);
    BZ_Off();
}


/* ==================================================================
 * 统一初始化
 * ================================================================== */
void Knob_Init(void)
{
    uint8_t i;

    for (i = 0; i < KEY_ID_NUM; i++)
    {
        s_key[i].stable = 0;
        s_key[i].cnt    = 0;
        s_key[i].edge   = 0;
    }

    s_lastCnt   = 0;
    s_total     = 0;
    s_remainder = 0;

    Delay_Init();
    encoder_init();
    keys_init();
    buzzer_init();
}

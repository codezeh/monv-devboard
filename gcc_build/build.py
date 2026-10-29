#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py —— 用 GNU Arm GCC 构建 STM32F407 固件（替代 Keil MDK）

为什么用 GCC：Keil MDK-Lite 限制 32KB，而动画帧数据需要 ~390KB。
GCC 没有这个限制。

用法：
    python build.py          # 构建
    python build.py clean    # 清理
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "例程_ST7735", "示例代码")
BUILD = os.path.join(HERE, "build")
TC = r"D:\gcc\arm-gnu-toolchain-13.3.rel1-mingw-w64-i686-arm-none-eabi\bin"
PREFIX = os.path.join(TC, "arm-none-eabi-")

CC = PREFIX + "gcc.exe"
CP = PREFIX + "objcopy.exe"
SZ = PREFIX + "size.exe"

INCLUDES = [
    "User", "Core", "Core/Startup",
    "STM32F4xx_StdPeriph_Driver/inc",
    "BSP/LED", "BSP/UART", "BSP/KEY", "BSP/W25Q128",
    "BSP/LCD_1.8_ST7735", "BSP/KNOB", "BSP/SKIN",
]

C_SOURCES = [
    "User/main.c",
    "Core/system_stm32f4xx.c",
    "BSP/LED/bsp_led.c",
    "BSP/UART/bsp_UART.c",
    "BSP/KEY/bsp_key.c",
    "BSP/W25Q128/bsp_spi_flash.c",
    "BSP/LCD_1.8_ST7735/bsp_LCD_ST7735.c",
    "BSP/KNOB/bsp_knob.c",
    "BSP/SKIN/bsp_skin.c",
    "BSP/SKIN/skin_bust.c",
    "BSP/SKIN/skin_anim.c",
]

CFLAGS = ["-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb",
          "-std=gnu11", "-O2", "-g", "-Wall", "-fdata-sections", "-ffunction-sections",
          "-DUSE_STDPERIPH_DRIVER", "-DSTM32F40_41xxx"]
CFLAGS += ["-I" + os.path.join(SRC, i) for i in INCLUDES]
CFLAGS += ["-I" + HERE]          # startup file lives here

LDFLAGS = ["-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb",
           "-T" + os.path.join(HERE, "STM32F407VETx_FLASH.ld"),
           "-specs=nano.specs", "-specs=nosys.specs",
           "-Wl,--gc-sections"]


def run(cmd, desc):
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"!! {desc} 失败")
        print(r.stdout[-4000:] if r.stdout else "")
        print(r.stderr[-4000:] if r.stderr else "")
        return False
    if r.stderr and r.stderr.strip():
        # 只显示警告摘要
        lines = [l for l in r.stderr.split("\n") if "warning" in l.lower()]
        for l in lines[:5]:
            print("   WARN", l[:150])
    return True


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        import shutil
        shutil.rmtree(BUILD, ignore_errors=True)
        print("已清理")
        return

    os.makedirs(BUILD, exist_ok=True)

    # 只编译本项目实际用到的 StdPeriph 模块
    # （F4 系列不支持 fmc/fmpi2c/qspi/dsi/dma2d/ltdc 等，全部排除）
    STDP = [
        "misc", "rcc", "gpio", "exti", "spi", "usart", "flash", "tim",
        "dma", "pwr", "syscfg", "adc", "i2c", "iwdg", "wwdg", "rtc",
        "crc", "dbgmcu", "fsmc",
    ]
    sources = list(C_SOURCES)
    for m in STDP:
        if m == "misc":
            sources.append("STM32F4xx_StdPeriph_Driver/src/misc.c")
        else:
            sources.append("STM32F4xx_StdPeriph_Driver/src/stm32f4xx_%s.c" % m)

    # 启动文件（汇编）单独处理
    startup = os.path.join(HERE, "startup_stm32f407.s")
    startup_obj = os.path.join(BUILD, "startup_stm32f407.o")
    objs = []
    fail = 0
    if os.path.exists(startup):
        print("  AS  startup_stm32f407.s")
        if not run([CC] + CFLAGS + ["-c", startup, "-o", startup_obj], "startup"):
            fail += 1
        else:
            objs.append(startup_obj)
    for s in sources:
        path = s if os.path.isabs(s) else os.path.join(SRC, s)
        if not os.path.exists(path):
            path = os.path.join(HERE, s)
        if not os.path.exists(path):
            print(f"   跳过（不存在）: {s}")
            continue
        obj = os.path.join(BUILD, os.path.basename(s).replace(".c", ".o"))
        objs.append(obj)
        print(f"  CC  {os.path.basename(s)}")
        if not run([CC] + CFLAGS + ["-c", path, "-o", obj], s):
            fail += 1
            if fail > 3:
                print("错误过多，中止")
                return

    if fail:
        print(f"\n{fail} 个文件编译失败")
        return

    # 链接
    elf = os.path.join(BUILD, "app.elf")
    print(f"  LD  app.elf  ({len(objs)} objects)")
    if not run([CC] + objs + LDFLAGS + ["-Wl,-Map=" + os.path.join(BUILD, "app.map"),
                                        "-o", elf], "link"):
        return

    # 转 hex / bin
    run([CP, "-O", "ihex", elf, os.path.join(BUILD, "app.hex")], "objcopy hex")
    run([CP, "-O", "binary", "-S", elf, os.path.join(BUILD, "app.bin")], "objcopy bin")

    r = subprocess.run([SZ, elf], capture_output=True, text=True)
    print("\n" + r.stdout)
    print("产物: build/app.hex  build/app.bin")


if __name__ == "__main__":
    main()

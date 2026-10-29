#!/bin/bash
# 手动完整构建：严格按工程 .lnp 的文件清单编译 + 链接
# 用途：不开 Keil GUI 也能验证「能不能编过、Flash 超没超 32KB」
set -e
export PATH="/d/keil/ARM/ARMCC/bin:$PATH"
cd "D:/魔女开发板/例程_ST7735/示例代码"

OUT="/tmp/mbuild"
rm -rf "$OUT"; mkdir -p "$OUT"

INC="-IUser -ICore -ICore/Startup -ISTM32F4xx_StdPeriph_Driver/inc -ISTM32F4xx_StdPeriph_Driver/src -IBSP/LED -IBSP/UART -IBSP/KEY -IBSP/W25Q128 -IBSP/LCD_1.8_ST7735 -IBSP/KNOB -IBSP/SKIN"
DEF="-DUSE_STDPERIPH_DRIVER -DSTM32F40_41xxx"
CFLAGS="--c99 -c -O3 --split_sections --cpu Cortex-M4.fp --apcs=interwork $DEF"

# 工程原有模块（从 .lnp 反推）
iconv -f GBK -t UTF-8 Project/Output/STM32F407.lnp 2>/dev/null \
  | grep -oE '"\.\\output\\[a-zA-Z0-9_]+\.o"' \
  | sed 's|".\\output\\||; s|\.o"||' \
  | grep -vE "^(main|startup_stm32f40xx)$" > "$OUT/list.txt"

ERR=0
while read -r base; do
  f=""
  for cand in "STM32F4xx_StdPeriph_Driver/src/$base.c" "BSP/LED/$base.c" "BSP/UART/$base.c" \
              "BSP/W25Q128/$base.c" "BSP/LCD_1.8_ST7735/$base.c" "BSP/KNOB/$base.c" \
              "BSP/SKIN/$base.c" "User/$base.c" "Core/$base.c"; do
    [ -f "$cand" ] && { f="$cand"; break; }
  done
  if [ -z "$f" ]; then echo "!! 找不到源文件: $base"; ERR=1; continue; fi
  armcc $CFLAGS $INC "$f" -o "$OUT/$base.o" 2> "$OUT/$base.err" || { echo "!! 编译失败: $f"; head -5 "$OUT/$base.err"; ERR=1; }
done < "$OUT/list.txt"

# 新增的项目模块
for f in User/main.c BSP/KNOB/bsp_knob.c BSP/SKIN/bsp_skin.c BSP/SKIN/skin_bust.c; do
  b=$(basename "$f" .c)
  armcc $CFLAGS $INC "$f" -o "$OUT/$b.o" 2> "$OUT/$b.err" || { echo "!! 编译失败: $f"; head -8 "$OUT/$b.err"; ERR=1; }
done

[ $ERR -eq 1 ] && { echo "== 有编译错误 =="; exit 1; }
echo "== 全部 C 源文件编译通过 =="

armasm --cpu Cortex-M4.fp --apcs=interwork Core/Startup/startup_stm32f40xx.s -o "$OUT/startup_stm32f40xx.o" 2>&1 | head -3
echo "== 启动文件汇编通过 =="

OBJS=""; for o in "$OUT"/*.o; do OBJS="$OBJS \"$o\""; done
eval armlink --cpu=Cortex-M4.fp.sp $OBJS \
  --strict --scatter "Project/Output/STM32F407.sct" \
  --info sizes --info totals -o "$OUT/STM32F407.axf" 2>&1 | grep -E "Total RO|Total RW|Total ROM|error|Error" | head -10
echo "== 链接完成 =="

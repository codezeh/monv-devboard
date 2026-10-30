#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fw_selftest.py —— 固件串口自检（不需要游戏、不需要看屏幕）

验证三件事：
  1. 8 个状态命令（SI/SW/SH/SJ/SA/SK/SR/SZ）板子都有正确回显
  2. 25 档扭头角度（'H'+档位）每档都收到 'h' ACK
  3. 非法档位被忽略、且不影响后续命令

为什么能这么测：固件对每条命令都回 1 字节 ACK
（'h'=角度已设置，'K'=整帧推流已提交，'-> XXX'=状态回显），
所以不用盯着屏幕猜。

用法：
    python tools/fw_selftest.py                 # 默认 COM5 @921600
    python tools/fw_selftest.py -p COM7
"""
import argparse
import sys
import time

import serial

STATES = [(b"SI", "IDLE"), (b"SW", "WALK"), (b"SH", "HURT"), (b"SJ", "JUMP"),
          (b"SA", "ATTACK"), (b"SK", "SNEAK"), (b"SR", "RUN"), (b"SZ", "SLEEP")]

HEAD_COUNT = 25          # 与 skin_head.h 的 HEAD_COUNT 一致
HEAD_MID = 12            # 正前方（0°）档位


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", default="COM5")
    ap.add_argument("-b", "--baud", type=int, default=921600)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    time.sleep(0.8)
    ser.reset_input_buffer()

    # 先回到本地动画，确认链路活着
    ser.write(b"SF")
    time.sleep(0.2)
    ser.read(200)

    fail = 0

    print("1) 状态命令")
    ok = 0
    for cmd, name in STATES:
        ser.reset_input_buffer()
        ser.write(cmd)
        time.sleep(0.10)
        r = ser.read(64)
        if name.encode() in r:
            ok += 1
        else:
            print("   %s 期望 %s，实际 %r" % (cmd.decode(), name, r))
    print("   %d/%d" % (ok, len(STATES)))
    fail += len(STATES) - ok

    print("2) 扭头角度档（来回各一遍）")
    ok = 0
    total = 0
    for idx in list(range(HEAD_COUNT)) + list(range(HEAD_COUNT - 1, -1, -1)):
        total += 1
        ser.reset_input_buffer()
        ser.write(b"H" + bytes([idx]))
        time.sleep(0.03)
        if b"h" in ser.read(16):
            ok += 1
        else:
            print("   档位 %d 无 ACK" % idx)
    print("   %d/%d" % (ok, total))
    fail += total - ok

    print("3) 边界：非法档位 200")
    ser.reset_input_buffer()
    ser.write(b"H" + bytes([200]))
    time.sleep(0.10)
    ser.read(32)                      # 有 ACK 但不下发，属正常
    ser.reset_input_buffer()
    ser.write(b"SI")
    time.sleep(0.15)
    alive = b"-> IDLE" in ser.read(64)
    print("   板子仍正常响应: %s" % ("是" if alive else "否"))
    if not alive:
        fail += 1

    # 收尾：回正 + 待机 + 交还本地动画
    ser.write(b"H" + bytes([HEAD_MID]))
    ser.write(b"SI")
    ser.write(b"SF")
    ser.close()

    print()
    if fail == 0:
        print("结论: 全部通过（状态回显 + 扭头档位 + 边界）")
        return 0
    print("结论: %d 项失败" % fail)
    return 1


if __name__ == "__main__":
    sys.exit(main())

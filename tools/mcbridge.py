#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcbridge.py —— 把 Minecraft 的实时状态转发给 F407 半身像屏

数据来源（二选一，自动识别）：
    文件模式：Scarpet 脚本写的 mc_state.txt      内容如 "WALK 18.5 0.132"
    日志模式：tail 游戏日志里的 "MCSTATE ..." 行

去向：串口 COM5 @921600，发 2 字节命令 SI/SW/SH/SJ/SA/SZ

用法：
    python mcbridge.py --find                  # 自动找 mc_state.txt
    python mcbridge.py --file <路径>           # 指定状态文件
    python mcbridge.py --source log            # 从游戏日志读
    python mcbridge.py --dry-run               # 只打印状态，不写串口

⚠️ 串口独占：本脚本和 mcstream.py 都用 COM5，不能同时运行。
   推完图请关掉 mcstream 再开本脚本。

依赖：pip install pyserial
"""

import argparse
import os
import re
import sys
import time

# ---- 状态 → 固件命令（与 bsp_skin.c 的 handle_uart 对应）----
STATE_CMD = {
    "IDLE": b"SI",
    "WALK": b"SW",
    "HURT": b"SH",
    "JUMP": b"SJ",
    "ATTACK": b"SA",
    "SLEEP": b"SZ",
}

# 最小重发间隔：防止同一状态被瞬间重复触发。
# 脚本已改为"仅变化时输出"，所以这里不需要再等状态稳定。
HOLD_MS = 100        # 同一状态的最小重发间隔（毫秒）


def log(*a):
    print("[bridge]", *a, flush=True)


# ------------------------------------------------------------------ 找文件
def find_state_file():
    """在常见位置搜 mc_state.txt"""
    # 本机实际游戏目录（PCL + 自定义根目录）
    candidates = [
        r"E:\我的世界文件\wwworld\.minecraft",
        r"E:\.minecraft",
        os.path.expanduser(r"~\AppData\Roaming\.minecraft"),
    ]
    base = next((c for c in candidates if os.path.isdir(c)), candidates[0])

    hits = []
    for root, dirs, files in os.walk(base):
        # 只往下 6 层，避免全盘扫描
        if root.count(os.sep) - base.count(os.sep) > 6:
            dirs[:] = []
            continue
        if "mc_state.txt" in files:
            hits.append(os.path.join(root, "mc_state.txt"))

    return hits


# ------------------------------------------------------------------ 解析
RE_STATE = re.compile(r"^\s*(IDLE|WALK|HURT|JUMP|ATTACK|SLEEP)\s+([\d.]+)\s+([\d.]+)")


def parse_line(line):
    """'WALK 18.5 0.132' → ('WALK', 18.5, 0.132)"""
    m = RE_STATE.match(line)
    if not m:
        return None
    return m.group(1), float(m.group(2)), float(m.group(3))


# ------------------------------------------------------------------ 串口
class Board:
    def __init__(self, port, baud, dry_run=False):
        self.dry = dry_run
        self.ser = None
        self.last_state = None
        self.last_send = 0.0

        if dry_run:
            return
        try:
            import serial
        except ImportError:
            sys.exit("需要 pyserial：pip install pyserial")
        try:
            self.ser = serial.Serial(port, baud, timeout=0.5)
        except Exception as e:
            log(f"❗打不开串口 {port}：{e}")
            log("")
            log("常见原因：")
            log("  · 另一个程序正占着这个口（Windows 串口是独占的）")
            log("    → 本脚本是长驻的，若已在另一个窗口运行，先停掉它")
            log("    → 或关掉串口助手 / Keil 调试")
            log("  · 板子没插好，或 CH340 驱动没装")
            log("")
            log("注：mcstream.py 是发完就退出的，不会长期占用串口；")
            log("    只有本脚本(mcbridge)会一直占着。")
            sys.exit(1)
        try:
            self.ser.dtr = False
            self.ser.rts = False
        except Exception:
            pass
        log(f"串口已打开 {port} @ {baud}")

    def feed(self, state):
        """喂入当前状态；内部做去抖后决定是否发送"""
        if state not in STATE_CMD:
            return
        now = time.time()

        if state == self.last_state:
            return

        # 注意：scarpet 脚本只在【状态变化时】输出，
        # 所以桥接收到的是"变化事件流"，不是"持续状态流"。
        # 因此不能要求同一状态连续出现两次（那样交替态永远下发不了），
        # 只需限制最小重发间隔，防止同一状态被瞬间重复触发。
        if (now - self.last_send) * 1000 < HOLD_MS:
            return

        cmd = STATE_CMD[state]
        if self.dry:
            log(f"[dry-run] 发送 {cmd.decode()}  ({state})")
        else:
            self.ser.write(cmd)
            self.ser.flush()
            log(f"发送 {cmd.decode()}  ({state})")
        self.last_state = state
        self.last_send = now

    def close(self):
        if self.ser:
            self.ser.close()


# ------------------------------------------------------------------ 主循环
def run_file(path, board, poll_ms=60):
    log(f"监视文件：{path}")
    log("Ctrl+C 退出")
    last_mtime = 0
    last_data = None
    missing = 0

    while True:
        try:
            mt = os.path.getmtime(path)
        except OSError:
            missing += 1
            if missing == 30:
                log("⚠️ 文件不存在——Scarpet 脚本加载了吗？(/script load mc_state)")
            time.sleep(poll_ms / 1000.0)
            continue

        if mt != last_mtime:
            last_mtime = mt
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    line = f.read().strip()
            except OSError:
                line = ""

            data = parse_line(line)
            if data:
                last_data = data
                st, hp, spd = data
                board.feed(st)
                print(f"\r  状态={st:<6} 血量={hp:5.1f} 速度={spd:.3f}   ",
                      end="", flush=True)
            elif line:
                log(f"⚠️ 无法解析：{line!r}")

        time.sleep(poll_ms / 1000.0)




def push_image(ser, skin_path, preset, yaw, pitch, arms):
    """把高清皮肤推给板子。

    ★ 为什么桥接必须自己推图：
      推流的高清图只存在板子 RAM 里，一复位就退回固件内置的 22x26 小图。
      而"打开串口"这个动作本身会因 DTR/RTS 电平变化触发板子复位。
      所以顺序必须是：先开串口(可能复位) → 再推图 → 最后才开始转发状态。
      否则每次启动桥接都会把图像弄丢，屏幕回到初始小图。
    """
    try:
        import mcstream
    except ImportError as e:
        log(f"跳过推图（{e}）")
        return False
    if not os.path.exists(skin_path):
        log(f"跳过推图（找不到 {skin_path}）")
        return False

    log(f"推送皮肤 {os.path.basename(skin_path)} ...")
    img, arm, texel = mcstream.render_preset(skin_path, preset, yaw, pitch, arms)
    px = mcstream.to_pixels(img)
    data, enc, nchunks = mcstream.pack_frame(img.width, img.height, px)

    i = 0
    while i < len(data):
        blk = data[i:i + 153]
        ser.write(blk)
        ser.flush()
        i += 153
        time.sleep(0.080)          # 必须 >= 80ms，小块(150B)才能稳定分帧

    time.sleep(0.8)

    # 推完图再推「部位矩形」——固件靠它做局部动画（手臂摆动/头垂下）
    try:
        import part_regions
        _fw, _fh, _px, pm, _tx = part_regions.export_frame(
            skin_path, preset=preset, arms=arms, yaw=yaw, pitch=pitch)
        mcstream.send_frames(ser, mcstream.pack_parts(pm, _tx[0], _tx[1]))
        time.sleep(0.8)
        log(f"部位矩形已推送（{len(parts)}B）")
    except Exception as e:
        log(f"推部位矩形失败（动画会退化为整体位移）：{e}")

    try:
        resp = ser.readline().decode("ascii", "replace").strip()
        log(f"图像已推送 {img.width}x{img.height}（{len(data)}B）"
            + (f"  板子: {resp}" if resp else ""))
    except Exception:
        log(f"图像已推送 {img.width}x{img.height}")
    return True


def find_latest_log():
    """在 .minecraft/versions/*/logs/latest.log 里找最新修改的那个"""
    roots = [
        r"E:\我的世界文件\wwworld\.minecraft",
        r"E:\.minecraft",
        os.path.expanduser(r"~\AppData\Roaming\.minecraft"),
    ]
    best, best_mt = None, 0
    for base in roots:
        vdir = os.path.join(base, "versions")
        if not os.path.isdir(vdir):
            continue
        for name in os.listdir(vdir):
            lp = os.path.join(vdir, name, "logs", "latest.log")
            try:
                mt = os.path.getmtime(lp)
            except OSError:
                continue
            if mt > best_mt:
                best, best_mt = lp, mt
    return best


def seed_last_state(log_path, board):
    """启动时把日志里最后一条 MCSTATE 立刻下发，避免板子停在旧状态"""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            tail = f.read()[-200000:]
        m = list(re.finditer(r"MCSTATE\s+(\w+)\s+([\d.]+)\s+([\d.]+)", tail))
        if m:
            st = m[-1].group(1)
            if st in STATE_CMD:
                if not board.dry:
                    board.ser.write(STATE_CMD[st])
                    board.ser.flush()
                board.last_state = st
                board.last_send = time.time()
                log(f"启动同步：当前状态 {st}")
    except OSError:
        pass


def run_log(log_path, board, poll_ms=60):
    log(f"监视日志：{log_path}")
    seed_last_state(log_path, board)
    log("Ctrl+C 退出")
    pos = 0
    try:
        pos = os.path.getsize(log_path)
    except OSError:
        pass

    while True:
        try:
            size = os.path.getsize(log_path)
            if size < pos:          # 日志轮转
                pos = 0
            if size > pos:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    for line in f:
                        m = re.search(r"MCSTATE\s+(\w+)\s+([\d.]+)\s+([\d.]+)", line)
                        if m:
                            st, hp, spd = m.group(1), float(m.group(2)), float(m.group(3))
                            board.feed(st)
                            print(f"\r  状态={st:<6} 血量={hp:5.1f} 速度={spd:.3f}   ",
                                  end="", flush=True)
                    pos = f.tell()
        except OSError:
            pass
        time.sleep(poll_ms / 1000.0)


def main():
    ap = argparse.ArgumentParser(description="MC 状态 → F407 串口桥")
    ap.add_argument("--file", help="mc_state.txt 路径")
    ap.add_argument("--find", action="store_true", help="自动搜索 mc_state.txt")
    ap.add_argument("--source", choices=["file", "log"], default="file")
    ap.add_argument("--skin", default="skin_user.png", help="要推送的皮肤（默认 skin_user.png）")
    ap.add_argument("--preset", default="hd", help="推图预设 pixel/hd/full")
    ap.add_argument("--push-arms", default="slim", help="推图手臂 classic/slim")
    ap.add_argument("--no-push", action="store_true", help="启动时不推图")
    ap.add_argument("--auto-log", action="store_true",
                    help="自动找最新的游戏 latest.log（配合 --source log）")
    ap.add_argument("--log-file", help="游戏 latest.log 路径（--source log 时用）")
    ap.add_argument("-p", "--port", help="串口，默认自动检测")
    ap.add_argument("-b", "--baud", type=int, default=921600)
    ap.add_argument("--dry-run", action="store_true", help="不写串口，只打印")
    ap.add_argument("--poll", type=int, default=60, help="轮询间隔 ms")
    args = ap.parse_args()

    # ---- 找状态文件 ----
    if args.source == "file":
        path = args.file
        if not path or args.find:
            hits = find_state_file()
            if not hits:
                log("没找到 mc_state.txt。确认：")
                log("  1) Carpet 已装且游戏已启动过")
                log("  2) 已执行 /script load mc_state")
                log("  3) 或手动指定 --file <路径>")
                sys.exit(1)
            path = hits[0]
            if len(hits) > 1:
                log(f"找到多个，用第一个：{path}")
                for h in hits[1:]:
                    log(f"  其它：{h}")
        log_path = None
    else:
        log_path = args.log_file
        if not log_path and args.auto_log:
            log_path = find_latest_log()
            if not log_path:
                sys.exit("没找到任何 latest.log。游戏启动过了吗？")
        if not log_path:
            sys.exit("--source log 需要 --log-file <路径> 或 --auto-log")
        path = None

    # ---- 串口 ----
    port = args.port
    if not port and not args.dry_run:
        import serial.tools.list_ports as lp
        ports = [p.device for p in lp.comports()]
        if not ports:
            sys.exit("没找到串口。板子插好了吗？")
        port = ports[0]
        if len(ports) > 1:
            log(f"多个串口，用 {port}（要指定请加 -p）")

    board = Board(port or "DRY", args.baud, args.dry_run)

    # ★ 先推图（串口刚打开这个动作可能已让板子复位），再开始转发状态。
    #   否则每次启动桥接，屏幕都会退回固件内置的小图。
    if not args.no_push and not args.dry_run:
        skin = args.skin
        if not os.path.isabs(skin):
            skin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", skin)
        push_image(board.ser, os.path.normpath(skin), args.preset,
                   24.0, -10.0, args.push_arms)

    try:
        if args.source == "file":
            run_file(path, board, args.poll)
        else:
            run_log(log_path, board, args.poll)
    except KeyboardInterrupt:
        print()
        log("退出")
    finally:
        board.close()


if __name__ == "__main__":
    main()

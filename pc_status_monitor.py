"""
PC 状态推送到魔女 F407 核心板（1.8" ST7735 屏）

协议：一行文本，\n 结尾
      C <cpu%> <mem%> <temp℃>
      例：C 12 34 56

用法：
      python pc_status_monitor.py            # 默认 COM5, 115200, 每秒一帧
      python pc_status_monitor.py COM5 115200 1

按 Ctrl+C 退出。
"""
import sys
import time
import serial

try:
    import psutil
except ImportError:
    print("[!] 缺少 psutil，正在安装...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil", "-q"])
    import psutil


def get_cpu_temp():
    """尽力读取 CPU 温度；多数 Windows 机器读不到，读不到返回 0。"""
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for _, entries in temps.items():
                if entries:
                    return int(entries[0].current)
    except Exception:
        pass
    return 0


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
    interval = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    print(f"[*] 打开 {port} @ {baud}")
    ser = serial.Serial(port, baud, timeout=1)
    time.sleep(0.3)

    # 让 psutil 的首次采样有基准
    psutil.cpu_percent(interval=None)
    time.sleep(0.5)

    print("[*] 开始推送，Ctrl+C 退出\n")
    n = 0
    try:
        while True:
            cpu = int(round(psutil.cpu_percent(interval=None)))
            mem = int(round(psutil.virtual_memory().percent))
            temp = get_cpu_temp()

            line = f"C {cpu} {mem} {temp}\n"
            ser.write(line.encode("ascii"))
            n += 1

            if n % 5 == 1:
                print(f"[{n:5d}] {line.strip()}", flush=True)

            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n[*] 已发送 {n} 帧，退出")
    finally:
        ser.close()


if __name__ == "__main__":
    main()

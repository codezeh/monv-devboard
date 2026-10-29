# 魔女 STM32F407VET6 核心板 · PC 状态监视器 —— 已跑通记录

> 完成时间：2026-10-25
> 状态：**硬件验证通过，功能正常运行**
> 本文档记录**实际验证过的**配置，与早期规划不同，以本文为准。

---

## 一、最终成果

```
你的电脑 (psutil 读 CPU/内存)
   ↓  USB Type-C（一根线：供电 + 烧录 + 通信）
板载 USB 转 TTL (COM5, 115200)
   ↓  UART1 = PA9/PA10
STM32F407VET6
   ↓  SPI1
1.8" ST7735 128×160 屏
```

屏幕每秒刷新：CPU%、内存%、CPU 温度%，带进度条。

---

## 二、硬件接线（实测确认）

### 屏幕 1.8" ST7735 8 针

| 屏丝印 | 接到 | 精确孔位 |
|---|---|---|
| GND | GND | 左排第 2 排 |
| VCC | **3.3V** | 右排第 1 排（⚠️ 切勿接 5V） |
| SCL | **PA5** | 左排第 11 排 · 右孔 |
| SDA | **PA7** | 左排第 12 排 · 右孔 |
| RES | **3.3V** | 与 VCC 同一孔 |
| DC | **PA12** | 右排第 14 排 · 左孔 |
| CS | **PA8** | 右排第 15 排 · 左孔 |
| BLK | **PA15** | 右排第 14 排 · 右孔 |

> ⚠️ **DC 和 BLK 在同一排（右排第 14 排）**，一左一右，最容易接反。
> 板上丝印那一排印的是 `A12 | A15`。

**方位基准**：SWD 焊盘朝上、USB Type-C 朝下。左排最上 = 5.0V，右排最上 = 3.3V。

### 核心板板载资源（实测）

| 资源 | 引脚 |
|---|---|
| 蓝色 LED | **PB2** |
| 绿色 LED | **PC5** |
| 用户按键 | **PA0** |
| USB 转 TTL | **USART1 = PA9/PA10** |
| 板载仿真器 | **CMSIS-DAP，SWDIO=PA13 / SWCLK=PA14** |
| 晶振 | **25 MHz**（不是 8 MHz！） |

---

## 三、开发环境（已配好，可直接复用）

| 项 | 值 |
|---|---|
| Keil | `D:\keil`（MDK 5.31） |
| 编译器 | `ARMCC V5.06 update 6`，路径 `D:\keil\ARM\ARMCC\Bin` |
| 器件包 | Keil.STM32F4xx_DFP.2.13.0 |
| 工程 | `例程_ST7735\示例代码\Project\STM32F407.uvprojx` |
| 编译选项 | `-O3` + `One ELF Section per Function`（**必须**，否则屏幕初始化失败） |

### 命令行编译/烧录（不用打开 Keil 界面）

```powershell
$env:Path="D:\keil\ARM\ARMCC\bin;" + $env:Path
cmd /c '"D:\keil\UV4\UV4.exe" -b "<工程路径>" -j0 -o "<日志>"'   # 编译
cmd /c '"D:\keil\UV4\UV4.exe" -f "<工程路径>" -j0 -o "<日志>"'   # 烧录
```

### 调试器配置修复（重要）

**现象**：`Options → Debug → Settings` 对话框灰色、打不开。
**原因**：工程里 `pMon` 写的是相对路径 `BIN\CMSIS_AGDI.dll`，实际 DLL 在 `D:\keil\ARM\BIN\`，UV4 从 `D:\keil\UV4` 启动时解析不到。
**修复**：`STM32F407.uvoptx` 中改为绝对路径：

```xml
<pMon>D:\keil\ARM\BIN\CMSIS_AGDI.dll</pMon>
```

改完命令行烧录直接可用，不必打开那个对话框。

---

## 四、对官方例程的三处必要修改

官方 `11-1 LCD_1.8寸_ST7735_8位` 是为**开发板**写的（板上有 W25Q128），核心板必须改：

| 文件 | 改动 | 原因 |
|---|---|---|
| `bsp_W25Q128.h` | 注释 `#define GBK_STORAGE_ADDR 0x00A00000` | 核心板无外部 Flash，汉字会去读空芯片 |
| `bsp_W25Q128.c` | 加本地兜底 `#ifndef GBK_STORAGE_ADDR` | 该文件内部仍引用此宏，否则编译报错 |
| `User/main.c` | 注释 `W25Q128_Init()` | 无芯片；且它会把 SPI1 改成 CPOL=1/CPHA=1 2分频，干扰 LCD |
| `User/main.c` | 中文 `LCD_String` 改用 `LCD_ShowChinese` | `LCD_String` 的汉字分支必走 `W25Q128_ReadFontData()`，无 Flash 必乱码 |
| `User/main.c` | 注释 32KB 图片数组 `bmp_128_128` | **MDK-Lite 32KB 链接限制的元凶**，删掉后镜像 57KB→24KB |

### 关键认知

- **F4 没有 `GPIO_PinRemapConfig`**，也没有 `GPIO_Remap_SWJ_JTAGDisable`（那是 **F1** 的 API + AFIO 外设）。
- F4 的 PA15 直接 `GPIO_Mode_OUT` 就能用，**不需要任何 JTAG 重映射**。官方驱动没写这段是对的。

---

## 五、PC 端脚本

`pc_status_monitor.py`

```powershell
# 默认 COM5, 115200, 每秒一帧
python pc_status_monitor.py

# 自定义
python pc_status_monitor.py COM5 115200 2
```

**依赖**：`pyserial`、`psutil`

### 串口独占提醒

**同一时刻只能由一个程序占用 COM5。** 如果脚本在跑，串口助手打不开；反之亦然。
Keil 调试模式也会占用，下载时先退出调试。

---

## 六、通信协议

```
C <cpu%> <mem%> <temp℃>\n
```

例：`C 9 45 0` → CPU 9%、内存 45%、温度 0℃

- 以 `\n` 结尾，一行一帧
- 固件用 UART1 空闲中断收帧，`UART1_GetRxNum()` > 0 表示收到
- 数值超出范围会被钳位（CPU/MEM 0~100，TEMP 0~125）

### 温度显示 0 是正常的

Windows 下 `psutil.sensors_temperatures()` 基本读不到 CPU 温度（需管理员权限 + 特定硬件驱动）。
要真实温度，方案：用 **LibreHardwareMonitor** 导出 WMI/JSON，再让脚本读取。不是固件问题。

---

## 七、当前资源占用

| 项 | 值 | 备注 |
|---|---|---|
| Code | 7826 B | |
| RO-data | 13998 B | 主要是字模 |
| RW-data | 60 B | |
| ZI-data | 12516 B | |
| **Flash 合计** | **约 21.8 KB** | MDK-Lite 限 32 KB，**余量约 10 KB** |
| RAM | 约 12.6 KB | 512KB 芯片的 192KB SRAM，余量极大 |

### ⚠️ 32KB 是硬天花板

Keil 装的是 **MDK-Lite 评估版**（`TOOL_VISOR=mdk_lite`），链接限制 32KB。
当前 21.8KB，还能加少量功能。**但要上 LVGL（需 100KB+）必须换工具链。**

免费方案：
- **STM32CubeIDE**（ST 官方，GCC，无代码限制）
- **CLion + GCC ARM** / **PlatformIO**
- MDK 社区版**不支持 AC5**，与现工程不兼容

---

## 八、后续可加功能（均在 10KB 余量内）

| 功能 | 预估 | 难度 |
|---|---|---|
| 显示磁盘占用、网络速率 | +2KB | 低（PC 端加字段即可） |
| 加日期时间（PC 下发） | +2KB | 低 |
| 双屏切换（CPU/内存 ↔ 磁盘/网络） | +3KB | 中 |
| 断线检测（超时显示 `--`） | +1KB | 低 |
| 局部刷新替代整屏重绘（消除闪烁） | +2KB | 中 |
| 换成 2.4"/2.8" 大屏 | — | 需改初始化序列 |

**当前已知小毛病**：每秒整屏重绘，肉眼可见轻微闪。改局部刷新可解决。

---

## 九、文件清单

| 文件 | 说明 |
|---|---|
| `main_final_pc_monitor.c` | 当前固件源码（归档副本） |
| `pc_status_monitor.py` | PC 端推送脚本 |
| `例程_ST7735\示例代码\` | 完整 Keil 工程（可直接编译烧录） |
| `魔女F407VET6_LVGL中控屏_精确方案.md` | 早期规划文档（**部分内容已作废**，以本文为准） |

# 魔女开发板 · Minecraft 半身像显示器

一块 **STM32F407 + ST7735 (128×160)** 的小屏，实时显示 Minecraft 玩家半身像：
走动会摆手、受伤会变红、跳跃会上移，**头会跟着你的视角左右转、抬头低头**。

头部是 3D 渲染的（不是 2D 贴图翻转），身体动画和头部姿态是**两个独立图层**，
所以「头在转」和「身体在动」可以同时发生，全程本地 30fps。

```
   Minecraft (Fabric 模组)                    STM32F407 + ST7735
   ┌────────────────────┐   串口 921600    ┌───────────────────────┐
   │ 读玩家状态/视角      │ ── 2~4 字节 ──>  │ 身体层 7状态×8帧(Flash) │
   │ 后台线程发送         │                 │ 头部层 13×5 姿态(Flash) │
   └────────────────────┘                 │ 本地合成 → LCD 30fps   │
                                           └───────────────────────┘
```

---

## 目录结构

| 路径 | 内容 |
|---|---|
| `例程_ST7735/示例代码/` | 固件源码（Keil 工程 + GCC 构建） |
| `例程_ST7735/示例代码/BSP/SKIN/` | 皮肤/动画核心：`bsp_skin.c`、`skin_anim.c`（身体层）、`skin_head.c`（头部层） |
| `gcc_build/` | **GCC 构建脚本**（推荐，见下文） |
| `模组/源码/` | Fabric 模组源码（Java + Gradle） |
| `模组/mcserial-1.0.0.jar` | 编好的模组，可直接丢进 `mods/` |
| `tools/` | PC 端渲染/生成/自检脚本 |

---

## 快速上手

### 1. 烧固件

固件需要 **GNU Arm Toolchain 13.x**（不能用 Keil：MDK-Lite 链接限 32KB，
而动画数据约 400KB，会报 `L6047U`）。

```bash
# 设置工具链路径（也可以直接改 build.py 里的 _CANDIDATES）
set ARM_GCC_BIN=D:\gcc\arm-gnu-toolchain-13.3.rel1-mingw-w64-i686-arm-none-eabi\bin

python gcc_build/build.py          # 产物 gcc_build/build/app.hex
```

烧录用 pyOCD + STM32F4 设备包（板载 CMSIS-DAP 即可）：

```bash
pip install pyocd
pyocd pack install stm32f407vetx          # 或自己下 Keil.STM32F4xx_DFP.*.pack
pyocd flash --target stm32f407ve --freq 1000000 gcc_build/build/app.hex
```

> 用 Keil 打开 `例程_ST7735/示例代码/Project/STM32F407.uvprojx` 也能编辑调试，
> 但**链接会因 MDK-Lite 32KB 限制失败**，请用上面的 GCC 路径编译。

### 2. 装模组

1. 装 [Fabric Loader](https://fabricmc.net/) + **Minecraft 1.21.8** + **Fabric API**
2. 把 `模组/mcserial-1.0.0.jar` 放进 `<你的 .minecraft>/mods/`
3. 启动游戏进世界 —— 无需任何命令

串口默认找 **COM5**（找不到就挑描述含 `CMSIS` / `USB` 的），波特率 921600。

### 3. 换皮肤

```bash
python tools/mcstream.py -p COM5 --preset full 你的皮肤.png
```

> 串口是独占的：**换皮肤前先关游戏**（模组会一直占着口）。

---

## 自检（不用游戏、不用看屏幕）

```bash
python tools/fw_selftest.py -p COM5
```

验证状态命令回显、左右 13 档、俯仰 5 档、13×5 全组合、非法档位容错。
固件对每条命令都回 1 字节 ACK（`h`/`v`/`K`），所以能自动化验证。

---

## 串口协议

字节流 + 长度前缀自定界（**不依赖 UART 空闲间隙分包**，写入被合并/切碎都能解析）。
详细定义见 `bsp_skin.h`。

| 命令 | 含义 |
|---|---|
| `'S' + 命令字` | 状态：`SI`待机 `SW`走 `SH`伤 `SJ`跳 `SA`攻 `SZ`睡 `SR`跑 `SK`潜 `SF`交还本地动画 |
| `'H' + 档位` | 左右：0..12（-60°..+60°，10°/档，6=正前方） |
| `'V' + 档位` | 俯仰：0..4（-30°..+30°，15°/档，2=平视） |
| `'C'/'D' + type + len + 负载` | 整帧推流（RLE），`C` 是单字节长度兼容旧工具 |

---

## 为什么分两层渲染

板子只有 512KB Flash，没法实时算 3D。所以头身姿态都在 PC 上预渲染好烘进 Flash：

- **身体层**：7 状态 × 8 帧（走动摆手、跳跃上移等），**不含头**
- **头部层**：13(左右) × 5(俯仰) = 65 张，**只有头**

固件每帧：解压身体帧 → 按当前档位把头部层贴上去（透明像素跳过）→ 上屏。
好处是头部姿态切换只需 2 字节，且和身体动画互不干扰。

**Flash 账**：身体层 205KB + 头部层 197KB ≈ 402KB，占 512KB 的 79%。

> `SLEEP` 是例外：那一行头垂得很低（`Head.rx=-14`），用通用头层会看着「没睡」，
> 所以保留整帧烘焙，睡觉时头不参与旋转。

---

## 头部姿态是怎么跟随视角的

两个轴的信号来源**刻意不同**：

- **俯仰** = `player.getPitch()` 直接取。相机俯仰本身就是绝对角，抬头就抬着。
- **左右** = 视角 yaw 增量累积 + 2.5 秒缓慢回中。因为原版 `turnHead()` 每 tick
  把 `bodyYaw` 往 `headYaw` 拉 0.3，身体永远跟着视角转，拿不到绝对左右参考。

模组里所有串口 IO 都在**独立发送线程**，渲染线程只写几个 volatile 字段，
所以串口再慢也不会卡游戏。

---

## 重新生成动画数据

需要 glTF 玩家模型（仓库**不附带**，属于第三方资产）。
从任意 [Axolotl](https://github.com/Axolotl-Launcher/Axolotl) 安装目录取：

```
<Axolotl>/packages/assets/models/slim-player.gltf      # 4px 手臂
<Axolotl>/packages/assets/models/classic-player.gltf   # 3px 手臂
```

然后：

```bash
set AXOLOTL_MODEL_DIR=D:\axolotl\packages\assets\models

python tools/gen_anim_c.py     # 重新渲染 身体层 + 头部层，写入 BSP/SKIN/*.c
python gcc_build/build.py      # 重新编译
```

想改转头/抬头的档位范围或步长，改 `tools/gen_anim_c.py` 顶部的
`HEAD_YAW` / `HEAD_TILT` 两个列表即可（注意 Flash 余量）。

---

## 已知限制

- 头部是预渲染档位，**不是连续旋转**：左右 10° 一档、俯仰 15° 一档
- `SLEEP` 状态头不跟随视角
- 极端组合（左右 ±60° 同时俯仰 ±30°）头会明显探出肩膀 —— 这是真实 3D 几何
- 串口独占：模组运行时不能同时用 `mcstream.py`
- 高清皮肤只存在 RAM，**板子复位后**会退回内置小图

---

## 许可

代码以 [MIT](LICENSE) 发布。`mods/` 里的 jar 内嵌
[jSerialComm](https://fazecast.github.io/jSerialComm/)（LGPL-3.0 / Apache-2.0 双许可）。

Minecraft 及相关素材版权归 Mojang / Microsoft 所有，本项目与它们无关。
仓库不附带任何第三方模型或工具软件。

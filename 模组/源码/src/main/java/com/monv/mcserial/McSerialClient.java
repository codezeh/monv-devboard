package com.monv.mcserial;

import com.fazecast.jSerialComm.SerialPort;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.util.math.Vec3d;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * MCSerial —— 把玩家状态 + 头部姿态（左右 + 俯仰）送到 F407 半身像屏。
 *
 * 架构（v4，2026-10-30）：
 *
 *   渲染线程(END_CLIENT_TICK) ──只写 volatile 字段──> 发送线程 ──串口──> 板子
 *
 *   板子上头和身体是两层：
 *     · 身体：Flash 里 7 状态 x 8 帧，本地 30fps 播放
 *     · 头  ：Flash 里 13(左右) x 5(俯仰) 张姿态图，按命令即时切换
 *   模组只发 2 字节的状态 + 2 字节左右 + 2 字节俯仰，"头在转/在抬"和
 *   "身体在动"可以同时发生，带宽基本为零。
 *
 *   串口协议（对应固件 bsp_skin.c 的 Skin_FeedStream）：
 *     'S' + 命令字   状态：SI/SW/SH/SJ/SA/SZ/SR/SK/SF
 *     'H' + 档位     左右：0..12（-60..+60，10 度一档，6 = 正前方）
 *     'V' + 档位     俯仰：0..4 （-30..+30，15 度一档，2 = 平视）
 *     'D' / 'C'      整帧推流（旧机制，留给 mcstream.py 推皮肤）
 *
 *   两个轴的信号来源不一样，这点很关键：
 *     · 俯仰 = player.getPitch() 直接用。相机俯仰本来就是绝对角，
 *       抬头就抬着、低头就低着，天然稳定。
 *     · 左右 = 视角 yaw 的增量累积 + 缓慢回中。因为原版里身体会跟着视角转
 *       （turnHead() 每 tick 把 bodyYaw 往 headYaw 拉 0.3），拿不到绝对左右参考。
 */
public class McSerialClient implements ClientModInitializer {
    public static final Logger LOG = LoggerFactory.getLogger("mcserial");

    /* ================= 串口 / 发送线程 ================= */
    private static SerialPort port = null;
    private static volatile boolean opened = false;
    private volatile boolean running = true;

    /* 渲染线程 -> 发送线程（volatile 足够，无需锁） */
    private volatile String wantState = null;
    private volatile int    wantYaw   = YAW_MID;
    private volatile int    wantTilt  = TILT_MID;

    private String sentState = null;
    private int    sentYaw   = -1;
    private int    sentTilt  = -1;

    /* ---- 头部档位（必须与 tools/gen_anim_c.py / skin_head.h 一致） ---- */
    private static final int YAW_COUNT = 13;   /* -60..+60 每 10 度 */
    private static final int YAW_STEP  = 10;
    private static final int YAW_MIN   = -60;
    private static final int YAW_MID   = 6;    /* 正前方 */

    private static final int TILT_COUNT = 5;   /* -30..+30 每 15 度 */
    private static final int TILT_STEP  = 15;
    private static final int TILT_MIN   = -30;
    private static final int TILT_MID   = 2;   /* 平视 */

    /* ================= 左右信号 ================= */
    private float lastCamYaw = Float.NaN;
    private float headYawDeg = 0f;
    private long  lastYawMs  = 0;

    private static final float YAW_LIMIT    = 60f;
    private static final float DECAY_MS     = 2500f;
    private static final float DEADBAND_DEG = 4f;

    /* ================= 状态判定 ================= */
    private float lastHealth = -1f;
    private long  lastHurtMs = 0;
    private boolean wasPaused = false;

    /* ================= ACK 统计（诊断用） ================= */
    private int ackHead = 0;

    @Override
    public void onInitializeClient() {
        LOG.info("[mcserial] 初始化（头/身分层 + 左右俯仰 v4）");

        Thread t = new Thread(this::senderLoop, "mcserial-sender");
        t.setDaemon(true);
        t.start();

        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            try {
                tick(client);
            } catch (Throwable thr) {
                LOG.debug("[mcserial] tick 异常", thr);
            }
        });
    }

    /* ==================================================================
     * 渲染线程：只算，不碰串口
     * ================================================================== */
    private void tick(MinecraftClient client) {
        if (client.isPaused()) {
            if (!wasPaused) {
                wantState = "SI";
                wasPaused = true;
            }
            return;
        }
        wasPaused = false;

        ClientPlayerEntity player = client.player;
        if (player == null) return;

        wantState = judge(player);
        updateYaw(player);
        updateTilt(player);
    }

    /** 左右：视角增量累积 + 缓慢回中 */
    private void updateYaw(ClientPlayerEntity player) {
        long now = System.currentTimeMillis();
        long dt = (lastYawMs == 0) ? 16 : (now - lastYawMs);
        if (dt <= 0) dt = 16;
        lastYawMs = now;

        float cam = player.headYaw;               /* 本机玩家：headYaw 即视角 yaw */
        if (Float.isNaN(lastCamYaw)) lastCamYaw = cam;

        headYawDeg += wrapDegrees(cam - lastCamYaw);
        lastCamYaw = cam;
        headYawDeg *= (float) Math.exp(-(double) dt / DECAY_MS);

        if (headYawDeg >  YAW_LIMIT) headYawDeg =  YAW_LIMIT;
        if (headYawDeg < -YAW_LIMIT) headYawDeg = -YAW_LIMIT;
        if (Math.abs(headYawDeg) < DEADBAND_DEG) headYawDeg = 0f;

        int deg = Math.round(headYawDeg / (float) YAW_STEP) * YAW_STEP;
        int idx = Math.round((deg - YAW_MIN) / (float) YAW_STEP);
        if (idx < 0)           idx = 0;
        if (idx >= YAW_COUNT)  idx = YAW_COUNT - 1;
        wantYaw = idx;
    }

    /** 俯仰：直接用相机 pitch（绝对角）。MC 里 pitch 正 = 低头，固件 rx 负 = 低头 */
    private void updateTilt(ClientPlayerEntity player) {
        float rx = -player.getPitch();            /* 转成固件的 Head.rx 语义 */
        if (rx >  30f) rx =  30f;
        if (rx < -30f) rx = -30f;

        int idx = Math.round((rx - TILT_MIN) / (float) TILT_STEP);
        if (idx < 0)            idx = 0;
        if (idx >= TILT_COUNT)  idx = TILT_COUNT - 1;
        wantTilt = idx;
    }

    private static float wrapDegrees(float d) {
        d = d % 360.0f;
        if (d >= 180.0f)  d -= 360.0f;
        if (d < -180.0f)  d += 360.0f;
        return d;
    }

    /* ==================================================================
     * 发送线程：唯一碰串口的地方
     * ================================================================== */
    private void senderLoop() {
        while (running) {
            try {
                if (!opened || port == null || !port.isOpen()) {
                    openPort();
                    Thread.sleep(200);
                    continue;
                }

                String st = wantState;
                if (st != null && !st.equals(sentState)) {
                    if (write(stateCmd(st).getBytes())) sentState = st;
                }

                int y = wantYaw;
                if (y != sentYaw) {
                    if (write(new byte[]{'H', (byte) y})) sentYaw = y;
                }

                int v = wantTilt;
                if (v != sentTilt) {
                    if (write(new byte[]{'V', (byte) v})) sentTilt = v;
                }

                drainAcks();
                Thread.sleep(8);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            } catch (Throwable t) {
                LOG.debug("[mcserial] 发送线程异常", t);
                sleepQuiet(100);
            }
        }
    }

    private void drainAcks() {
        try {
            byte[] tmp = new byte[128];
            for (int i = 0; i < 4; i++) {
                int n = port.readBytes(tmp, tmp.length);
                if (n <= 0) break;
                for (int k = 0; k < n; k++) {
                    if (tmp[k] == 'h' || tmp[k] == 'v' || tmp[k] == 'K') ackHead++;
                }
            }
        } catch (Throwable ignored) {
        }
    }

    private boolean write(byte[] data) {
        try {
            return port.writeBytes(data, data.length) == data.length;
        } catch (Throwable t) {
            LOG.debug("[mcserial] 写串口失败", t);
            return false;
        }
    }

    private static void sleepQuiet(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /* ==================================================================
     * 打开串口（在发送线程里做，getCommPorts 在 Windows 上很慢）
     * ================================================================== */
    private long lastOpenTry = 0;

    private void openPort() {
        long now = System.currentTimeMillis();
        if (now - lastOpenTry < 5000) return;
        lastOpenTry = now;

        try {
            SerialPort[] ports = SerialPort.getCommPorts();
            if (ports.length == 0) {
                LOG.warn("[mcserial] 没找到串口，5 秒后重试");
                return;
            }

            SerialPort chosen = null;
            for (SerialPort p : ports) {
                if ("COM5".equalsIgnoreCase(p.getSystemPortName())) { chosen = p; break; }
            }
            if (chosen == null) {
                for (SerialPort p : ports) {
                    String d = p.getDescriptivePortName();
                    if (d != null && (d.contains("CMSIS") || d.contains("USB"))) { chosen = p; break; }
                }
            }
            if (chosen == null) chosen = ports[0];

            chosen.setBaudRate(921600);
            chosen.setNumDataBits(8);
            chosen.setNumStopBits(SerialPort.ONE_STOP_BIT);
            chosen.setParity(SerialPort.NO_PARITY);
            chosen.setComPortTimeouts(SerialPort.TIMEOUT_WRITE_BLOCKING, 0, 0);

            if (chosen.openPort()) {
                port = chosen;
                opened = true;
                sentState = null;
                sentYaw = -1;
                sentTilt = -1;
                LOG.info("[mcserial] 串口已打开: {} ({})",
                         chosen.getSystemPortName(), chosen.getDescriptivePortName());
                sleepQuiet(400);
                write(new byte[]{'S', 'F'});      /* 上电/复位后先回本地动画 */
                sentState = null;
            } else {
                LOG.warn("[mcserial] 打开 {} 失败，5 秒后重试", chosen.getSystemPortName());
            }
        } catch (Throwable t) {
            LOG.warn("[mcserial] 打开串口异常", t);
        }
    }

    /* ==================================================================
     * 状态判定（阈值沿用之前实测校准的结果）
     * ================================================================== */
    private String judge(ClientPlayerEntity player) {
        long now = System.currentTimeMillis();

        float hp = player.getHealth();
        if (lastHealth >= 0 && hp < lastHealth - 0.05f) lastHurtMs = now;
        lastHealth = hp;
        if (hp <= 0.0f) return "HURT";
        if ((now - lastHurtMs) < 800) return "HURT";

        if (player.isSleeping()) return "SLEEP";
        if (player.isSneaking()) return "SNEAK";
        if (!player.isOnGround() && !player.isTouchingWater()) return "JUMP";
        if (player.handSwinging && !player.isUsingItem()) return "ATTACK";

        Vec3d v = player.getVelocity();
        double horiz = Math.sqrt(v.x * v.x + v.z * v.z);
        if (horiz > 0.08) return player.isSprinting() ? "RUN" : "WALK";

        return "IDLE";
    }

    private static String stateCmd(String state) {
        return switch (state) {
            case "WALK"   -> "SW";
            case "RUN"    -> "SR";
            case "HURT"   -> "SH";
            case "JUMP"   -> "SJ";
            case "ATTACK" -> "SA";
            case "SLEEP"  -> "SZ";
            case "SNEAK"  -> "SK";
            default       -> "SI";
        };
    }
}

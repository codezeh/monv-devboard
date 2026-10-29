// ============================================================
//  mc_state.sc —— 把玩家状态通过聊天栏/日志输出给外部程序
//
//  【为什么用 print 而不是 write_file】
//  实测 26.3：write_file 会导致 "Callback failed"（函数存在但运行期失败），
//  而 print() 的输出已确认会进入 latest.log：
//      [17:30:52] [Render thread/INFO]: [System] [CHAT] xxx
//  所以改走日志通道，这条路已验证可用。
//
//  为避免刷屏，**只在状态变化时**才输出一行。
//
//  安装：
//    .minecraft/versions/<版本>/config/carpet/scripts/mc_state.sc
//  启用：
//    /script load mc_state
//  停用：
//    /script unload mc_state
//
//  输出格式（PC 端 tools/mcbridge.py --source log 解析）：
//    MCSTATE WALK 18.5 0.132
// ============================================================

global_tick = 0;
global_hp = -1;
global_hurt_at = -9999;
global_last = '';
global_jump_n = 0;      // 连续满足跳跃条件的次数

__on_tick() -> (
    global_tick = global_tick + 1;
    if (global_tick % 4, return(null));       // 每 4 tick 检查一次（约 5Hz）

    p = player();
    if (!p, return(null));                    // 26.3 实测：player() 直接返回 entity

    // ---- 血量 ----
    hp = query(p, 'health');
    if (!hp, hp = 0);

    // ---- 速度 ----
    mv = query(p, 'motion');
    spd = if (mv, sqrt(mv:0 * mv:0 + mv:2 * mv:2), 0);
    vy  = if (mv, mv:1, 0);

    // ---- 掉血 → 受伤（约 1 秒内保持）----
    if (global_hp >= 0 && hp < global_hp - 0.05, global_hurt_at = global_tick);
    global_hp = hp;
    hurt_recent = (global_tick - global_hurt_at) < 20;

    // ---- 跳跃判定：必须连续满足，滤掉站立时的瞬时抖动 ----
    // 用"连续上升"判断跳跃：vy 每 tick 都 > 0.20 且连续 3 次（约 0.6 秒）
    // 才认定真的起跳。站立时 vy 的单次抖动撑不过 3 次。
    if (vy > 0.20,
        global_jump_n = global_jump_n + 1,
        global_jump_n = 0
    );

    // 优先级：受伤 > 移动 > 跳跃 > 待机
    //   WALK 要先判：走路水平速度 0.12~0.17，若先判跳跃会误判
    st = if (hp <= 0,                'HURT',
         if (hurt_recent,            'HURT',
         if (spd > 0.08,             'WALK',
         if (global_jump_n >= 3,     'JUMP',
                                     'IDLE'))));

    // ---- 只在变化时输出，避免刷屏 ----
    if (st != global_last,
        print(str('MCSTATE %s %f %f', st, hp, spd));
        global_last = st;
    );
);

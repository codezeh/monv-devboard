// ============================================================
//  probe.sc —— 探测 scarpet 里哪些写法可用（一次性诊断用）
//
//  用法：游戏内  /script load probe
//  然后看聊天栏输出，或看日志里的 PROBE 行
//
//  它会逐个测试，用 try 包住，失败不中断
// ============================================================

global_n = 0;

__on_tick() -> (
    // 只在进入世界后跑一次
    if (global_n > 0, return(null));

    ps = player();
    if (!ps, return(null));       // 还没进世界
    global_n = 1;

    print('=== PROBE START ===');

    // ---- 1) player() 返回什么 ----
    print(str('player() -> %s  type=%s', ps, type(ps)));
    pn = ps:0;
    print(str('ps:0 -> %s  type=%s', pn, type(pn)));

    // ---- 2) 各种"把名字变实体"的写法 ----
    //  注意：这里故意不用 try（scarpet 没有 try/catch），
    //  所以每项单独放到独立 app 里测，见下方说明。
    //  本文件只做不会报错的探测。

    // ---- 3) 已知可用的全局函数探测 ----
    print(str('query(ps,health) -> %s', query(ps, 'health')));

    print('=== PROBE END ===');
    global_n = 2;
);

@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  游戏联动 —— 板上小人跟随你的 Minecraft 状态
REM
REM  本程序会：
REM    1. 打开串口（这一步可能让板子复位，属正常）
REM    2. 自动推送高清皮肤（所以不会退回初始小图）
REM    3. 开始监听游戏日志，实时转发状态
REM
REM  用法：双击本文件，窗口保持开着，然后去玩游戏。
REM        走动→摇摆   被打→变红   跳→上移   不动→待机
REM
REM  停止：Ctrl+C 或关闭窗口
REM
REM  前提：
REM    · 板子插着
REM    · 游戏里执行过   /script load mc_state
REM ============================================================

set PY=C:\Users\zeh\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe

echo.
echo  ============================================================
echo   游戏联动
echo  ============================================================
echo.
echo   会先自动推送皮肤，再开始跟随游戏状态。
echo   窗口别关，按 Ctrl+C 停止。
echo.

"%PY%" "%~dp0tools\mcbridge.py" --source log --auto-log --skin skin_user.png --preset hd --push-arms slim -p COM5

echo.
echo   已停止。
echo   若要再次联动，重新双击本文件即可。
pause

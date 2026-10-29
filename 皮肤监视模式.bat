@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  皮肤监视模式 —— 启动后，把任意皮肤 PNG 丢进 skins 文件夹
REM  就会自动渲染并推送到板子，不用再敲命令。
REM  Ctrl+C 退出。
REM ============================================================

set PY=C:\Users\zeh\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
set TOOL=%~dp0tools\mcstream.py
set SKINS=%~dp0skins

if not exist "%SKINS%" mkdir "%SKINS%"

echo.
echo   监视文件夹: %SKINS%
echo   把皮肤 PNG 丢进去就会自动推送。Ctrl+C 退出。
echo.

"%PY%" "%TOOL%" --watch "%SKINS%" --preset hd

pause

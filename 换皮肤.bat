@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  拖拽换皮肤 —— 把任意 Minecraft 皮肤 PNG 拖到这个 bat 文件上
REM  就自动渲染并推送到板子。不需要开命令行，也不需要问任何人。
REM ============================================================

set PY=C:\Users\zeh\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
set TOOL=%~dp0tools\mcstream.py

if "%~1"=="" (
    echo.
    echo   把一张 Minecraft 皮肤 PNG 拖到本文件上即可。
    echo.
    echo   可选：编辑本文件，修改 PRESET 换预设
    echo         pixel = 像素块更粗   hd = 当前默认   full = 最清晰
    echo.
    pause
    exit /b
)

set PRESET=hd

echo.
echo   皮肤: %~nx1
echo   预设: %PRESET%
echo.

"%PY%" "%TOOL%" "%~1" --preset %PRESET%

echo.
echo   完成。按任意键关闭。
pause >nul

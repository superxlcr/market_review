@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo   清理缓存 & 数据
echo ========================================
echo.

REM ── 1. Kill Streamlit / Python processes ──
echo [1/4] 终止 Python 进程...
taskkill /f /im streamlit.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo       完成
echo.

REM ── 2. Delete database ──
echo [2/4] 删除数据库...
if exist "%~dp0data\marketreview.db" (
    del /q "%~dp0data\marketreview.db"
    echo       已删除 data\marketreview.db
) else (
    echo       (数据库不存在，跳过)
)
echo.

REM ── 3. Clear __pycache__ ──
echo [3/4] 清理 __pycache__...
for /d /r "%~dp0dashboard" %%d in (__pycache__) do (
    if exist "%%d" (
        rmdir /s /q "%%d"
        echo       %%d
    )
)
for /d /r "%~dp0src" %%d in (__pycache__) do (
    if exist "%%d" (
        rmdir /s /q "%%d"
        echo       %%d
    )
)
echo       完成
echo.

REM ── 4. Clear Streamlit browser cache ──
echo [4/4] 清理 Streamlit 缓存...
if exist "%~dp0.streamlit" (
    del /q "%~dp0.streamlit\*" 2>nul
    echo       已清理 .streamlit\
) else (
    echo       (.streamlit 目录不存在，跳过)
)
echo       完成
echo.

echo ========================================
echo   清理完毕！
echo ========================================
echo.
echo   接下来: 运行 start-dashboard.bat 启动
echo   然后在控制台应用日期拉取数据
echo.
pause

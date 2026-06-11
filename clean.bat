@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo   清理缓存（保留数据库）
echo ========================================
echo.
echo   注意：数据库不会被删除！
echo   如需重建数据库，请手动删除：
echo     data\marketreview.db
echo   （仅在 schema 变更或数据被污染时才需要）
echo.

REM ── 1. Kill Streamlit / Python processes ──
echo [1/3] 终止 Python 进程...
taskkill /f /im streamlit.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo       完成
echo.

REM ── 2. Clear __pycache__ ──
echo [2/3] 清理 __pycache__...
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

REM ── 3. Clear Streamlit browser cache ──
echo [3/3] 清理 Streamlit 缓存...
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
echo.
pause

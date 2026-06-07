@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   A股复盘 Dashboard — Agent 1 大盘分析
echo ============================================
echo.

REM Activate venv
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo [ERROR] .venv not found, please run: uv sync
    pause
    exit /b 1
)

REM Clear bytecode cache
for /d /r . %%i in (__pycache__) do @if exist "%%i" rd /s /q "%%i" 2>nul

echo Starting Dashboard on http://localhost:8501
echo Press Ctrl+C to stop.
echo.

python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true

pause

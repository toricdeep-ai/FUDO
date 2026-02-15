@echo off
echo ========================================
echo   FUDO - Streamlit + Cloudflare Tunnel
echo ========================================
echo.

REM --- check cloudflared ---
where cloudflared >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] cloudflared not found.
    echo   winget install cloudflare.cloudflared
    pause
    exit /b 1
)

echo [1/2] Starting Streamlit...
start "FUDO-Streamlit" cmd /c "cd /d %~dp0 && python -m streamlit run app.py"

echo   Waiting for Streamlit...
timeout /t 8 /nobreak >nul

echo   Opening browser...
explorer "http://localhost:8501"

echo.
echo [2/2] Starting Cloudflare Tunnel + LINE notify...
echo   Tunnel URL will be sent to LINE automatically.
echo   Press Ctrl+C to stop.
echo.
cd /d %~dp0
python start_tunnel.py

@echo off
setlocal
cd /d "%~dp0"

set "UVICORN=%~dp0.venv\Scripts\uvicorn.exe"
if not exist "%UVICORN%" (
    echo Could not find the virtual environment at .venv.
    echo Create it and install requirements before starting the server.
    pause
    exit /b 1
)

for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess"`) do (
    echo Solar server is already running on http://127.0.0.1:8000
    exit /b 0
)

echo Starting Solar proposal server on http://127.0.0.1:8000
start "Solar Proposal Server" cmd /k ""%UVICORN%" app.main:app --host 127.0.0.1 --port 8000"
endlocal

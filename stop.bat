@echo off
setlocal

for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess"`) do (
    echo Stopping Solar server process %%P...
    powershell -NoProfile -Command "Stop-Process -Id %%P -Force"
)

echo Solar server stopped, or it was not running.
endlocal

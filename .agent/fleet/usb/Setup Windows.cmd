@echo off
rem Double-click to set up this Windows machine. It asks for administrator rights, then runs setup-windows.ps1
rem from this drive and keeps the window open until a key is pressed.
net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"
echo.
pause

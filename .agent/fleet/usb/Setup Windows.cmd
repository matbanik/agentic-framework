@echo off
rem Double-click to set up this Windows machine. It runs setup-windows.ps1 from this drive in this window, signed in
rem as the account the agent will use. The script asks for administrator rights itself, so the drive gets a record
rem even when the prompt is cancelled. The window stays open until a key is pressed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"
echo.
pause

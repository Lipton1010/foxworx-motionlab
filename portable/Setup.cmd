@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0portable\Setup.ps1"
if errorlevel 1 pause

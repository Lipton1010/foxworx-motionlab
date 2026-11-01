@echo off
if not exist "%~dp0app\Image Studio.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build Desktop.ps1"
  if errorlevel 1 (pause & exit /b 1)
)
start "" "%~dp0app\Image Studio.exe"

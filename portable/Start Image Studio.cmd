@echo off
if not exist "%~dp0app\Image Studio.exe" (
  echo Image Studio is missing. Extract the portable package again.
  pause
  exit /b 1
)
if not exist "%~dp0runtime\ComfyUI_windows_portable\python_embeded\python.exe" (
  call "%~dp0Setup.cmd"
  if not exist "%~dp0runtime\ComfyUI_windows_portable\python_embeded\python.exe" exit /b 1
)
start "" "%~dp0app\Image Studio.exe"

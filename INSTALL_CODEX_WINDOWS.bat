@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m pip install openai-codex==0.163.0
if errorlevel 1 (
  echo Failed installing Codex SDK. Check Python and network.
  pause
  exit /b 1
)
echo Codex Python SDK installed. Launch START_WINDOWS.bat and use ChatGPT sign-in.
pause

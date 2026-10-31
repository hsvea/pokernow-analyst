@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if NOT %ERRORLEVEL% EQU 0 (
  echo Install Python from https://python.org/downloads/windows/
  pause
  exit /b 1
)
echo Installing PyInstaller locally for EXE creation...
py -3 -m pip install pyinstaller==6.16.0 openai-codex==0.163.0
if ERRORLEVEL 1 (
  echo Could not install PyInstaller.
  pause
  exit /b 1
)
py -3 build_release.py
if ERRORLEVEL 1 (
  echo EXE build failed.
  pause
  exit /b 1
)
echo.
echo Ready: release\PokerNowAnalyst-Windows.zip
pause

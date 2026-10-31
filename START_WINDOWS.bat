@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    py -3 app.py
    goto finished
)
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python app.py
    goto finished
)
echo.
echo Python 3.10+ не найден. Установите Python с https://www.python.org/downloads/windows/
echo При установке включите "Add python.exe to PATH".
:finished
if NOT %ERRORLEVEL% EQU 0 pause

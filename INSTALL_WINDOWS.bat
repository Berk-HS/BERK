@echo off
setlocal
cd /d "%~dp0"
echo ================================================
echo   HighschoolRP CrowBot - Windows Installation
echo ================================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.12 from python.org.
  pause
  exit /b 1
)
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installation failed. Check your internet connection and Python installation.
  pause
  exit /b 1
)
if not exist .env copy .env.example .env >nul
echo.
echo Setup file: .env
echo Paste your DISCORD_TOKEN and DISCORD_GUILD_ID into this file.
start "" notepad .env
echo After saving .env, run START_WINDOWS.bat.
pause

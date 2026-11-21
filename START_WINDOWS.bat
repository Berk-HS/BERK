@echo off
setlocal
cd /d "%~dp0"
if not exist .env (
  echo Missing .env file. Run INSTALL_WINDOWS.bat first.
  pause
  exit /b 1
)
echo Starting HighschoolRP CrowBot...
py bot.py
echo.
echo The bot is no longer running. Review the error above.
pause

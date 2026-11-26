@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo ERROR: Storyroom's existing .venv is missing. Use the normal launcher first.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" "tools\storyroom_release_preflight.py"
set "SR_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %SR_EXIT%

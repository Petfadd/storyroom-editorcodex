@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "STORYROOM_VERIFIED_PORT=8004"
echo ========================================
echo STORYROOM - AUDITED DOCUMENTARY EDITOR (8004)
echo Launch URL: http://127.0.0.1:8004
echo ========================================
echo.
if not exist ".venv\Scripts\python.exe" (
 echo First-run setup is needed in THIS editor folder.
 echo This installs app dependencies locally, not system-wide.
 echo.
 where py >nul 2>&1
 if errorlevel 1 (
   echo ERROR: Python launcher was not found. Install Python 3.11 or 3.12.
   pause
   exit /b 1
 )
 py -3.11 -m venv .venv
 if errorlevel 1 py -3.12 -m venv .venv
 if not exist ".venv\Scripts\python.exe" (
   echo ERROR: Could not create local Python environment.
   pause
   exit /b 1
 )
 echo Installing dependencies. Internet may be required the first time.
 ".venv\Scripts\python.exe" -m pip install -r requirements.txt -c requirements-constraints.txt
 if errorlevel 1 (
   echo ERROR: Dependency installation failed. Read the messages above.
   pause
   exit /b 1
 )
)
".venv\Scripts\python.exe" verified_launch.py
set "END_CODE=%ERRORLEVEL%"
if not "%END_CODE%"=="0" (
 echo.
 echo Storyroom could not start. Review the error above.
 pause
)
exit /b %END_CODE%

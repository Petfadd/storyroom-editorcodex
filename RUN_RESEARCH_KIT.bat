@echo off
title Storyroom research kit
setlocal
set "EDITOR=%USERPROFILE%\Desktop\storyroom-editor-main"
set "DL=%USERPROFILE%\Downloads"

echo.
echo  Storyroom research kit - downloads the videos and makes the research pack.
echo  Leave this window open until it says DONE.
echo.

if not exist "%EDITOR%\app.py" (
  echo  Could not find the editor at %EDITOR%
  pause & exit /b
)

rem The newest storyroom_kit.py in Downloads replaces the one in the editor folder.
for /f "delims=" %%F in ('dir /b /o-d "%DL%\storyroom_kit*.py" 2^>nul') do (
  copy /y "%DL%\%%F" "%EDITOR%\storyroom_kit.py" >nul & goto :kit_ok
)
:kit_ok
if not exist "%EDITOR%\storyroom_kit.py" (
  echo  storyroom_kit.py is not in Downloads. Download it from the chat first.
  pause & exit /b
)

rem The sheet: the file dropped onto this .bat, else the newest *footage_sheet*.md or SHEET*.md in Downloads.
set "SHEET="
if not "%~1"=="" (
  copy /y "%~1" "%EDITOR%\%~nx1" >nul
  set "SHEET=%~nx1" & goto :sheet_copied
)
for /f "delims=" %%F in ('dir /b /o-d "%DL%\SHEET*.md" 2^>nul') do (
  set "SHEET=%%F" & goto :sheet_ok
)
for /f "delims=" %%F in ('dir /b /o-d "%DL%\*footage_sheet*.md" 2^>nul') do (
  set "SHEET=%%F" & goto :sheet_ok
)
:sheet_ok
if not defined SHEET (
  echo  No footage sheet found in Downloads. Download the footage sheet from the agent first, or drag it onto this file.
  pause & exit /b
)
copy /y "%DL%\%SHEET%" "%EDITOR%\%SHEET%" >nul
:sheet_copied
echo  Footage sheet: %SHEET%
echo.

cd /d "%EDITOR%"
python storyroom_kit.py run "%SHEET%" --out work
findstr /c:"confirm you" "work\logs\fetch.log" >nul 2>&1 && (
  echo.
  echo  YouTube asked to sign in. Trying again with your Chrome sign-in - close Chrome now, then press a key.
  pause
  python storyroom_kit.py run "%SHEET%" --out work --cookies-from-browser chrome
)

echo.
echo  ============================================================
echo   DONE. Upload to the agent:
echo     work_research_pack.md
echo     every picture in the work_pictures folder
echo  ============================================================
explorer "%EDITOR%\work_pictures"
explorer /select,"%EDITOR%\work_research_pack.md"
pause

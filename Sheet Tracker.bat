@echo off
rem Opens the weekly timesheet check. Keep this file in the Sheet Tracker folder (a Desktop shortcut to it is fine).
setlocal
set "HOME_DIR=%~dp0"
if not exist "%HOME_DIR%tool\app.pyw" goto missing
where pythonw >nul 2>nul
if errorlevel 1 goto console
start "" pythonw "%HOME_DIR%tool\app.pyw"
exit /b 0

:console
python "%HOME_DIR%tool\app.pyw"
if errorlevel 1 pause
exit /b

:missing
echo.
echo   Can't find tool\app.pyw next to this file.
echo   Keep "Sheet Tracker.bat" in the Sheet Tracker folder and make a shortcut to it instead.
echo.
pause
exit /b 1

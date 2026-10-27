@echo off
setlocal DisableDelayedExpansion
title AgentOS
pushd "%~dp0"
if errorlevel 1 goto folder_error

if exist ".venv\Scripts\python.exe" goto local_python
where py >nul 2>nul
if not errorlevel 1 goto python_launcher
where python >nul 2>nul
if not errorlevel 1 goto path_python
echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/
echo Then double-click start.bat again.
goto failed

:local_python
".venv\Scripts\python.exe" "scripts\start-local.py" %*
goto finished

:python_launcher
py -3 "scripts\start-local.py" %*
goto finished

:path_python
python "scripts\start-local.py" %*
goto finished

:finished
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo.
echo AgentOS did not start. See the message above.
popd
pause
exit /b 1

:folder_error
echo Could not open the AgentOS folder.
pause
exit /b 1

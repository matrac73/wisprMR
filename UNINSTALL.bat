@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   Wispr MR - UNINSTALL
echo ============================================================
echo.

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" "%~dp0UNINSTALL.py" %*
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% NEQ 0 (
    echo Desinstallation interrompue ^(code %EXITCODE%^).
) else (
    echo Desinstallation terminee.
)
echo.
pause
exit /b %EXITCODE%

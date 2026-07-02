@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   Wispr MR - INSTALL
echo ============================================================
echo.

REM Windows bootstrap: setup.ps1 can install Python 3.11 if needed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Profile balanced -Launch %*
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% NEQ 0 (
    echo Installation interrompue ^(code %EXITCODE%^).
) else (
    echo Installation terminee.
)
echo.
pause
exit /b %EXITCODE%

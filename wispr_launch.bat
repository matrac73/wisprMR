@echo off
REM Lanceur Wispr MR — utilisé par le Planificateur de tâches Windows.
REM Sans "start" : cmd.exe reste vivant tant que pythonw tourne.
REM Task Scheduler peut ainsi détecter les crashes et relancer.

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

cd /d "%~dp0"
"%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" --profile fast

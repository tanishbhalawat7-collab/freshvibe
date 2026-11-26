@echo off
REM Start Fresh Vibe (Windows). First run creates .venv and installs deps.
cd /d "%~dp0\.."
if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
if not exist .env copy .env.example .env
cd backend
..\.venv\Scripts\python -m app

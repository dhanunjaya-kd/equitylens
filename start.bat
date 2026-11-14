@echo off
REM EquityLens one-click start (Windows). First run sets everything up.
cd /d "%~dp0backend"
if not exist venv (
  echo Creating Python environment...
  py -3.11 -m venv venv 2>nul || python -m venv venv
)
call venv\Scripts\activate
pip install -q -r requirements.txt
start "" http://localhost:8600
python run.py

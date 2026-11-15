@echo off
REM EquityLens start with a console window (shows the log live).
REM For no window at all, double-click EquityLens.vbs instead.
REM   start.bat setup  = only create the environment and install packages
cd /d "%~dp0backend"
if not exist venv\Scripts\python.exe (
  echo Creating Python environment...
  py -3.11 -m venv venv 2>nul || python -m venv venv
)
if not exist venv\Scripts\python.exe (
  echo.
  echo Python was not found. Install Python 3.11 or newer from python.org
  echo and tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)
fc /b requirements.txt venv\eql_req.txt >nul 2>&1 || (
  echo Installing packages, 1 to 3 minutes...
  venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || (
    echo.
    echo Package install failed. Check the internet connection and run start.bat again.
    pause
    exit /b 1
  )
  copy /y requirements.txt venv\eql_req.txt >nul
)
if /i "%~1"=="setup" exit /b 0
start "" http://localhost:8600
venv\Scripts\python.exe run.py

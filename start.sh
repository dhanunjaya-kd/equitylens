#!/usr/bin/env bash
# EquityLens start (Mac/Linux/server)
cd "$(dirname "$0")/backend"
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
python run.py

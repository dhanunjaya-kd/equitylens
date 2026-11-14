"""Start EquityLens:  python run.py   then open http://localhost:8600"""
import uvicorn

from app import config

if __name__ == "__main__":
    print(f"\n  EquityLens running ->  http://localhost:{config.PORT}\n")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)

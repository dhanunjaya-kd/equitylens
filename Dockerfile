# EquityLens server image: docker compose up -d   (see docs/CLOUD_AND_PHONE.md)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EQL_HOST=0.0.0.0 EQL_PORT=8600 TZ=Asia/Kolkata
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
# keys, cache, broker logins and logs live here: keep it on a volume
VOLUME /app/backend/data
EXPOSE 8600
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('EQL_PORT','8600'),timeout=4)"
CMD ["python", "run.py"]

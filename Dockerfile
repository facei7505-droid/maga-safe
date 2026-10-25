# ПРУФ: сервер аналитика одним контейнером (FastAPI + дашборд). Строго один воркер: индексы в памяти процесса.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PRUF_DATA_DIR=/app/data/demo PRUF_MODEL_PATH=/app/models/clf.joblib \
    PRUF_LLM_MODEL=claude-sonnet-5-5 PRUF_LLM_DAILY_BUDGET=300

# OCR (rapidocr/opencv) просит libGL и glib; компилятор нужен, если для pdqhash нет готового колеса
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pruf ./pruf
COPY scripts ./scripts
COPY web ./web
COPY eval ./eval
COPY docker-entrypoint.sh ./

# Модель обучается при сборке: синтетика + ручные dev-наборы, секреты не нужны
RUN python scripts/gen_synthetic.py && PRUF_DEV_MODE=1 python scripts/train.py \
 && useradd --create-home --uid 10001 pruf && mkdir -p /app/data && chown -R pruf /app/data \
 && chmod +x docker-entrypoint.sh

USER pruf
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health')"
ENTRYPOINT ["./docker-entrypoint.sh"]

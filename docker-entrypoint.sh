#!/bin/sh
# Демо-данные (фон + кейс C-211 + журнал разведчика) создаёт сам сервер в фоне при пустой базе (pruf/demo_boot.py):
# порт открывается сразу, а сайт до готовности показывает «Демо загружается». PRUF_SEED_DEMO=0 — пустой сервер.
set -e
export PRUF_SEED_DEMO="${PRUF_SEED_DEMO:-1}"
exec python -m uvicorn pruf.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers

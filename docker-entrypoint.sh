#!/bin/sh
# Первый запуск: демо-данные (фон + кейс C-211) с тем же PRUF_HMAC_KEY, что у сервера, иначе поиск карт не сойдётся.
set -e
if [ ! -f "$PRUF_DATA_DIR/pruf.db" ]; then
  echo "демо-данных нет, создаю в $PRUF_DATA_DIR (несколько минут)"
  python scripts/seed_demo.py --reset
fi
exec python -m uvicorn pruf.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers

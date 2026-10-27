#!/usr/bin/env bash
# Единый запуск Hackathon Command Center (Git Bash / sh).
# Ставит зависимости при первом запуске, затем поднимает backend и frontend.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/Scripts/python.exe"

if [ ! -f "$PY" ]; then
  echo "[1/3] Создание venv и установка бэкенда..."
  python -m venv "$ROOT/.venv"
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r "$ROOT/backend/requirements.txt"
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "[2/3] Установка фронтенда (npm install)..."
  (cd "$ROOT/frontend" && npm install)
fi

echo "[3/3] Запуск серверов..."
echo "  Frontend: http://localhost:5173  <- открой это"
echo "  Backend : http://127.0.0.1:8000"
echo "  Логин   : admin / change-me"
echo ""

(cd "$ROOT/backend" && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
(cd "$ROOT/frontend" && npm run dev) &

echo "Серверы запущены. Остановка: Ctrl+C здесь."
wait

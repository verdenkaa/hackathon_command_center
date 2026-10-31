#!/usr/bin/env bash
# Локальная панель. Docker Engine работает отдельно от браузера.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.control/venv-linux/bin/python"

if [ ! -f "$PY" ]; then
  python3 -m venv "$ROOT/.control/venv-linux"
fi

"$PY" -m pip install --disable-pip-version-check -q -r "$ROOT/control/requirements.lock"
cd "$ROOT"
exec "$PY" -m control

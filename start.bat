@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [1/3] Creating venv and installing backend...
  python -m venv "%ROOT%.venv"
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r "%ROOT%backend\requirements.txt"
)

if not exist "%ROOT%frontend\node_modules" (
  echo [2/3] Installing frontend...
  pushd "%ROOT%frontend"
  call npm install
  popd
)

echo [3/3] Starting servers...
echo   Frontend: http://localhost:5173  ^<- open this
echo   Backend : http://127.0.0.1:8000
echo   Login   : admin / change-me
echo.

start "HCC Backend" /D "%ROOT%backend" cmd /k "%PY% -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "HCC Frontend" /D "%ROOT%frontend" cmd /k "npm run dev"

echo Servers started in two windows. Close them to stop.
endlocal

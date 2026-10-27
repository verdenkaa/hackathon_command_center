# Единый запуск Hackathon Command Center (Windows)
# Ставит зависимости при первом запуске, затем поднимает backend и frontend.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host "[1/3] Создание venv и установка бэкенда..." -ForegroundColor Cyan
    python -m venv "$root\.venv"
    & $py -m pip install --upgrade pip
    & $py -m pip install -r "$root\backend\requirements.txt"
}

if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "[2/3] Установка фронтенда (npm install)..." -ForegroundColor Cyan
    Push-Location "$root\frontend"
    npm install
    Pop-Location
}

Write-Host "[3/3] Запуск серверов..." -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost:5173  <- открой это" -ForegroundColor Green
Write-Host "  Backend : http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  Логин   : admin / change-me`n" -ForegroundColor Green

$backend = Start-Process -FilePath $py `
    -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' `
    -WorkingDirectory "$root\backend" -PassThru

$frontend = Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/k','npm run dev' `
    -WorkingDirectory "$root\frontend" -PassThru

Write-Host "Серверы запущены. Остановка: закрой оба окна (backend/frontend)." -ForegroundColor Yellow

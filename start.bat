@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.control\venv-windows\Scripts\python.exe"

if not exist "%PY%" (
  echo Creating local dashboard environment...
  python -m venv "%ROOT%.control\venv-windows"
  if errorlevel 1 goto :failed
)

"%PY%" -m pip install --disable-pip-version-check -q -r "%ROOT%control\requirements.lock"
if errorlevel 1 goto :failed
pushd "%ROOT%"
"%PY%" -m control
popd
endlocal
exit /b 0
:failed
echo Dashboard setup failed. Check Python 3.12+ and internet access.
pause
exit /b 1

@echo off
setlocal EnableExtensions

pushd "%~dp0" >nul || (
  echo Cannot open the KOMI Report V5 project folder.
  pause
  exit /b 1
)

set "PROJECT_ROOT=%CD%"
set "SOURCE_ROOT=%PROJECT_ROOT%\source"
set "WEB_SOURCE=%PROJECT_ROOT%\web"
set "PYTHON_BIN=%LOCALAPPDATA%\KOMI Report V5\runtime-windows\Scripts\python.exe"
set "WEB_RUNTIME=%LOCALAPPDATA%\KOMI Report V5\web-runtime"

call "%PROJECT_ROOT%\START_KOMI_REPORT.cmd" doctor
if errorlevel 1 goto :runtime_error

"%PYTHON_BIN%" "%SOURCE_ROOT%\tools\launch_doctor.py" web
if errorlevel 1 goto :source_error

"%PYTHON_BIN%" "%SOURCE_ROOT%\tools\prepare_web_runtime.py" --source "%WEB_SOURCE%" --runtime "%WEB_RUNTIME%" --legacy-env "%WEB_SOURCE%\.env.local"
if errorlevel 1 goto :web_error

set "KOMI_PROJECT_ROOT=%PROJECT_ROOT%"
set "KOMI_SOURCE_ROOT=%SOURCE_ROOT%"
set "PYTHONDONTWRITEBYTECODE=1"

"%PYTHON_BIN%" "%SOURCE_ROOT%\tools\run_web_servers.py" --source "%SOURCE_ROOT%" --runtime "%WEB_RUNTIME%"
set "APP_EXIT=%ERRORLEVEL%"
popd
exit /b %APP_EXIT%

:runtime_error
echo Unable to prepare the local Windows Python runtime.
goto :failed

:source_error
echo The shared Web source is incomplete or unavailable.
goto :failed

:web_error
echo Unable to prepare the local Windows Web runtime. Install Node.js LTS and try again.

:failed
pause
popd
exit /b 1

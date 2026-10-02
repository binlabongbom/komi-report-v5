@echo off
setlocal EnableExtensions

pushd "%~dp0" >nul || (
  echo Cannot open the KOMI Report V5 project folder.
  pause
  exit /b 1
)

set "PROJECT_ROOT=%CD%"
set "SOURCE_ROOT=%PROJECT_ROOT%\source"
set "RUNTIME_ROOT=%LOCALAPPDATA%\KOMI Report V5\runtime-windows"
set "PYTHON_BIN=%RUNTIME_ROOT%\Scripts\python.exe"
set "STAMP_FILE=%RUNTIME_ROOT%\.komi-dependencies.sha256"
set "LAUNCH_MODE=%~1"
if "%LAUNCH_MODE%"=="" set "LAUNCH_MODE=desktop"
if /i not "%LAUNCH_MODE%"=="desktop" if /i not "%LAUNCH_MODE%"=="doctor" if /i not "%LAUNCH_MODE%"=="lab" if /i not "%LAUNCH_MODE%"=="web" (
  echo Usage: START_KOMI_REPORT.cmd [desktop^|doctor^|lab^|web]
  popd
  exit /b 2
)

if not exist "%SOURCE_ROOT%\app.py" goto :missing_source
if not exist "%SOURCE_ROOT%\pyproject.toml" goto :missing_source

for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "$a=(Get-FileHash -Algorithm SHA256 -LiteralPath ([IO.Path]::Combine($env:SOURCE_ROOT,'pyproject.toml'))).Hash; $b=(Get-FileHash -Algorithm SHA256 -LiteralPath ([IO.Path]::Combine($env:SOURCE_ROOT,'uv.lock'))).Hash; $bytes=[Text.Encoding]::UTF8.GetBytes($a+$b); ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes))).Replace('-','').ToLowerInvariant()"`) do set "DEPENDENCY_HASH=%%H"
if not defined DEPENDENCY_HASH goto :runtime_error

set "INSTALLED_HASH="
if exist "%STAMP_FILE%" set /p INSTALLED_HASH=<"%STAMP_FILE%"

if not exist "%PYTHON_BIN%" call :bootstrap_runtime || goto :runtime_error
if /i not "%DEPENDENCY_HASH%"=="%INSTALLED_HASH%" call :sync_dependencies || goto :runtime_error

set "KOMI_PROJECT_ROOT=%PROJECT_ROOT%"
set "KOMI_SOURCE_ROOT=%SOURCE_ROOT%"
set "PYTHONDONTWRITEBYTECODE=1"

set "DOCTOR_MODE=%LAUNCH_MODE%"
if /i "%LAUNCH_MODE%"=="lab" set "DOCTOR_MODE=desktop"
if /i "%LAUNCH_MODE%"=="web" set "DOCTOR_MODE=desktop"
"%PYTHON_BIN%" "%SOURCE_ROOT%\tools\launch_doctor.py" "%DOCTOR_MODE%" || goto :source_error
if /i "%LAUNCH_MODE%"=="doctor" (
  popd
  exit /b 0
)
cd /d "%SOURCE_ROOT%"
if /i "%LAUNCH_MODE%"=="lab" (
  "%PYTHON_BIN%" "%SOURCE_ROOT%\tools\setup_lab.py"
  set "APP_EXIT=%ERRORLEVEL%"
  popd
  exit /b %APP_EXIT%
)
set "APP_ARGS="
if /i "%LAUNCH_MODE%"=="web" set "APP_ARGS=--open-web"
"%PYTHON_BIN%" "%SOURCE_ROOT%\app.py" %APP_ARGS%
set "APP_EXIT=%ERRORLEVEL%"
popd
exit /b %APP_EXIT%

:bootstrap_runtime
if not exist "%RUNTIME_ROOT%" mkdir "%RUNTIME_ROOT%"
where uv >nul 2>nul
if not errorlevel 1 (
  set "UV_PROJECT_ENVIRONMENT=%RUNTIME_ROOT%"
  uv sync --project "%SOURCE_ROOT%" --python 3.11 --no-dev --locked
  if errorlevel 1 exit /b 1
  exit /b 0
)
py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  py -3.11 -m venv "%RUNTIME_ROOT%"
  if errorlevel 1 exit /b 1
  exit /b 0
)
py -3 -c "import sys; raise SystemExit(sys.version_info ^< (3,11))" >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%RUNTIME_ROOT%"
  if errorlevel 1 exit /b 1
  exit /b 0
)
python -c "import sys; raise SystemExit(sys.version_info ^< (3,11))" >nul 2>nul
if not errorlevel 1 (
  python -m venv "%RUNTIME_ROOT%"
  if errorlevel 1 exit /b 1
  exit /b 0
)
echo Python 3.11 or newer is required.
exit /b 1

:sync_dependencies
echo Preparing the Windows runtime outside the source tree...
where uv >nul 2>nul
if not errorlevel 1 (
  set "UV_PROJECT_ENVIRONMENT=%RUNTIME_ROOT%"
  uv sync --project "%SOURCE_ROOT%" --python 3.11 --no-dev --locked || exit /b 1
) else (
  "%PYTHON_BIN%" -m pip install --disable-pip-version-check -r "%SOURCE_ROOT%\requirements.txt" || exit /b 1
)
>"%STAMP_FILE%" echo %DEPENDENCY_HASH%
exit /b 0

:missing_source
echo KOMI Report V5 shared source was not found:
echo %SOURCE_ROOT%
echo Confirm that the canonical source folder was copied completely.
pause
popd
exit /b 1

:source_error
echo The shared source is incomplete or unavailable.
echo Confirm that the source folder in Projects/dev is available locally.
pause
popd
exit /b 1

:runtime_error
echo Unable to prepare the local Windows runtime.
pause
popd
exit /b 1

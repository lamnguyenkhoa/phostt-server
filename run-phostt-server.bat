@echo off
setlocal
rem Double-click to install dependencies (first run) and start the server.
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    ) else (
        echo Installing uv...
        powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    )
)

echo Installing dependencies...
uv sync --frozen
if errorlevel 1 goto :error

rem Settings (PORT, NUM_THREADS, ...) come from .env if present; see .env.example.
rem Variables already set in the environment take precedence over .env.
set "ENV_ARGS="
if exist ".env" set "ENV_ARGS=--env-file .env"

echo Starting server...
uv run --frozen %ENV_ARGS% src/main.py
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Something went wrong. See the messages above.
pause
exit /b 1

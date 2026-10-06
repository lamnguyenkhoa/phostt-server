@echo off
setlocal
rem Double-click to install dependencies (first run) and start the server.
cd /d "%~dp0"

if "%PORT%"=="" set PORT=8123

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

echo Starting server on port %PORT%...
uv run --frozen src/main.py --port %PORT%
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Something went wrong. See the messages above.
pause
exit /b 1

@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

echo Wenzi Windows installer

echo.

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python launcher ^(py^) was not found. Install Python 3.10 or 3.11 x64 first.
    exit /b 1
)

py -3.11 --version >nul 2>&1
if errorlevel 1 (
    py -3.10 --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python 3.10 or 3.11 was not found.
        exit /b 1
    )
    set "PYTHON=py -3.10"
) else (
    set "PYTHON=py -3.11"
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 exit /b 1
) else (
    echo [1/4] Using existing .venv
)

echo [2/4] Installing Python dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

where ffmpeg >nul 2>&1
if errorlevel 1 if not exist "vendor\ffmpeg\ffmpeg.exe" (
    echo WARNING: FFmpeg was not found in PATH or vendor\ffmpeg.
    echo Install FFmpeg before processing videos that need ASR.
) else (
    echo [3/4] Found vendor\ffmpeg\ffmpeg.exe
)

if not exist ".env" (
    echo [4/4] Creating .env from .env.example...
    copy /Y ".env.example" ".env" >nul
) else (
    echo [4/4] Keeping existing .env
)

echo.
echo Installation finished.
echo Activate the environment with:
echo   .venv\Scripts\activate
echo Start Wenzi with:
echo   .venv\Scripts\python.exe run.py
echo Then open http://127.0.0.1:8000/ui
endlocal

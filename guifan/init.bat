@echo off
setlocal

echo.
echo ========================================
echo   Python Backend Init
echo ========================================
echo.

for %%I in ("%~dp0..") do set "ROOT_DIR=%%~fI"
pushd "%ROOT_DIR%" >nul

echo [1/7] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    goto :fail
)
python --version
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: pip is unavailable. Please repair Python installation.
    goto :fail
)

echo.
echo [2/7] Checking ffmpeg in PATH...
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "%ROOT_DIR%\vendor\ffmpeg\ffmpeg.exe" (
        set "PATH=%ROOT_DIR%\vendor\ffmpeg;%PATH%"
        echo ffmpeg was not in PATH. Added "%ROOT_DIR%\vendor\ffmpeg" for this session.
    ) else (
        echo ERROR: ffmpeg not found in PATH and vendor\ffmpeg\ffmpeg.exe is missing.
        goto :fail
    )
)
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffmpeg check failed.
    goto :fail
)
echo ffmpeg is available.

echo.
echo [3/7] Checking vendor repositories...
if not exist "%ROOT_DIR%\vendor" mkdir "%ROOT_DIR%\vendor"

if not exist "%ROOT_DIR%\vendor\yt-dlp" (
    echo Cloning yt-dlp...
    git clone https://github.com/yt-dlp/yt-dlp.git "%ROOT_DIR%\vendor\yt-dlp"
    if errorlevel 1 (
        echo ERROR: Failed to clone yt-dlp.
        goto :fail
    )
) else (
    echo Found vendor\yt-dlp
)

if not exist "%ROOT_DIR%\vendor\FunASR" (
    echo Cloning FunASR...
    git clone https://github.com/modelscope/FunASR.git "%ROOT_DIR%\vendor\FunASR"
    if errorlevel 1 (
        echo ERROR: Failed to clone FunASR.
        goto :fail
    )
) else (
    echo Found vendor\FunASR
)

echo.
echo [4/7] Installing yt-dlp from vendor...
python -m pip install -e "%ROOT_DIR%\vendor\yt-dlp" -i https://pypi.org/simple
if errorlevel 1 (
    echo Official PyPI failed, retrying with default pip index ...
    python -m pip install -e "%ROOT_DIR%\vendor\yt-dlp"
    if errorlevel 1 (
        echo ERROR: Failed to install yt-dlp from vendor.
        goto :fail
    )
)

echo.
echo [5/7] Installing FunASR from vendor...
python -m pip install -e "%ROOT_DIR%\vendor\FunASR" -i https://pypi.org/simple
if errorlevel 1 (
    echo Official PyPI failed, retrying with default pip index ...
    python -m pip install -e "%ROOT_DIR%\vendor\FunASR"
    if errorlevel 1 (
        echo ERROR: Failed to install FunASR from vendor.
        goto :fail
    )
)

echo.
echo [6/7] Installing requirements.txt...
if not exist "%ROOT_DIR%\requirements.txt" (
    echo ERROR: requirements.txt not found in project root.
    goto :fail
)
python -m pip install -r "%ROOT_DIR%\requirements.txt" -i https://pypi.org/simple
if errorlevel 1 (
    echo Official PyPI failed, retrying with default pip index ...
    python -m pip install -r "%ROOT_DIR%\requirements.txt"
    if errorlevel 1 (
        echo ERROR: Failed to install requirements.
        goto :fail
    )
)

echo.
echo [7/7] Preparing .env...
if not exist "%ROOT_DIR%\.env" (
    if exist "%ROOT_DIR%\.env.example" (
        copy /Y "%ROOT_DIR%\.env.example" "%ROOT_DIR%\.env" >nul
        if errorlevel 1 (
            echo ERROR: Failed to create .env from .env.example.
            goto :fail
        )
        echo Created .env from .env.example
    ) else (
        echo ERROR: .env.example not found.
        goto :fail
    )
) else (
    echo Found existing .env
)

echo.
echo ========================================
echo Environment setup complete.
echo Start server with:
echo   python run.py
echo ========================================
echo.

popd >nul
exit /b 0

:fail
echo.
echo Initialization failed.
popd >nul
exit /b 1

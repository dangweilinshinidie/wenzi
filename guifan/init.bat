@echo off
cls

echo.
echo ========================================
echo   AI Agent Scaffold
echo ========================================
echo.

node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Node.js not found
    pause
    exit /b 1
)

if not exist node_modules (
    echo Installing dependencies...
    npm install
)

echo.
echo Environment ready!
echo.
echo Starting development server...
echo Server will run at http://localhost:3000
echo.

start /b node server.js

echo.
echo Server started! Press Ctrl+C to stop.
echo.
pause

@echo off
setlocal

python "%~dp0setup_douyin_cookie.py" %*
set EXIT_CODE=%ERRORLEVEL%

endlocal & exit /b %EXIT_CODE%

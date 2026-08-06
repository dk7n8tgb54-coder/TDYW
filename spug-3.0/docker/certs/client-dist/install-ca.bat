@echo off
echo ========================================
echo   Installing TDYW Root CA Certificate
echo ========================================
echo.

REM Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo This script requires administrator privileges.
    echo.
    echo Please right-click and run as Administrator.
    echo.
    pause
    exit /b 1
)

echo Installing certificate...
certutil -addstore "Root" ca.crt

if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   Certificate installed successfully!
    echo ========================================
    echo.
    echo Next steps:
    echo 1. Restart your browser
    echo 2. Visit https://192.168.1.49
    echo 3. Verify you see the secure lock icon
    echo.
    pause
) else (
    echo.
    echo ========================================
    echo   Failed to install certificate
    echo ========================================
    echo.
    echo Please try manual installation:
    echo 1. Right-click ca.crt
    echo 2. Install Certificate
    echo 3. Trusted Root Certification Authorities
    echo.
    pause
    exit /b 1
)

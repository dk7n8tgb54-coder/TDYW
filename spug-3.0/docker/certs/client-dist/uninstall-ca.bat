@echo off
echo ========================================
echo   Uninstalling TDYW Root CA Certificate
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

echo Removing certificate...
certutil -delstore "Root" Spug-Root-CA

if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   Certificate removed successfully!
    echo ========================================
    echo.
    echo Note: This will cause the TDYW site to show
    echo security warnings again.
    echo.
    pause
) else (
    echo.
    echo ========================================
    echo   Failed to remove certificate
    echo ========================================
    echo.
    echo It may not be installed, or was already removed.
    echo.
    pause
    exit /b 1
)

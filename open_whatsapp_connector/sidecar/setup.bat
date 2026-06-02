@echo off
title WhatsApp Sidecar Setup
echo ============================================
echo   WhatsApp Sidecar - One-Click Setup
echo ============================================
echo.

:: Check Node.js
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js is not installed or not in PATH.
    echo         Download from https://nodejs.org/ (version 22 or higher)
    pause
    exit /b 1
)

:: Show Node version
for /f "tokens=*" %%v in ('node -v') do echo [OK] Node.js %%v found

:: Navigate to sidecar directory
cd /d "%~dp0"
echo [..] Working directory: %cd%
echo.

:: Step 1: Install dependencies
echo [1/4] Installing dependencies...
call npm install
if %ERRORLEVEL% neq 0 (
    echo [ERROR] npm install failed. Check your internet connection.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.
echo.

:: Step 2: Apply patches (runs automatically via postinstall, but run again to be sure)
echo [2/4] Applying patches...
call npx patch-package
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Patch may have failed. Continuing anyway...
)
echo [OK] Patches applied.
echo.

:: Step 3: Create baileys module alias
echo [3/4] Creating module alias...
if not exist "node_modules\baileys" (
    mklink /J "node_modules\baileys" "node_modules\@whiskeysockets\baileys" >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo [WARNING] Could not create junction. Try running as Administrator.
    ) else (
        echo [OK] Module alias created.
    )
) else (
    echo [OK] Module alias already exists.
)
echo.

:: Step 4: Build TypeScript
echo [4/4] Building TypeScript...
call npm run build
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo [OK] Build complete.
echo.

echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo To start the sidecar, run:
echo   npm start
echo.
echo Or start it from Odoo:
echo   WhatsApp ^> Accounts ^> Start Sidecar
echo.
pause

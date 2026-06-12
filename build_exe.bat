@echo off
chcp 65001 >nul
title Mewgenics Breeding Analyzer - Build

echo 🐱 Building Mewgenics Breeding Analyzer...
echo.

cd /d "%~dp0"

REM Clean previous build
if exist "dist\MewgenicsBreeding" rmdir /s /q "dist\MewgenicsBreeding"
if exist "dist\MewgenicsBreeding.exe" del "dist\MewgenicsBreeding.exe"
if exist "build" rmdir /s /q "build"

REM Build with PyInstaller
.venv\Scripts\pyinstaller --onefile --windowed ^
  --name "MewgenicsBreeding" ^
  --add-data "src\app.html;." ^
  --add-data "src\img\*.svg;img" ^
  --add-data "src\extract_data.py;." ^
  --icon "src\img\icons\UI_Charisma_Icon.svg" ^
  --hidden-import sqlite3 ^
  --hidden-import struct ^
  --hidden-import json ^
  --hidden-import os ^
  --hidden-import sys ^
  --hidden-import socketserver ^
  --hidden-import webbrowser ^
  --hidden-import http.server ^
  src\server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Build failed!
    pause
    exit /b 1
)

echo.
echo ✅ Build complete!
echo    dist\MewgenicsBreeding.exe
echo.
echo The save path is hardcoded to your Steam save.
echo For distribution, users will need to update it.
pause

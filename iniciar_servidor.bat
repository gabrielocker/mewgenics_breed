@echo off
cd /d "%~dp0"
echo 🐱 Mewgenics Server
echo =================
echo Starting server...
start http://localhost:8080/app.html
.venv\Scripts\python src\server.py
pause

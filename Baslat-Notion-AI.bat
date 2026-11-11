@echo off
title Notion AI Yerel Sunucu ve Web Paneli
cd /d "%~dp0"
echo Notion AI Web Paneli baslatiliyor...
start http://127.0.0.1:8765
python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
pause

```bat
@echo off
cd /d "%~dp0"
title Classificador de IVA

echo ================================================
echo       CLASSIFICADOR DE IVA
echo ================================================
echo.

if not exist ".venv313\Scripts\python.exe" (
    echo ERRO: Python 3.13 nao encontrado no projeto.
    pause
    exit /b 1
)

echo Iniciando o servidor...
start "Servidor Classificador IVA" cmd /k ""%CD%\.venv313\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000"

echo Aguardando o servidor...
timeout /t 3 /nobreak >nul

start "" "http://127.0.0.1:8000/"

exit /b
```
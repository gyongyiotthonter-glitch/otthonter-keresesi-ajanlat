@echo off
chcp 65001 >nul
title Ingatlan Ajánlat Generátor

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║      Ingatlan Ajánlat Generátor                  ║
echo  ╚══════════════════════════════════════════════════╝
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo  [HIBA] Python nem talalhato! Telepitsd: python.org
        pause & exit /b
    )
    set PY=py
) else (
    set PY=python
)

echo  Csomagok telepitese...
%PY% -m pip install -q streamlit requests reportlab Pillow

echo.
echo  Indul az alkalmazas...
echo  Bongeszoben: http://localhost:8501
echo  Leallitas: Ctrl+C
echo.
start /b cmd /c "timeout /t 3 >nul && start http://localhost:8501"
%PY% -m streamlit run app.py --server.headless false
pause

@echo off
echo ==================================
echo   TikTok Scheduler - Demarrage
echo ==================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python n'est pas installe. Installe Python 3.8+ sur python.org
    pause
    exit /b 1
)

echo Python detecte
echo Installation de Flask si necessaire...
python -m pip install flask werkzeug -q

echo.
echo Demarrage de l'application...
echo Ouvre ton navigateur sur : http://localhost:5000
echo.
echo Appuie sur CTRL+C pour arreter
echo.

python app.py
pause

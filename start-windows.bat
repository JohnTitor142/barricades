@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python est introuvable. Installez Python 3.12 ou plus depuis python.org en cochant Add python.exe to PATH.
  goto :fail
)
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js est introuvable. Installez la version LTS depuis nodejs.org.
  goto :fail
)
if not exist "server\requirements.txt" (
  echo Ce fichier doit se trouver dans le dossier barricade, a cote des dossiers server et client.
  goto :fail
)

if not exist "server\.venv" (
  echo Creation de l'environnement Python...
  python -m venv server\.venv
  if errorlevel 1 goto :fail
)
echo Installation des dependances du serveur...
"server\.venv\Scripts\python.exe" -m pip install -q -r server\requirements.txt
if errorlevel 1 goto :fail

if not exist "client\node_modules" (
  echo Installation des dependances du client, cela peut prendre une minute...
  pushd client
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    popd
    goto :fail
  )
  popd
)

echo Demarrage du serveur et du client...
start "Barricade - serveur" /d "%~dp0server" cmd /k "set FILL_TO=8&& .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "Barricade - client" /d "%~dp0client" cmd /k "npm run dev"

timeout /t 8 >nul
start http://localhost:5173
echo.
echo Le jeu est ouvert dans votre navigateur. Fermez les deux fenetres noires pour arreter.
timeout /t 5 >nul
exit /b 0

:fail
echo.
echo Une etape a echoue. Copiez le message ci-dessus et envoyez-le a Claude.
pause
exit /b 1

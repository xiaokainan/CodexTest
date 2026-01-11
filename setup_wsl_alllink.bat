@echo off
setlocal

rem ==============================================================================
rem AllLink_V0.6 WSL (Ubuntu_AllLink) isolated setup helper for Windows 11
rem - Run this script from an elevated (Administrator) command prompt.
rem - First run will install WSL + Ubuntu if missing and may require a reboot.
rem - After rebooting and creating your Linux username/password, run again.
rem ==============================================================================

set "WSL_DISTRO=Ubuntu_AllLink"
set "BASE_DISTRO=Ubuntu"
set "IMPORT_DIR=%USERPROFILE%\WSL\Ubuntu_AllLink"
set "ROOTFS_TAR=%TEMP%\ubuntu_alllink_rootfs.tar"
set "REPO_URL=https://github.com/xiaokainan/CodexTest.git"
set "WSL_PROJECT_PATH=$HOME/AllLink_V0_6"
set "PYTHON_BIN=python3"

echo [1/5] Checking WSL availability...
wsl --status >nul 2>&1
if errorlevel 1 (
    echo WSL is not enabled. Installing WSL with %WSL_DISTRO%...
    wsl --install -d %WSL_DISTRO%
    echo.
    echo WSL/Ubuntu installation kicked off. Please reboot, create your Linux user,
    echo and run this script again to finish provisioning.
    exit /b 0
)

for /f "tokens=1" %%i in ('wsl -l -q ^| findstr /i "^%WSL_DISTRO%$"') do set "DISTRO_FOUND=1"
if not defined DISTRO_FOUND (
    for /f "tokens=1" %%i in ('wsl -l -q ^| findstr /i "^%BASE_DISTRO%$"') do set "BASE_FOUND=1"
    if not defined BASE_FOUND (
        echo Base Ubuntu is not installed. Installing %BASE_DISTRO%...
        wsl --install -d %BASE_DISTRO%
        echo.
        echo Ubuntu installation started. Reboot, create your Linux user,
        echo and run this script again to finish provisioning.
        exit /b 0
    )

    echo Creating isolated distro %WSL_DISTRO% by cloning %BASE_DISTRO%...
    wsl --export %BASE_DISTRO% "%ROOTFS_TAR%"
    wsl --import %WSL_DISTRO% "%IMPORT_DIR%" "%ROOTFS_TAR%" --version 2
    del "%ROOTFS_TAR%" >nul 2>&1
    echo.
    echo New distro %WSL_DISTRO% was created. Open it once to create a Linux user,
    echo then run this script again to finish provisioning.
    exit /b 0
)

echo [2/5] Updating Ubuntu packages and installing dependencies...
wsl -d %WSL_DISTRO% -- bash -lc "set -euo pipefail
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y %PYTHON_BIN% %PYTHON_BIN%-venv python3-pip git tesseract-ocr tesseract-ocr-jpn libtesseract-dev
"

echo [3/5] Cloning or updating repository inside WSL...
wsl -d %WSL_DISTRO% -- bash -lc "set -euo pipefail
PROJECT_DIR=\"%WSL_PROJECT_PATH%\"
if [ ! -d \"$PROJECT_DIR\" ]; then
  git clone \"%REPO_URL%\" \"$PROJECT_DIR\"
else
  cd \"$PROJECT_DIR\" && git pull --ff-only
fi
"

echo [4/5] Creating virtual environment and installing Python dependencies...
wsl -d %WSL_DISTRO% -- bash -lc "set -euo pipefail
PROJECT_DIR=\"%WSL_PROJECT_PATH%\"
cd \"$PROJECT_DIR\"
%PYTHON_BIN% -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data/logs data/receipts
"

echo [5/5] AllLink_V0.6 WSL setup completed.
echo To start the app inside WSL:
echo   wsl -d %WSL_DISTRO% -- bash -lc "cd %WSL_PROJECT_PATH% && . .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo.
echo Access the app at http://localhost:8000/ after the server starts.

endlocal

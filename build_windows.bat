@echo off
REM Build VeilMark for Windows on your own PC.
REM Requirements: Python 3.11+ (python.org), optionally Inno Setup 6 for the installer.
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt || goto :error
python -m pytest -q || goto :error
pyinstaller packaging\veilmark.spec --noconfirm --clean || goto :error
echo.
echo Portable app: dist\VeilMark\VeilMark.exe
where iscc >nul 2>nul && (
    iscc packaging\installer.iss || goto :error
    echo Installer:   dist\VeilMark-Setup-1.0.0.exe
)
goto :eof
:error
echo Build failed.
exit /b 1

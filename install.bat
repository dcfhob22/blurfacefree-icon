@echo off
REM One-click installer for Blur Faces Free
REM Run this once after extracting the ZIP.

title Installing Blur Faces Free...
setlocal

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo [X] Python is not installed (or not on PATH^).
  echo.
  echo Please install Python 3.10 or newer:
  echo    1. Download from https://www.python.org/downloads/
  echo    2. During install, CHECK the box "Add Python to PATH"
  echo    3. Re-run this installer.
  echo.
  pause
  exit /b 1
)

echo.
echo === Step 1/3: Upgrading pip ===
python -m pip install --upgrade pip
if errorlevel 1 goto fail

echo.
echo === Step 2/3: Installing face-blur engine + GUI dependencies ===
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto fail

echo.
echo === Step 3/3: Downloading face models (one time, ~40 MB) ===
python "%~dp0install_models.py"
if errorlevel 1 goto fail_models

echo.
echo ===========================================================
echo  Install complete! Everything is downloaded.
echo  After this, the app works fully offline.
echo.
echo  Next step:  double-click  "Blur Faces.bat"  to open the app.
echo ===========================================================
echo.
pause
exit /b 0

:fail_models
echo.
echo [!] The program was installed, but the face models could not be downloaded.
echo     "pick from preview" will not work until they are. Either:
echo       - Connect to the internet and run this installer again, or
echo       - Download the files by hand using the links printed above.
echo.
pause
exit /b 1

:fail
echo.
echo [X] Install failed. Scroll up and check the error message.
echo Common fixes:
echo   - Make sure you're connected to the internet.
echo   - Try right-clicking this file and "Run as administrator".
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"

uv sync --extra build
if errorlevel 1 exit /b %errorlevel%

uv run --extra build python scripts\build_app.py --clean --noconfirm %*
if errorlevel 1 exit /b %errorlevel%

echo.
echo Build complete. See the dist directory.
echo Output: dist\GFCI Analyzer.exe
echo.
echo If Windows SmartScreen warns about an unknown publisher, see the
echo "Avoid the Windows SmartScreen warning" section in PACKAGING.md.
pause

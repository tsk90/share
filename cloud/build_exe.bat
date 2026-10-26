@echo off
rem Builds dist\ScreenShareAgent.exe (single file, ffmpeg bundled). Needs: pip install pyinstaller pystray pillow aiohttp
rem and ffmpeg.exe (set FFMPEG=path\to\ffmpeg.exe, or it is auto-found from PATH / the winget install).
setlocal
if "%FFMPEG%"=="" for /f "delims=" %%F in ('where ffmpeg 2^>nul') do if "%FFMPEG%"=="" set FFMPEG=%%F
if "%FFMPEG%"=="" for /f "delims=" %%F in ('dir /s /b "%LOCALAPPDATA%\Microsoft\WinGet\Packages\ffmpeg.exe" 2^>nul ^| findstr /i "\\bin\\ffmpeg.exe"') do if "%FFMPEG%"=="" set FFMPEG=%%F
if "%FFMPEG%"=="" (echo ffmpeg.exe not found. Set FFMPEG=path\to\ffmpeg.exe & exit /b 1)
echo Using %FFMPEG%
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --name ScreenShareAgent --paths .. --add-binary "%FFMPEG%;." agent_app.py
if errorlevel 1 (echo BUILD FAILED & exit /b 1)
echo Done: %~dp0dist\ScreenShareAgent.exe

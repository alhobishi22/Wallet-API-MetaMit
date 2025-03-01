@echo off
echo Stopping MetaBit KYC System...
taskkill /f /im python.exe /fi "WINDOWTITLE eq MetaBit KYC System*"
timeout /t 2 /nobreak > nul
echo Starting MetaBit KYC System...
start "MetaBit KYC System" cmd /c "python run.py && pause"
echo System restarted successfully!

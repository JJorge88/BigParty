@echo off
taskkill /FI "WINDOWTITLE eq BIG PARTY Impresion" /T /F >nul 2>nul
del /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\BIG-PARTY-Impresion.cmd" 2>nul
echo Inicio automatico eliminado. Los registros permanecen en %%LOCALAPPDATA%%\BigPartyPrintBridge.
pause

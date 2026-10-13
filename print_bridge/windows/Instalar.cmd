@echo off
setlocal
set "APPDIR=%LOCALAPPDATA%\BigPartyPrintBridge"
if not exist "%APPDIR%" mkdir "%APPDIR%"
copy /Y "%~dp0BigPartyPrintBridge.ps1" "%APPDIR%\BigPartyPrintBridge.ps1" >nul
set /p SERVER=Direccion del sistema (ejemplo https://bigpartygt.com): 
set /p TOKEN=Clave de conexion: 
powershell.exe -NoProfile -Command "$c=@{server=$env:SERVER;token=$env:TOKEN}; $c|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $env:APPDIR 'config.json') -Encoding UTF8"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\BIG-PARTY-Impresion.cmd"
>"%STARTUP%" echo @echo off
>>"%STARTUP%" echo start "BIG PARTY Impresion" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%\BigPartyPrintBridge.ps1"
start "BIG PARTY Impresion" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%\BigPartyPrintBridge.ps1"
echo.
echo Mini app instalada. Se iniciara automaticamente con Windows.
pause

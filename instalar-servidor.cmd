@echo off
rem Doble clic para instalar o actualizar SIGA-MINEDUCYT en un servidor Windows.
rem Pide permisos de administrador y ejecuta deploy\windows\instalar-servidor.ps1.
setlocal
set "SCRIPT=%~dp0deploy\windows\instalar-servidor.ps1"

net session >nul 2>&1
if errorlevel 1 goto elevate

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
echo.
pause
exit /b

:elevate
rem Las rutas van por variables de entorno para no romper comillas.
set "SIGA_CMD=%~f0"
set "SIGA_ARGS=%*"
if "%~1"=="" (
    powershell.exe -NoProfile -Command "Start-Process -FilePath $env:SIGA_CMD -Verb RunAs"
) else (
    powershell.exe -NoProfile -Command "Start-Process -FilePath $env:SIGA_CMD -ArgumentList $env:SIGA_ARGS -Verb RunAs"
)
exit /b

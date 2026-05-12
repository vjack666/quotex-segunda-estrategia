@echo off
REM Audit Run Script - 15 minutos
REM Flags: SHADOW_ULTRA_RELAXED_VALIDATION=true, SHADOW_AUDIT_BYPASS_SPIKE_1M_ON_FORCE_EXECUTE=true

setlocal enabledelayedexpansion

echo ╔════════════════════════════════════════════════════════════════════════════╗
echo ║         AUDIT RUN #3: CORRIDA DE 15 MINUTOS CON INSTRUMENTACION            ║
echo ╚════════════════════════════════════════════════════════════════════════════╝

REM Backup log actual
echo [*] Backing up current log...
if exist "data\logs\bot\consolidation_bot-2026-05-12.log" (
    copy "data\logs\bot\consolidation_bot-2026-05-12.log" "data\logs\bot\consolidation_bot-2026-05-12.bak.log"
    echo Backed up to .bak.log
)

REM Capturar timestamp de inicio
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
echo [*] Inicio: %mydate% %mytime%

REM Iniciar bot con flags
echo [*] Iniciando bot...
set SHADOW_ULTRA_RELAXED_VALIDATION=true
set SHADOW_AUDIT_BYPASS_SPIKE_1M_ON_FORCE_EXECUTE=true
set SHADOW_AUDIT_MODE=true

REM Ejecutar en background con timeout de 900 segundos (15 minutos)
echo [*] Corriendo 15 minutos (900 segundos)...
timeout /t 900 /nobreak

echo [*] Ciclo completado
echo [*] Fin

endlocal
pause

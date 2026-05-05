param(
  [string]$NombreSesion = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$workspace = Split-Path -Parent $root

if ([string]::IsNullOrWhiteSpace($NombreSesion)) {
  $NombreSesion = Get-Date -Format "yyyyMMdd_HHmm"
}

$dest = Join-Path $root ("sesiones/" + $NombreSesion)
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# Copia plantilla de sesion
$plantilla = Join-Path $root "sesiones/plantilla_sesion.json"
if (Test-Path $plantilla) {
  Copy-Item $plantilla (Join-Path $dest "sesion.json") -Force
}

# Copiar ultima DB si existe
$db = Get-ChildItem (Join-Path $workspace "data/db/trade_journal-*.db") -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if ($db) {
  Copy-Item $db.FullName (Join-Path $dest $db.Name) -Force
}

# Copiar ultimo log si existe
$log = Get-ChildItem (Join-Path $workspace "data/logs/bot/*.log") -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if ($log) {
  Copy-Item $log.FullName (Join-Path $dest $log.Name) -Force
}

Write-Host "Sesion archivada en: $dest"
if ($db) { Write-Host "DB: $($db.Name)" }
if ($log) { Write-Host "LOG: $($log.Name)" }

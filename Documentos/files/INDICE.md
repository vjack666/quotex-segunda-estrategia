# ÍNDICE DE DOCUMENTACIÓN
*Sistema de Trading de Alta Calidad — Plan Maestro Completo*

---

## Estructura de Documentos

### 📋 PLAN_MAESTRO.md
El documento de entrada. Conecta la auditoría técnica con el objetivo operativo.
Define el problema central, el edge real identificado, y la visión del sistema mejorado.
**Leer primero.**

### 🎯 EDGE_REAL.md
Análisis de qué componentes del sistema tienen ventaja estadística real,
cuáles probablemente solo agregan ruido, y qué vale endurecer vs eliminar.
Ordenado por impacto estimado en winrate.

### 📊 MATRIZ_DE_CALIDAD.md
Clasificación de setups en cuatro categorías (A/B/C/D) con condiciones exactas
para cada una. Incluye flujo de clasificación en código y tabla comparativa.
**El documento más operativo del conjunto.**

### 🚫 FILTROS_CRITICOS.md
Definición técnica de los 7 filtros que deben convertirse en vetos binarios.
Incluye pseudocódigo de implementación, impacto estimado y tiempo de implementación.

### 🗺️ ROADMAP_TECNICO.md
Plan de trabajo dividido en 6 fases con objetivos, módulos, riesgos y
métricas de validación por fase. Incluye dependencias entre fases y tiempo estimado.

### 💰 PLAN_MASANIELLO.md
Análisis matemático del Masaniello 5/2, qué entradas lo protegen vs destruyen,
propuesta de modo conservador post-pérdida y señales de alarma.

### 📈 METRICAS_REALES.md
Definición de 12 métricas con objetivos, umbrales de alarma y cómo registrarlas.
Incluye template de reporte semanal y schema de campos a agregar al journal.

### ⚠️ HALLAZGOS_OPERATIVOS.md
Hallazgos técnicos con evidencia de código real. Problemas críticos, riesgos del
sistema y puntos fuertes a proteger.

### ✅ ESTADO_REAL_SISTEMA.md
Estado consolidado del sistema contra evidencia real de código y runtime.
Define qué está implementado, qué está validado y qué sigue no concluyente.

---

## Orden de Lectura Recomendado

Para entender el sistema completo:
1. PLAN_MAESTRO.md
2. EDGE_REAL.md
3. HALLAZGOS_OPERATIVOS.md
4. ESTADO_REAL_SISTEMA.md

Para implementar mejoras:
4. FILTROS_CRITICOS.md
5. MATRIZ_DE_CALIDAD.md
6. ROADMAP_TECNICO.md

Para gestión de riesgo:
7. PLAN_MASANIELLO.md
8. METRICAS_REALES.md

---

## Resumen Ejecutivo en Una Página

**Problema:** El sistema ya tiene vetos y observabilidad parcial, pero la validación
estadística formal NEW vs OLD todavía no cuenta con evidencia concluyente.

**Edge real:** La confluencia de tres capas tiene ventaja estadística estimada de
8-15 puntos de winrate sobre operar sin filtros:
- Flujo HTF a favor (tendencia 15m alineada)
- Zona de consolidación fuerte probada (age ≥ 30 min, range_pct ≤ 0.10%)
- Rechazo confirmado en vela 1m (strength ≥ 0.75)

**Solución principal actual:** Mantener la ejecución live estable, completar cobertura
de shadow y consolidar validación estadística antes de promover NEW.

**Resultado esperado en la fase actual:**
- Evidencia cuantitativa NEW vs OLD con muestra suficiente
- Integridad de trazabilidad (candidate -> outcome link)
- Criterios GO/NO-GO objetivos para promoción por etapas

**Tiempo objetivo actual:** ejecutar sesiones de observación y cerrar validación estadística formal.

**Riesgo crítico inmediato:** Credenciales en texto plano en archivos de sesión.
Rotar y mover a variables de entorno antes de cualquier otra modificación.

# 📊 Calculadora de Opciones Binarias

## 🎯 Propósito

Calculadora de gestión de riesgo y Martingale para opciones binarias. Calcula automáticamente el monto de inversión necesario en cada operación para alcanzar un objetivo de ganancia, con protección contra riesgo excesivo.

## 🔧 Tecnología

- **Framework**: Flutter (Dart)
- **Tipo**: Aplicación multiplataforma (Web, Windows, macOS, Linux, Android, iOS)
- **Dependencias**: fl_chart, shared_preferences, flutter

## 📐 Algoritmo Core

### 1. **Cálculo de Inversión Base**
```
utilidad_necesaria = objetivo_saldo - saldo_actual
inversión_base = utilidad_necesaria / payout
```

Ejemplo:
- Saldo actual: $100
- Objetivo: $110 (incremento de $10)
- Payout: 92%
- Inversión = $10 / 0.92 = **$10.87**

### 2. **Gestión de Gales (Martingale)**

**Modo por Objetivo:**
- En cada pérdida, recalcula la inversión requerida para alcanzar el objetivo desde el nuevo saldo
- Automáticamente ajusta al saldo actualizado

**Modo Multiplicador:**
- En cada pérdida, multiplica la inversión anterior por un factor (ej: 2x)
- Uso rápido pero requiere confirmación manual

### 3. **Regla del 10% (Risk Management)**

**Si saldo ≤ $50:**
- Reset automático después de 3 pérdidas consecutivas
- Reinicia el ciclo desde la inversión base

**Si saldo > $50:**
- Si la próxima inversión >= 10% de la cuenta → **Reset inmediato**
- Previene riesgo catastrophal

Ejemplo de trigger:
```
Saldo: $100
Limite 10%: $10
Inversión calculada: $12
→ RESET (12 > 10)
```

### 4. **Objetivo Manual**

Permite sobrescribir el objetivo automático por ciclo:
- Ingresa un valor específico (ej: $250)
- Solo se usa para 1 ciclo
- Se limpia automáticamente después de una ganancia

### 5. **Ciclo Completo**

```
[INICIO] Saldo $100 → Objetivo $110
         ↓
[OPERACIÓN 1] Inversión $10.87 → PERDIDA
         ↓
[GALE 1] Saldo $89.13 → Nuevo cálculo
         Inversión $20.12 → GANANCIA
         ↓
[CIERRE CICLO] Saldo fuerza a $110 (objetivo)
         ↓
[NUEVO CICLO] Saldo $110 → Objetivo $120
```

## 💾 Persistencia

- Saldo se guarda automáticamente en SharedPreferences
- Recupera el último saldo al reiniciar la aplicación
- Historial de saldo se mantiene en memoria (sesión actual)

## 📈 Gráfica

- Visualiza evolución del saldo en tiempo real
- Código de color:
  - 🟢 **Verde**: Tendencia alcista
  - 🔴 **Rojo**: Tendencia bajista
- Cada punto = un evento (ganancia/pérdida/reset)
- Botón para resetear gráfica sin afectar saldo

## ⚙️ Parámetros Configurables

| Parámetro | Rango | Defecto | Descripción |
|-----------|-------|---------|-------------|
| **Saldo** | $0+ | $0 | Balance actual |
| **Incremento** | $1+ | $2 | Ganancia objetivo por ciclo |
| **Payout** | 1%-99% | 92% | Porcentaje de ganancia en opciones |
| **Multiplicador** | 1x+ | 2x | Factor de multiplicación en gales (si aplica) |
| **Objetivo Manual** | $1+ | — | Sobrescribe objetivo automático |

## 🚀 Integración con el Bot (QUOTEX Strategy)

Esta calculadora puede integrarse con el bot de trading para:

1. **Validación de inversiones**: Verificar que montos propuestos por el bot cumplen con reglas de riesgo
2. **Cálculo dinámico de martingale**: Adaptar inversiones según saldo en tiempo real
3. **Risk scoring**: Alertar cuando se acerca el límite del 10%
4. **Backtesting**: Simular diferentes escenarios de payout y duración

### Ejemplo de integración futura:
```python
from calculadora_nuevo.core import MartingaleCalculator

calc = MartingaleCalculator(
    saldo_inicial=100,
    objetivo=110,
    payout=0.92
)

# Después de una operación
if operacion_ganada:
    calc.registrar_ganancia()
else:
    monto_siguiente = calc.calcular_gale()
    # Enviar monto_siguiente al bot
```

## 📋 Casos de Uso

### Escenario 1: Estrategia Conservadora (QUOTEX STRAT-A)
```
Saldo: $100 | Incremento: $5 | Payout: 92%
Inversión: $5.43
Gales: Máx 3-4 antes de reset (regla 10%)
```

### Escenario 2: Estrategia Agresiva (QUOTEX STRAT-B)
```
Saldo: $200 | Incremento: $20 | Payout: 88%
Inversión: $22.73
Gales: Permitidos hasta $20 (límite 10% de $200)
```

### Escenario 3: Recuperación de Pérdidas
```
Saldo: $30 (después de pérdidas)
Objetivo Manual: $50
Payout: 90%
Inversión: $22.22
Gale: Reset por regla 3 pérdidas (saldo < $50)
```

## 🔴 Limitaciones & Notas

- **No es predictor**: Calcula inversiones, no predice resultados
- **Requiere disciplina**: Solo funciona si se siguen las reglas (especialmente reset de 3 pérdidas)
- **Payout variable**: Ajusta el payout según el activo y condiciones de mercado
- **Historial**: Se pierde al cerrar la app (salvo saldo final guardado)

## 🛠️ Compilación & Ejecución

```bash
# Descargar dependencias
flutter pub get

# Ejecutar en modo debug
flutter run

# Compilar para Web
flutter build web

# Compilar para Windows
flutter build windows

# Compilar para APK (Android)
flutter build apk
```

## 📝 Notas del Desarrollador

- **Estado**: Stable, tested en ambiente de práctica
- **Última actualización**: 2026-04-29
- **Mantenedor**: QUOTEX Strategy V2
- **Próximas mejoras**:
  - Exportar historial a CSV
  - Análisis estadístico de gales
  - Integración con API de Quotex en tiempo real
  - Dark/Light theme toggle (ya implementado)

# 🔄 Integración Martingale Calculator

## Cambios Realizados

### 1. Nuevo Módulo: `src/martingale_calculator.py`
**Propósito**: Gestionar cálculo de montos con lógica de Martingale de la calculadora.

**Clase Principal**: `MartingaleCalculator`

**Atributos**:
- `INCREMENT = 2.00` — Incremento fijo por ciclo
- `MAX_RISK_PCT = 0.10` — No invertir más del 10% del saldo
- `current_balance` — Saldo actual
- `cycle_target` — Objetivo del ciclo (próximo número par)
- `cycle_losses` — Contador de gales

**Métodos Principales**:
```python
calculator = MartingaleCalculator(balance)

# Calcular inversión para payout
amount, status = calculator.calculate_investment(payout_pct=92)
# status: "OK", "RISK_EXCEEDED", "CYCLE_COMPLETE"

# Registrar ganancia
calculator.register_win(amount_invested=2.12, payout_pct=92)

# Registrar pérdida
calculator.register_loss(amount_invested=2.12)

# Ver estado
status = calculator.get_status()
```

---

### 2. Cambios en `src/consolidation_bot.py`

#### a) **Importación**
```python
from martingale_calculator import MartingaleCalculator
```

#### b) **Instancia en `__init__()`**
```python
self.martingale: MartingaleCalculator = MartingaleCalculator()
```

#### c) **Sincronización de Balance**
En `set_session_start_balance()`:
```python
self.martingale.set_balance(float(balance))
```

En `_update_balance_from_broker()`:
```python
self.martingale.set_balance(bal)
```

#### d) **Reemplazo de Funciones de Cálculo**

**Antes**:
```python
def _compute_initial_amount(self, payout_pct: int):
    target = self._target_profit_for_integer_balance(TARGET_MIN_PROFIT)
    return self._amount_for_target_profit(payout_pct, target)

def _compute_compensation_amount(self, payout_pct: int, base_loss: float):
    target = self._target_profit_for_integer_balance(MARTIN_TARGET_PROFIT) + base_loss
    return self._amount_for_target_profit(payout_pct, target)
```

**Ahora**:
```python
def _compute_initial_amount(self, payout_pct: int) -> Tuple[float, float]:
    """Calcula monto inicial usando MartingaleCalculator."""
    if self.current_balance is not None:
        self.martingale.set_balance(self.current_balance)

    amount, status = self.martingale.calculate_investment(payout_pct)
    
    if status != "OK":
        log.warning(f"⚠ {status} | amount={amount:.2f}")
        return 0.0, 0.0
    
    payout_rate = float(payout_pct) / 100.0
    expected_profit = self._round_up_to_cents(amount * payout_rate)
    return amount, expected_profit

def _compute_compensation_amount(self, payout_pct: int, base_loss: float) -> Tuple[float, float]:
    """Calcula monto de compensación (gale) usando MartingaleCalculator."""
    if self.current_balance is not None:
        self.martingale.set_balance(self.current_balance)
    
    amount, status = self.martingale.calculate_investment(payout_pct)
    
    if status != "OK":
        return 0.0, 0.0
    
    payout_rate = float(payout_pct) / 100.0
    expected_profit = self._round_up_to_cents(amount * payout_rate)
    return amount, expected_profit
```

#### e) **Registro de Resultados**
En `_on_broker_message()` donde se procesa WIN/LOSS:

**Antes**:
```python
if outcome == "WIN":
    self.compensation_pending = False
elif outcome == "LOSS":
    self.compensation_pending = True
    self.last_closed_amount = trade.amount
```

**Ahora**:
```python
if outcome == "WIN":
    self.compensation_pending = False
    self.martingale.register_win(trade.amount, trade.payout)
elif outcome == "LOSS":
    self.compensation_pending = True
    self.last_closed_amount = trade.amount
    self.martingale.register_loss(trade.amount)
```

---

## 🎯 Lógica de Funcionamiento

### Ciclo Completo

```
[INICIO] Saldo: $42.59
  ↓
[OBJETIVO] → Próximo par: $44 (INCREMENT=$2)
  ↓
[CÁLCULO] Payout=92%
  amount = (44 - 42.59) / 0.92 = 1.54 / 0.92 = 1.67 → 1.69 (redondeado)
  Riesgo: 1.69 / 42.59 = 3.96% ✅ < 10%
  ↓
[ENVIADA] $1.69 CALL
  ↓
  ├─ [GANANCIA] → Saldo sube a $44 (cierre limpio)
  │  └─ Ciclo completado, nuevo objetivo: $46
  │
  └─ [PÉRDIDA] → Saldo baja a $40.90
     ├─ Gale 1: (44 - 40.90) / 0.85 = 3.65 → $3.71
     ├─ Si pierde: Saldo $37.19
     │  └─ Gale 2: (44 - 37.19) / 0.90 = 7.57 → $7.68
     │     etc...
     │
     └─ Si gana en cualquier gale → Saldo fuerza a $44
```

### Reglas de Riesgo

**Regla 10%**: No permite inversión > 10% del saldo
```
Saldo: $30
Límite 10%: $3.00
Inversión calculada: $5.00
→ Status: "RISK_EXCEEDED" → NO ENVIAR
```

**Reset por 3 pérdidas** (si saldo ≤ $50):
```
Saldo ≤ $50 Y 3 pérdidas seguidas
→ Resetear ciclo, nuevo objetivo
```

---

## 📊 Ejemplos Prácticos

### Ejemplo 1: Incremento de $2 limpio

```
Balance: $100.00
Payout: 92%
  → Objetivo: $102
  → Inversión: (102 - 100) / 0.92 = 2.17
  → Status: OK

[GANANCIA]
  → Nuevo saldo: $102.00
  → Objetivo siguiente: $104
```

### Ejemplo 2: Gales con múltiples payouts

```
Balance: $41.05
Payout: 92%
  → Objetivo: $42 (próximo par es 42, luego 44... pero incremento es 2)
  → Wait, let me recalculate: ceil((41.05 + 0.01) / 2) * 2 = ceil(20.53) * 2 = 21 * 2 = 42
  → Inversión: (42 - 41.05) / 0.92 = 1.03 → $2.12 (redondeado hacia arriba)
  → Status: OK (2.12 / 41.05 = 5.2% < 10%)

[PÉRDIDA]
  → Nuevo saldo: $38.93
  
Gale 1 - Payout: 85%
  → Objetivo: $42 (sigue igual)
  → Inversión: (42 - 38.93) / 0.85 = 3.61
  → Status: OK (3.61 / 38.93 = 9.3% < 10%)

[GANANCIA]
  → Nuevo saldo: $42.00
  → Objetivo siguiente: $44
```

### Ejemplo 3: Bloqueo por riesgo excesivo

```
Balance: $30.00
Límite 10%: $3.00
Payout: 85%
  → Objetivo: $32
  → Inversión: (32 - 30) / 0.85 = 2.35 → $2.35
  → Status: OK (2.35 < 3.00)

[PÉRDIDA]
  → Nuevo saldo: $27.65

Gale 1 - Payout: 80%
  → Objetivo: $32
  → Inversión: (32 - 27.65) / 0.80 = 5.44
  → Límite 10%: $2.77
  → Status: "RISK_EXCEEDED" (5.44 > 2.77)
  → NO ENVIAR ⛔
  → Manual intervention needed
```

---

## ⚙️ Integración con el Bot

### Puntos de Entrada

1. **Cálculo de monto inicial**
   ```python
   amount, _ = self._compute_initial_amount(payout)
   # Ahora usa: calculator.calculate_investment(payout)
   ```

2. **Cálculo de monto de martingala**
   ```python
   amount, _ = self._compute_compensation_amount(payout, base_loss)
   # Ahora usa: calculator.calculate_investment(payout) después de pérdida
   ```

3. **Actualización de balance**
   ```python
   # Automático cuando se llama a set_balance()
   # Resetea ciclo si sale del rango esperado
   ```

4. **Registro de resultados**
   ```python
   if outcome == "WIN":
       calculator.register_win(amount, payout)
   elif outcome == "LOSS":
       calculator.register_loss(amount)
   ```

---

## 🔍 Monitoreo & Debug

### Status del Martingale

```python
status = bot.martingale.get_status()
# Retorna:
# {
#     'balance': 42.59,
#     'target': 44.0,
#     'profit_needed': 1.41,
#     'losses': 0,
#     'risk_limit_10pct': 4.259
# }

# Formato para logging:
log.info(bot.martingale.format_status())
# Output: Balance: $42.59 | Objetivo: $44.00 | Necesita: $1.41 | Gales: 0 | Límite 10%: $4.26
```

### Estados Posibles en `calculate_investment()`

| Estado | Significado | Acción |
|--------|-------------|--------|
| `OK` | Inversión segura | ✅ ENVIAR |
| `CYCLE_COMPLETE` | Ya alcanzamos objetivo | 🔄 RESETEAR |
| `RISK_EXCEEDED` | Monto > 10% del saldo | ⛔ NO ENVIAR |
| `ERROR_NO_BALANCE` | Sin balance registrado | ⚠️ WAIT |

---

## 🚀 Próximos Pasos

1. **Testeo en modo dry-run**
   ```bash
   python main.py --dry-run
   ```

2. **Validación con histórico**
   - Reproducir operaciones desde trade_journal.db
   - Comparar montos calculados vs reales

3. **Adaptaciones por mercado**
   - Ajustar INCREMENT si se requiere
   - Tune MAX_RISK_PCT según preferencia

4. **Logging mejorado**
   - Agregar martingale.format_status() al output de ciclos
   - Alertas cuando RISK_EXCEEDED

---

## 📋 Cambios en Constantes

| Constante | Antes | Ahora | Notas |
|-----------|-------|-------|-------|
| `AMOUNT_INITIAL` | $1.00 | Dinámico | Calculado por martingale |
| `AMOUNT_MARTIN` | $3.00 | Dinámico | Calculado por martingale |
| `TARGET_MIN_PROFIT` | $1.00 | — | Ya no usado |
| `MARTIN_TARGET_PROFIT` | $1.00 | — | Ya no usado |
| `INCREMENT` | — | $2.00 | Nuevo en MartingaleCalculator |
| `MAX_RISK_PCT` | — | 10% | Nuevo en MartingaleCalculator |


"""
Martingale Calculator para Opciones Binarias.
Reemplica la lógica de la calculadora Flutter en Python.

Lógica:
- Incremento: $2 (fijo)
- Objetivo: Próximo número entero par (saldo redondeado hacia arriba a múltiplo de 2)
- Inversión = (objetivo - saldo) / payout
- Regla 10%: No invertir si monto > 10% del saldo actual (RESET)
- Gales: Recalcular inversión en cada pérdida para llegar al objetivo final
"""

from math import ceil
from typing import Tuple, Optional
import logging

log = logging.getLogger(__name__)


class MartingaleCalculator:
    """Calculadora de Martingale para ciclos de trading con incremento fijo."""

    # Configuración fija
    INCREMENT = 2.00  # Incremento por ciclo ($2) (fallback)
    GROWTH_PCT = 0.02  # Objetivo por operación: 2% de la cuenta base de sesión
    MIN_ORDER_AMOUNT = 1.01  # Monto mínimo de orden (broker requiere > $1.00)
    MIN_ORDER_AMOUNT_LOW_BALANCE = 2.00  # Mínimo cuando saldo < LOW_BALANCE_THRESHOLD
    LOW_BALANCE_THRESHOLD = 100.0  # Umbral de saldo bajo
    MAX_RISK_PCT = 0.10  # Máximo 10% del saldo por operación
    PRECISION_CENTS = 0.01  # Redondear a centavos
    MAX_CONSECUTIVE_ENTRIES = 4  # Máximo de entradas: base + 3 gales seguidos

    def __init__(self, current_balance: Optional[float] = None):
        """
        Args:
            current_balance: Saldo actual de la cuenta. Si es None, se actualiza luego.
        """
        self.current_balance = current_balance
        self.cycle_target = None  # Objetivo del ciclo actual
        self.cycle_losses = 0  # Contador de pérdidas en el ciclo
        self.session_base_balance = float(current_balance) if current_balance is not None else None
        self.fixed_increment_amount: Optional[float] = None
        # Inicializar objetivo si hay saldo
        if current_balance is not None and current_balance >= 0:
            self._reset_cycle()

    def set_balance(self, balance: float, *, reset_cycle: bool = True) -> None:
        """Actualiza el saldo actual y opcionalmente resetea el ciclo."""
        if balance < 0:
            balance = 0
        self.current_balance = balance
        if reset_cycle:
            self._reset_cycle()

    def sync_balance(self, balance: float) -> None:
        """Sincroniza saldo sin reiniciar contador/objetivo del ciclo."""
        self.set_balance(balance, reset_cycle=False)

    def _dynamic_min_order(self, balance: float) -> float:
        """Devuelve el mínimo de orden según el saldo actual."""
        if balance < self.LOW_BALANCE_THRESHOLD:
            return self.MIN_ORDER_AMOUNT_LOW_BALANCE
        return self.MIN_ORDER_AMOUNT

    def configure_growth_target(self, base_balance: float, pct: float = 0.02) -> None:
        """Configura objetivo fijo por operación (2% de la cuenta base de sesión)."""
        safe_base = max(0.0, float(base_balance))
        safe_pct = max(0.0, float(pct))
        self.session_base_balance = safe_base
        fixed_amount = self._round_up_to_cents(safe_base * safe_pct)
        self.fixed_increment_amount = max(self._dynamic_min_order(safe_base), fixed_amount)
        self.GROWTH_PCT = safe_pct
        self._reset_cycle()

    def _target_increment_amount(self) -> float:
        if self.fixed_increment_amount is not None and self.fixed_increment_amount > 0:
            return float(self.fixed_increment_amount)
        if self.session_base_balance is not None and self.session_base_balance > 0:
            return max(self.MIN_ORDER_AMOUNT, self._round_up_to_cents(self.session_base_balance * self.GROWTH_PCT))
        return float(self.INCREMENT)

    def _reset_cycle(self) -> None:
        """Resetea el ciclo con nuevo objetivo."""
        if self.current_balance is not None:
            self.cycle_target = self._calculate_objective()
            self.cycle_losses = 0
        else:
            self.cycle_target = None
            self.cycle_losses = 0

    def _calculate_objective(self) -> float:
        """
        Calcula el próximo objetivo: próximo número entero par.
        Siempre devuelve sin decimales (44.0, 46.0, etc.).
        Regla:
        - Si saldo es par exacto (ej: 42.00), objetivo = saldo + 2
        - Si saldo tiene decimales (ej: 42.92), objetivo = próximo par (ej: 44)
        Ej: 42.92 → 44, 42.00 → 44, 45.00 → 47
        """
        if self.current_balance is None:
            return 0
        return self._calculate_objective_from_balance(float(self.current_balance))

    def _calculate_objective_from_balance(self, balance: float) -> float:
        """Calcula el objetivo de ciclo para un balance dado (sin mutar estado)."""
        if balance < 0:
            balance = 0.0

        increment = self._target_increment_amount()
        return self._round_up_to_cents(balance + increment)

    def _round_up_to_cents(self, amount: float) -> float:
        """Redondea hacia arriba a centavos."""
        return ceil(amount / self.PRECISION_CENTS) * self.PRECISION_CENTS

    def calculate_investment(self, payout_pct: int) -> Tuple[float, str]:
        """
        Calcula el monto a invertir para alcanzar el objetivo.

        Args:
            payout_pct: Porcentaje de payout (ej: 92 para 92%)

        Returns:
            Tupla (monto_inversión, estado)
            - monto: Cantidad a invertir en USD
            - estado: "OK", "RISK_EXCEEDED", "CYCLE_COMPLETE"

        Lógica:
        1. Si no hay saldo → retornar $0
        2. Si ya alcanzamos objetivo → retornar "CYCLE_COMPLETE"
        3. Calcular: inversión = (objetivo - saldo) / payout
        4. Si inversión > 10% del saldo → retornar "RISK_EXCEEDED"
        5. Si inversión < mínimo → retornar mínimo
        """
        if self.current_balance is None or self.current_balance < 0:
            return 0, "ERROR_NO_BALANCE"

        if self.cycle_target is None:
            self.cycle_target = self._calculate_objective()

        if self.cycle_losses >= self.MAX_CONSECUTIVE_ENTRIES:
            return 0, "MAX_CONSECUTIVE_REACHED"

        # Verificar si ya alcanzamos el objetivo
        if self.current_balance >= self.cycle_target:
            # Ciclo completado, resetear para próximo
            self._reset_cycle()
            return 0, "CYCLE_COMPLETE"

        # Calcular ganancia neta necesaria
        profit_needed = self.cycle_target - self.current_balance

        # Convertir payout a decimal (92 → 0.92)
        payout_rate = max(0.01, float(payout_pct) / 100.0)

        # Calcular inversión requerida
        raw_investment = profit_needed / payout_rate

        # Redondear hacia arriba a centavos
        investment = self._round_up_to_cents(raw_investment)
        investment = max(self._dynamic_min_order(self.current_balance), investment)

        # Verificar regla del 10%
        risk_limit = self.current_balance * self.MAX_RISK_PCT
        if investment > risk_limit:
            return investment, f"RISK_EXCEEDED|limit={risk_limit:.2f}"

        return investment, "OK"

    def preview_investment(self, payout_pct: int, balance_override: float) -> Tuple[float, str]:
        """Calcula inversión para un balance proyectado sin mutar el estado interno.

        Se usa para escenarios como GALE en curso, donde hay una pérdida probable
        aún no confirmada por el broker.
        Preserva el cycle_target ACTUAL para que el gale recupere la pérdida real,
        en vez de calcular un target nuevo desde el balance proyectado (que devolvería
        el mismo monto que la operación base).
        """
        projected_balance = max(0.0, float(balance_override))
        # Usar el target del ciclo vigente si existe, para que el gale cubra la pérdida
        # real y no solo apunte a un incremento mínimo desde el saldo reducido.
        if self.cycle_target is not None and self.cycle_target > projected_balance:
            cycle_target = self.cycle_target
        else:
            cycle_target = self._calculate_objective_from_balance(projected_balance)

        if projected_balance >= cycle_target:
            return 0, "CYCLE_COMPLETE"

        profit_needed = cycle_target - projected_balance
        payout_rate = max(0.01, float(payout_pct) / 100.0)
        raw_investment = profit_needed / payout_rate

        investment = self._round_up_to_cents(raw_investment)
        investment = max(self._dynamic_min_order(projected_balance), investment)

        risk_limit = projected_balance * self.MAX_RISK_PCT
        if investment > risk_limit:
            return investment, f"RISK_EXCEEDED|limit={risk_limit:.2f}"

        return investment, "OK"

    def register_win(
        self,
        amount_invested: float,
        payout_pct: int,
        *,
        apply_target_balance: bool = True,
    ) -> Tuple[float, str]:
        """
        Registra ganancia y cierra ciclo.
        El saldo se ajusta EXACTAMENTE al objetivo (número par entero, sin decimales).

        Args:
            amount_invested: Monto que se invirtió
            payout_pct: Porcentaje de payout realizado

        Returns:
            Tupla (nuevo_saldo, estado)
        """
        if self.current_balance is None:
            return 0, "ERROR_NO_BALANCE"

        old_balance = self.current_balance
        cycle_target = self.cycle_target if self.cycle_target else old_balance + self._target_increment_amount()

        if apply_target_balance:
            # Modo simulado: fuerza cierre exacto al objetivo del ciclo.
            self.current_balance = round(cycle_target, 2)

        # Resetea ciclo para próxima ronda
        self.cycle_losses = 0
        self._reset_cycle()

        log.info(
            "✅ WIN: %.2f → %.2f (objetivo: %.2f, ganancia ajustada)",
            old_balance, self.current_balance, cycle_target
        )

        return self.current_balance, "CYCLE_CLOSED"

    def register_loss(self, amount_invested: float, *, apply_balance_change: bool = True) -> Tuple[float, str]:
        """
        Registra pérdida y calcula próximo gale.

        Args:
            amount_invested: Monto que se perdió

        Returns:
            Tupla (nuevo_saldo, estado)
        """
        if self.current_balance is None:
            return 0, "ERROR_NO_BALANCE"

        old_balance = self.current_balance
        if apply_balance_change:
            self.current_balance -= amount_invested

        if self.current_balance < 0:
            self.current_balance = 0

        self.cycle_losses += 1

        # Regla de reset: máximo de entradas consecutivas alcanzado.
        if self.cycle_losses >= self.MAX_CONSECUTIVE_ENTRIES:
            log.warning(
                "🔄 RESET por máximo de entradas consecutivas (%d)",
                self.MAX_CONSECUTIVE_ENTRIES,
            )
            self._reset_cycle()
            return self.current_balance, "MAX_CONSECUTIVE_REACHED"

        if self.current_balance <= 0:
            log.warning(
                "🔄 RESET por saldo no operativo (%.2f)",
                self.current_balance,
            )
            self._reset_cycle()
            return self.current_balance, "RESET_NO_BALANCE"

        log.info(
            "❌ LOSS (gale %d): %.2f - %.2f = %.2f (objetivo: %.2f)",
            self.cycle_losses,
            old_balance,
            amount_invested if apply_balance_change else 0.0,
            self.current_balance,
            self.cycle_target,
        )

        return self.current_balance, f"GALE_{self.cycle_losses}"

    def check_10_percent_risk(self, proposed_investment: float) -> Tuple[bool, str]:
        """Verifica si una inversión propuesta respeta la regla del 10%."""
        if self.current_balance is None or self.current_balance <= 0:
            return False, "NO_BALANCE"

        limit = self.current_balance * self.MAX_RISK_PCT
        if proposed_investment > limit:
            return False, (
                f"⚠️ Riesgo excesivo: ${proposed_investment:.2f} > 10% de "
                f"${self.current_balance:.2f} (${limit:.2f})"
            )

        return True, "OK"

    def get_status(self) -> dict:
        """Retorna el estado actual del ciclo de riesgo."""
        return {
            "balance": self.current_balance,
            "target": self.cycle_target,
            "profit_needed": (self.cycle_target - self.current_balance) if self.cycle_target else 0,
            "losses": self.cycle_losses,
            "risk_limit_10pct": (self.current_balance * self.MAX_RISK_PCT) if self.current_balance else 0,
        }

    def format_status(self) -> str:
        """Retorna el estado del ciclo formateado para logging."""
        status = self.get_status()
        return (
            f"Balance: ${status['balance']:.2f} | "
            f"Objetivo: ${status['target']:.2f} | "
            f"Necesita: ${status['profit_needed']:.2f} | "
            f"Gales: {status['losses']} | "
            f"Límite 10%: ${status['risk_limit_10pct']:.2f}"
        )

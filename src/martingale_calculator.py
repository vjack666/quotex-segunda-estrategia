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
    INCREMENT = 2.00  # Incremento por ciclo ($2)
    MIN_ORDER_AMOUNT = 1.00  # Monto mínimo de orden
    MAX_RISK_PCT = 0.10  # Máximo 10% del saldo por operación
    PRECISION_CENTS = 0.01  # Redondear a centavos
    RESET_BALANCE_THRESHOLD = 100.0  # Si saldo <= umbral y hay 3 pérdidas, reinicia ciclo

    def __init__(self, current_balance: Optional[float] = None):
        """
        Args:
            current_balance: Saldo actual de la cuenta. Si es None, se actualiza luego.
        """
        self.current_balance = current_balance
        self.cycle_target = None  # Objetivo del ciclo actual
        self.cycle_losses = 0  # Contador de pérdidas en el ciclo
        # Inicializar objetivo si hay saldo
        if current_balance is not None and current_balance >= 0:
            self._reset_cycle()

    def set_balance(self, balance: float) -> None:
        """Actualiza el saldo actual y resetea el ciclo."""
        if balance < 0:
            balance = 0
        self.current_balance = balance
        self._reset_cycle()

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

        # Si es un número par exacto (entero), sumar INCREMENT
        if (self.current_balance == int(self.current_balance) and 
            int(self.current_balance) % 2 == 0):
            return float(int(self.current_balance + self.INCREMENT))

        # Si no es par exacto, ir al próximo par
        target = ceil(self.current_balance / self.INCREMENT) * self.INCREMENT
        return float(int(target))  # Asegura número entero sin decimales

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
        investment = max(self.MIN_ORDER_AMOUNT, investment)

        # Verificar regla del 10%
        risk_limit = self.current_balance * self.MAX_RISK_PCT
        if investment > risk_limit:
            return investment, f"RISK_EXCEEDED|limit={risk_limit:.2f}"

        return investment, "OK"

    def register_win(self, amount_invested: float, payout_pct: int) -> Tuple[float, str]:
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
        cycle_target = self.cycle_target if self.cycle_target else old_balance + 2

        # IMPORTANTE: Fuerza el saldo exacto al objetivo (cierre limpio sin decimales)
        # Esto asegura que siempre cierre en un número par exacto
        self.current_balance = round(cycle_target)  # Redondea al entero más cercano

        # Resetea ciclo para próxima ronda
        self._reset_cycle()

        log.info(
            "✅ WIN: %.2f → %.2f (objetivo: %.2f, ganancia ajustada)",
            old_balance, self.current_balance, cycle_target
        )

        return self.current_balance, "CYCLE_CLOSED"

    def register_loss(self, amount_invested: float) -> Tuple[float, str]:
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
        self.current_balance -= amount_invested

        if self.current_balance < 0:
            self.current_balance = 0

        self.cycle_losses += 1

        # Regla de reset: 3 pérdidas seguidas si saldo <= $100
        if self.current_balance <= self.RESET_BALANCE_THRESHOLD and self.cycle_losses >= 3:
            log.warning(
                "🔄 RESET por 3 pérdidas (saldo: %.2f <= $%.0f)",
                self.current_balance,
                self.RESET_BALANCE_THRESHOLD,
            )
            self._reset_cycle()
            return self.current_balance, "RESET_3_LOSSES"

        log.info(
            "❌ LOSS (gale %d): %.2f - %.2f = %.2f (objetivo: %.2f)",
            self.cycle_losses, old_balance, amount_invested, self.current_balance, self.cycle_target
        )

        return self.current_balance, f"GALE_{self.cycle_losses}"

    def check_10_percent_risk(self, proposed_investment: float) -> Tuple[bool, str]:
        """
        Verifica si la inversión propuesta respeta la regla del 10%.

        Args:
            proposed_investment: Monto a verificar

        Returns:
            Tupla (es_seguro, mensaje)
        """
        if self.current_balance is None or self.current_balance <= 0:
            return False, "NO_BALANCE"

        limit = self.current_balance * self.MAX_RISK_PCT
        safe = proposed_investment <= limit

        if not safe:
            msg = f"⚠️ Riesgo excesivo: ${proposed_investment:.2f} > 10% de ${self.current_balance:.2f} (${limit:.2f})"
            return False, msg

        return True, "OK"

    def get_status(self) -> dict:
        """Retorna estado actual del ciclo."""
        return {
            "balance": self.current_balance,
            "target": self.cycle_target,
            "profit_needed": (self.cycle_target - self.current_balance) if self.cycle_target else 0,
            "losses": self.cycle_losses,
            "risk_limit_10pct": (self.current_balance * 0.1) if self.current_balance else 0,
        }

    def format_status(self) -> str:
        """Retorna estado formateado para logging."""
        status = self.get_status()
        return (
            f"Balance: ${status['balance']:.2f} | "
            f"Objetivo: ${status['target']:.2f} | "
            f"Necesita: ${status['profit_needed']:.2f} | "
            f"Gales: {status['losses']} | "
            f"Límite 10%: ${status['risk_limit_10pct']:.2f}"
        )

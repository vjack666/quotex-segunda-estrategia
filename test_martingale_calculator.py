#!/usr/bin/env python3
"""
Test script para MartingaleCalculator.
Valida los ejemplos dados por el usuario.
"""

import sys
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from martingale_calculator import MartingaleCalculator


def test_example_1():
    """
    Ejemplo 1: Saldo 42.59, objetivo 44, payout 92%
    InversiÃ³n esperada: ~2.12
    """
    print("\n" + "="*70)
    print("TEST 1: Saldo $42.59, Objetivo $44, Payout 92%")
    print("="*70)
    
    calc = MartingaleCalculator(current_balance=42.59)
    print(f"Status: {calc.format_status()}")
    
    amount, status = calc.calculate_investment(92)
    print(f"\nCÃ¡lculo:")
    print(f"  InversiÃ³n: ${amount:.2f}")
    print(f"  Estado: {status}")
    
    # Validar que es cercano a 2.12
    expected = 2.12
    if abs(amount - expected) < 0.10:
        print(f"  âœ… OK: ${amount:.2f} â‰ˆ ${expected:.2f}")
    else:
        print(f"  âŒ ERROR: esperado ~${expected:.2f}, obtenido ${amount:.2f}")


def test_example_2_gales():
    """
    Ejemplo 2: Saldo 41.05, payout 92% â†’ 1Âª inversiÃ³n 2.12
    Pierde, payout 85% â†’ 2Âª inversiÃ³n 3.61
    """
    print("\n" + "="*70)
    print("TEST 2: Gales con mÃºltiples payouts")
    print("="*70)
    
    calc = MartingaleCalculator(current_balance=41.05)
    print(f"Status inicial: {calc.format_status()}")
    
    # 1Âª Entrada - Payout 92%
    amount1, status1 = calc.calculate_investment(92)
    print(f"\n1Âª Entrada (Payout 92%):")
    print(f"  InversiÃ³n: ${amount1:.2f} (status: {status1})")
    print(f"  Riesgo: {amount1/41.05*100:.1f}% (lÃ­mite: 10%)")
    
    expected1 = 2.12
    if abs(amount1 - expected1) < 0.15:
        print(f"  âœ… OK: ${amount1:.2f} â‰ˆ ${expected1:.2f}")
    else:
        print(f"  âŒ ERROR: esperado ~${expected1:.2f}, obtenido ${amount1:.2f}")
    
    # Simular pÃ©rdida
    calc.register_loss(amount1)
    new_balance = calc.current_balance
    print(f"\n[PÃ‰RDIDA]")
    print(f"  Nuevo saldo: ${new_balance:.2f}")
    print(f"  Objetivo: ${calc.cycle_target:.2f}")
    print(f"  Status: {calc.format_status()}")
    
    # 2Âª Entrada - Payout 85% (Gale 1)
    amount2, status2 = calc.calculate_investment(85)
    print(f"\nGale 1 (Payout 85%):")
    print(f"  InversiÃ³n: ${amount2:.2f} (status: {status2})")
    print(f"  Riesgo: {amount2/new_balance*100:.1f}% (lÃ­mite: 10%)")
    
    expected2 = 3.61
    if abs(amount2 - expected2) < 0.20:
        print(f"  âœ… OK: ${amount2:.2f} â‰ˆ ${expected2:.2f}")
    else:
        print(f"  âŒ ERROR: esperado ~${expected2:.2f}, obtenido ${amount2:.2f}")


def test_example_3_risk_exceeded():
    """
    Ejemplo 3: Riesgo excesivo detectado
    Saldo $30, LÃ­mite 10% = $3
    Si calcula inversiÃ³n de $5 â†’ RISK_EXCEEDED
    """
    print("\n" + "="*70)
    print("TEST 3: Bloqueo por riesgo excesivo")
    print("="*70)
    
    calc = MartingaleCalculator(current_balance=30.00)
    print(f"Status inicial: {calc.format_status()}")
    
    # SimulaciÃ³n: despuÃ©s de pÃ©rdidas, saldo cae a 27.65
    calc.register_loss(2.35)
    new_balance = calc.current_balance
    print(f"\n[Simulado] Saldo despuÃ©s de pÃ©rdida: ${new_balance:.2f}")
    
    # Intento de inversiÃ³n con payout 80%
    amount, status = calc.calculate_investment(80)
    print(f"\nIntento de inversiÃ³n (Payout 80%):")
    print(f"  InversiÃ³n calculada: ${amount:.2f}")
    print(f"  LÃ­mite 10%: ${new_balance * 0.10:.2f}")
    print(f"  Riesgo: {amount/new_balance*100:.1f}%")
    print(f"  Estado: {status}")
    
    if "RISK_EXCEEDED" in status:
        print(f"  âœ… OK: Bloqueado por exceso de riesgo")
    else:
        print(f"  âŒ ERROR: DeberÃ­a estar bloqueado")


def test_cycle_completion():
    """
    Ciclo completo: Inicio â†’ Ganancia â†’ Nuevo objetivo
    """
    print("\n" + "="*70)
    print("TEST 4: Ciclo completo (Ganancia)")
    print("="*70)
    
    calc = MartingaleCalculator(current_balance=100.00)
    print(f"Status inicial: {calc.format_status()}")
    
    amount, status = calc.calculate_investment(92)
    print(f"\nInversiÃ³n requerida (Payout 92%): ${amount:.2f}")
    
    # Simular ganancia
    calc.register_win(amount, 92)
    print(f"\n[GANANCIA]")
    print(f"Status despuÃ©s de WIN: {calc.format_status()}")
    
    if abs(calc.current_balance - 102.0) < 0.05:
        print(f"  âœ… OK: Saldo alcanzÃ³ objetivo $102.00")
    else:
        print(f"  âŒ ERROR: Saldo deberÃ­a ser ~$102.00, es ${calc.current_balance:.2f}")


def test_reset_by_3_losses():
    """
    Reset automÃ¡tico: 3 pÃ©rdidas seguidas con saldo â‰¤ $50
    """
    print("\n" + "="*70)
    print("TEST 5: Reset automÃ¡tico por 3 pÃ©rdidas (saldo â‰¤ $50)")
    print("="*70)
    
    calc = MartingaleCalculator(current_balance=45.00)
    print(f"Status inicial (saldo â‰¤ $50): {calc.format_status()}")
    
    # 1Âª PÃ©rdida
    calc.register_loss(2.50)
    print(f"\nPÃ©rdida 1: Saldo ${calc.current_balance:.2f}, Gales: {calc.cycle_losses}")
    
    # 2Âª PÃ©rdida
    calc.register_loss(2.50)
    print(f"PÃ©rdida 2: Saldo ${calc.current_balance:.2f}, Gales: {calc.cycle_losses}")
    
    # 3Âª PÃ©rdida â†’ Debe resetear
    calc.register_loss(2.50)
    print(f"PÃ©rdida 3: Saldo ${calc.current_balance:.2f}, Gales: {calc.cycle_losses}")
    
    print(f"\nStatus despuÃ©s de reset: {calc.format_status()}")
    
    if calc.cycle_losses == 0 and calc.cycle_target is not None:
        print(f"  âœ… OK: Ciclo reseteado (nuevas pÃ©rdidas: 0)")
    else:
        print(f"  âŒ ERROR: Ciclo no se resetÃ³ correctamente")


def test_edge_cases():
    """
    Casos lÃ­mite
    """
    print("\n" + "="*70)
    print("TEST 6: Casos lÃ­mite")
    print("="*70)
    
    # Zero balance
    calc = MartingaleCalculator(current_balance=0.0)
    amount, status = calc.calculate_investment(92)
    print(f"Saldo $0: amount=${amount:.2f}, status={status}")
    if amount == 0:
        print(f"  âœ… OK: Retorna $0 en saldo vacÃ­o")
    
    # Monto muy pequeÃ±o
    calc.set_balance(1.10)
    amount, status = calc.calculate_investment(92)
    print(f"\nSaldo $1.10, objetivo $2: amount=${amount:.2f}, status={status}")
    if amount >= 1.00:
        print(f"  âœ… OK: Respeta mÃ­nimo de $1.00")


def main():
    """Ejecutar todas las pruebas."""
    print("\n" + "ðŸ§ª MARTINGALE CALCULATOR - TEST SUITE" + "\n")
    
    try:
        test_example_1()
        test_example_2_gales()
        test_example_3_risk_exceeded()
        test_cycle_completion()
        test_reset_by_3_losses()
        test_edge_cases()
        
        print("\n" + "="*70)
        print("âœ… TODAS LAS PRUEBAS COMPLETADAS")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\nâŒ ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


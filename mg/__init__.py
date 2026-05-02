"""
mg/ — Motor de Gale (Martingale Engine)

Módulo independiente que vigila operaciones abiertas y dispara
una orden de compensación (gale) exactamente 1 segundo antes de que
cierre la vela de 5 minutos, si la operación va en pérdida.

Uso básico:
    from mg.mg_watcher import GaleWatcher, TradeInfo
"""
from mg.mg_watcher import GaleWatcher, TradeInfo

__all__ = ["GaleWatcher", "TradeInfo"]

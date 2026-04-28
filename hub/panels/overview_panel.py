from __future__ import annotations

from ..models import HubSnapshot


def build_overview(snapshot: HubSnapshot) -> list[str]:
    bal_txt = "N/A" if snapshot.balance is None else f"{snapshot.balance:.2f} USD"
    scan_txt = "N/A" if snapshot.scan_no is None else str(snapshot.scan_no)
    assets_txt = "N/A" if snapshot.assets_count is None else str(snapshot.assets_count)
    thr_txt = "N/A" if snapshot.threshold is None else str(snapshot.threshold)

    return [
        f"Hora ultima linea : {snapshot.last_time}",
        f"Nivel log        : {snapshot.level}",
        f"Cuenta           : {snapshot.account_type}",
        f"Balance          : {bal_txt}",
        f"Scan actual      : #{scan_txt}",
        f"Activos en scan  : {assets_txt}",
        f"Umbral sesion    : {thr_txt}",
        f"Estado           : {'OK' if snapshot.level in {'INFO', 'DEBUG'} else 'ALERTA'}",
    ]

"""Métricas sobre un conjunto de transacciones (la carga completa o una vista filtrada).

Las métricas de negocio (conteo por estado y totales por moneda) se calculan
solo con transacciones válidas: sumar montos que no se pudieron interpretar
daría totales falsos.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from .modelo import ESTADOS

CERO = Decimal("0.00")


def calcular_metricas(transacciones: list) -> dict:
    validas = [t for t in transacciones if t.es_valida]
    invalidas = [t for t in transacciones if not t.es_valida]
    total = len(transacciones)

    por_estado = {e: 0 for e in ESTADOS}
    por_moneda = {}
    for t in validas:
        por_estado[t.status] += 1
        m = por_moneda.setdefault(t.currency, {
            "cantidad": 0,
            "total": CERO,
            "por_estado": {e: CERO for e in ESTADOS},
        })
        m["cantidad"] += 1
        m["total"] += t.amount
        m["por_estado"][t.status] += t.amount

    por_fuente = {}
    for t in transacciones:
        f = por_fuente.setdefault(t.source or "(sin fuente)", {"total": 0, "validas": 0, "invalidas": 0})
        f["total"] += 1
        f["validas" if t.es_valida else "invalidas"] += 1

    errores = Counter(e.codigo for t in invalidas for e in t.errores)
    advertencias = Counter(a.codigo for t in transacciones for a in t.advertencias)

    return {
        "total_procesadas": total,
        "validas": len(validas),
        "invalidas": len(invalidas),
        "porcentaje_validas": round(100 * len(validas) / total, 1) if total else 0.0,
        "validas_con_advertencias": sum(1 for t in validas if t.advertencias),
        "por_estado": por_estado,
        "totales_por_moneda": dict(sorted(por_moneda.items())),
        "por_fuente": dict(sorted(por_fuente.items())),
        "errores_por_codigo": dict(errores.most_common()),
        "advertencias_por_codigo": dict(advertencias.most_common()),
    }


def a_json(valor):
    """Convierte Decimal a float (2 decimales) recursivamente para exportar."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [a_json(v) for v in valor]
    return valor

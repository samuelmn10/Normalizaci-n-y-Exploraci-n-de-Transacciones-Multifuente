"""Filtros y ordenamiento sobre transacciones normalizadas (independiente de la interfaz)."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from typing import Optional

VALIDEZ = ("todas", "validas", "invalidas")

CAMPOS_ORDEN = {
    "indice": "N° de registro (orden del archivo)",
    "timestamp": "Fecha",
    "amount": "Monto",
    "id": "ID",
    "source": "Fuente",
    "status": "Estado",
    "currency": "Moneda",
}


@dataclass
class Filtro:
    validez: str = "todas"
    estado: Optional[str] = None
    moneda: Optional[str] = None
    fuente: Optional[str] = None
    desde: Optional[date] = None  # inclusive, fecha UTC
    hasta: Optional[date] = None  # inclusive, fecha UTC
    monto_min: Optional[Decimal] = None
    monto_max: Optional[Decimal] = None
    texto_id: Optional[str] = None
    solo_con_advertencias: bool = False

    @property
    def activo(self) -> bool:
        return self != Filtro()

    def acepta(self, t) -> bool:
        if self.validez == "validas" and not t.es_valida:
            return False
        if self.validez == "invalidas" and t.es_valida:
            return False
        if self.solo_con_advertencias and not t.advertencias:
            return False
        if self.estado and t.status != self.estado:
            return False
        if self.moneda and t.currency != self.moneda:
            return False
        if self.fuente and t.source != self.fuente:
            return False
        if self.desde or self.hasta:
            if t.timestamp is None:
                return False
            dia = t.timestamp.date()
            if (self.desde and dia < self.desde) or (self.hasta and dia > self.hasta):
                return False
        if self.monto_min is not None or self.monto_max is not None:
            if t.amount is None:
                return False
            if (self.monto_min is not None and t.amount < self.monto_min) or (
                self.monto_max is not None and t.amount > self.monto_max
            ):
                return False
        if self.texto_id and (t.id is None or self.texto_id.lower() not in t.id.lower()):
            return False
        return True

    def describir(self) -> str:
        partes = []
        if self.validez != "todas":
            partes.append("solo " + ("válidas" if self.validez == "validas" else "inválidas"))
        if self.solo_con_advertencias:
            partes.append("con advertencias")
        if self.estado:
            partes.append(f"estado={self.estado}")
        if self.moneda:
            partes.append(f"moneda={self.moneda}")
        if self.fuente:
            partes.append(f"fuente={self.fuente}")
        if self.desde or self.hasta:
            partes.append(f"fecha {self.desde or '…'} a {self.hasta or '…'}")
        if self.monto_min is not None or self.monto_max is not None:
            minimo = self.monto_min if self.monto_min is not None else "…"
            maximo = self.monto_max if self.monto_max is not None else "…"
            partes.append(f"monto {minimo} a {maximo}")
        if self.texto_id:
            partes.append(f"id contiene '{self.texto_id}'")
        return ", ".join(partes) or "sin filtros"


def aplicar_filtro(transacciones: list, filtro: Filtro) -> list:
    return [t for t in transacciones if filtro.acepta(t)]


def ordenar(transacciones: list, campo: str = "indice", descendente: bool = False) -> list:
    """Ordena por un campo; los registros sin ese dato quedan siempre al final."""
    if campo not in CAMPOS_ORDEN:
        raise ValueError(f"campo de orden no válido: {campo}")
    con_dato = [t for t in transacciones if getattr(t, campo) is not None]
    sin_dato = [t for t in transacciones if getattr(t, campo) is None]
    con_dato.sort(key=lambda t: getattr(t, campo), reverse=descendente)
    return con_dato + sin_dato


def valores_distintos(transacciones: list, campo: str) -> list:
    return sorted({getattr(t, campo) for t in transacciones if getattr(t, campo) is not None})

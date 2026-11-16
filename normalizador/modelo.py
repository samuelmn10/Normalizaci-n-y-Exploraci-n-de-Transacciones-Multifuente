"""Modelo de datos normalizado.

Esquema de salida de una transacción válida:

    {
      "id":        str    -> identificador tal como lo da la fuente, siempre texto
      "amount":    float  -> monto en unidades (no centavos), 2 decimales
      "currency":  str    -> código ISO 4217 en mayúsculas (USD, EUR, ...)
      "timestamp": str    -> ISO-8601 en UTC, p. ej. "2025-03-10T14:22:00Z"
      "status":    str    -> "SUCCESS" | "FAILED" | "PENDING"
      "source":    str    -> nombre de la fuente detectada (ver config/reglas.json)
    }

Internamente el monto se guarda como Decimal para no perder centavos por
errores de punto flotante; solo se convierte a float al exportar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

ESTADOS = ("SUCCESS", "FAILED", "PENDING")

# Campos del esquema que se obtienen del registro original.
# "source" no viene en el registro: se deduce en la detección de fuente.
CAMPOS_ESQUEMA = ("id", "amount", "currency", "timestamp", "status")


@dataclass(frozen=True)
class Incidencia:
    """Un error (invalida la transacción) o una advertencia (solo la marca)."""

    codigo: str
    mensaje: str
    campo: Optional[str] = None

    def a_dict(self) -> dict:
        return {"codigo": self.codigo, "campo": self.campo, "mensaje": self.mensaje}


@dataclass
class Transaccion:
    """Una transacción después de normalizarla y validarla.

    `indice` es la posición (desde 1) del registro en el archivo de entrada y
    `original` conserva el registro tal como llegó, para poder auditarlo.
    """

    indice: int
    original: Any
    source: Optional[str] = None
    id: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    timestamp: Optional[datetime] = None
    status: Optional[str] = None
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)

    @property
    def es_valida(self) -> bool:
        return not self.errores

    @property
    def timestamp_iso(self) -> Optional[str]:
        if self.timestamp is None:
            return None
        return self.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def tiene_error_en(self, campo: str) -> bool:
        return any(e.campo == campo for e in self.errores)

    def a_esquema(self) -> dict:
        """Representación en el esquema normalizado (la salida oficial)."""
        return {
            "id": self.id,
            "amount": float(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "timestamp": self.timestamp_iso,
            "status": self.status,
            "source": self.source,
        }

    def a_reporte(self) -> dict:
        """Representación de auditoría: normalizado + incidencias + original."""
        return {
            "registro": self.indice,
            "valida": self.es_valida,
            "normalizada": self.a_esquema(),
            "errores": [e.a_dict() for e in self.errores],
            "advertencias": [a.a_dict() for a in self.advertencias],
            "original": self.original,
        }

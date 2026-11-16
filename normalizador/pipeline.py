"""Orquestación: leer archivo -> normalizar -> validar -> exportar."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .metricas import a_json, calcular_metricas
from .normalizacion import normalizar_lote
from .reglas import Reglas
from .validacion import validar_lote


class ErrorEntrada(Exception):
    """El archivo de transacciones no existe o no tiene la estructura esperada."""


@dataclass
class ResultadoProceso:
    ruta: str
    transacciones: list

    @property
    def validas(self) -> list:
        return [t for t in self.transacciones if t.es_valida]

    @property
    def invalidas(self) -> list:
        return [t for t in self.transacciones if not t.es_valida]


def leer_transacciones(ruta) -> list:
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorEntrada(f"No existe el archivo: {ruta}")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ErrorEntrada(f"{ruta.name}: JSON mal formado (línea {e.lineno}, columna {e.colno}): {e.msg}") from None
    except UnicodeDecodeError:
        raise ErrorEntrada(f"{ruta.name}: el archivo no está en UTF-8") from None
    if isinstance(datos, dict):  # se tolera {"transactions": [...]}
        for clave in ("transactions", "transacciones", "data"):
            if isinstance(datos.get(clave), list):
                return datos[clave]
    if not isinstance(datos, list):
        raise ErrorEntrada(f"{ruta.name}: se esperaba un arreglo JSON de transacciones")
    return datos


def procesar(registros: list, reglas: Reglas, ruta: str = "(memoria)", ahora: Optional[datetime] = None) -> ResultadoProceso:
    transacciones = normalizar_lote(registros, reglas)
    validar_lote(transacciones, reglas, ahora)
    return ResultadoProceso(ruta=str(ruta), transacciones=transacciones)


def procesar_archivo(ruta, reglas: Reglas, ahora: Optional[datetime] = None) -> ResultadoProceso:
    return procesar(leer_transacciones(ruta), reglas, str(ruta), ahora)


def exportar(transacciones: list, carpeta) -> dict:
    """Escribe los resultados y devuelve {descripción: ruta}.

    - normalizadas.json / .csv : válidas en el esquema normalizado exacto
    - invalidas.json           : inválidas con su original y los motivos
    - advertencias.json        : válidas marcadas para revisión
    - metricas.json            : métricas del conjunto exportado
    """
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    validas = [t for t in transacciones if t.es_valida]
    salidas = {
        "normalizadas.json": [t.a_esquema() for t in validas],
        "invalidas.json": [t.a_reporte() for t in transacciones if not t.es_valida],
        "advertencias.json": [t.a_reporte() for t in validas if t.advertencias],
        "metricas.json": a_json(calcular_metricas(transacciones)),
    }
    rutas = {}
    for nombre, contenido in salidas.items():
        ruta = carpeta / nombre
        ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
        rutas[nombre] = ruta

    ruta_csv = carpeta / "normalizadas.csv"
    with ruta_csv.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=["id", "amount", "currency", "timestamp", "status", "source"])
        escritor.writeheader()
        for t in validas:
            fila = t.a_esquema()
            fila["amount"] = f"{t.amount:.2f}"
            escritor.writerow(fila)
    rutas["normalizadas.csv"] = ruta_csv
    return rutas

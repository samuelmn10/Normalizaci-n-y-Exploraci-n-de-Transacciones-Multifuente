#!/usr/bin/env python3
"""Punto de entrada.

    python main.py                                  # CLI interactiva con los datos de prueba
    python main.py -e datos/ejemplo_enunciado.json  # otro archivo de entrada
    python main.py --exportar salida                # sin menú: procesa, exporta y resume
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from normalizador.interfaz_cli import InterfazCLI
from normalizador.metricas import calcular_metricas
from normalizador.pipeline import ErrorEntrada, exportar, procesar_archivo
from normalizador.reglas import ErrorReglas, cargar_reglas

BASE = Path(__file__).resolve().parent


def _preparar_consola():
    if os.name == "nt":
        os.system("")  # activa los colores ANSI en la consola de Windows
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _preparar_consola()
    p = argparse.ArgumentParser(description="Normalización y exploración de transacciones multifuente")
    p.add_argument("-e", "--entrada", default=str(BASE / "datos" / "transacciones_prueba.json"),
                   help="archivo JSON de transacciones")
    p.add_argument("-r", "--reglas", default=str(BASE / "config" / "reglas.json"),
                   help="archivo de reglas de normalización")
    p.add_argument("--exportar", metavar="CARPETA",
                   help="modo no interactivo: procesa, exporta a CARPETA y muestra un resumen")
    args = p.parse_args(argv)

    try:
        reglas = cargar_reglas(args.reglas)
    except ErrorReglas as ex:
        print(f"Error en las reglas: {ex}", file=sys.stderr)
        return 2

    if args.exportar:
        try:
            resultado = procesar_archivo(args.entrada, reglas)
        except ErrorEntrada as ex:
            print(f"Error en la entrada: {ex}", file=sys.stderr)
            return 1
        rutas = exportar(resultado.transacciones, args.exportar)
        m = calcular_metricas(resultado.transacciones)
        print(f"{m['total_procesadas']} procesadas: {m['validas']} válidas, {m['invalidas']} inválidas")
        print("Por estado:", ", ".join(f"{k}={v}" for k, v in m["por_estado"].items()))
        print("Totales:", ", ".join(f"{k}={d['total']:,.2f}" for k, d in m["totales_por_moneda"].items()))
        for ruta in rutas.values():
            print(f"  -> {ruta}")
        return 0

    InterfazCLI(reglas, BASE / "datos", BASE / "salida").iniciar(args.entrada)
    return 0


if __name__ == "__main__":
    sys.exit(main())

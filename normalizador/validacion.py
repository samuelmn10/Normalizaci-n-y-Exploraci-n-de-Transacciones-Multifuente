"""Validación: decide qué transacciones normalizadas son válidas.

Política para registros con problemas: **marcar y separar** (no descartar).
  * Error       -> la transacción queda inválida: se excluye de las métricas de
                   negocio y se exporta aparte con su registro original y motivos.
  * Advertencia -> la transacción sigue siendo válida, pero queda marcada para
                   revisión humana.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .modelo import CAMPOS_ESQUEMA, Incidencia, Transaccion
from .reglas import Reglas

# código -> (severidad, descripción). Es la referencia que muestra la CLI.
CATALOGO = {
    "FORMATO_REGISTRO": ("error", "El elemento del arreglo no es un objeto JSON."),
    "FUENTE_DESCONOCIDA": ("error", "Las claves del registro no corresponden a ninguna fuente configurada."),
    "FUENTE_AMBIGUA": ("error", "El registro coincide por igual con más de una fuente."),
    "CAMPO_FALTANTE": ("error", "Falta un campo obligatorio o viene vacío."),
    "ID_INVALIDO": ("error", "El identificador no es texto ni número entero."),
    "ID_DUPLICADO": ("error", "El ID ya apareció antes en la misma fuente (se conserva la primera aparición)."),
    "MONTO_INVALIDO": ("error", "El monto no se puede interpretar con las reglas de su fuente."),
    "MONTO_NO_POSITIVO": ("error", "El monto no supera el mínimo configurado (debe ser > 0)."),
    "MONTO_EXCEDE_MAXIMO": ("error", "El monto supera el máximo permitido."),
    "MONEDA_INVALIDA": ("error", "La moneda no es un código de 3 letras ni un alias conocido."),
    "MONEDA_NO_SOPORTADA": ("error", "La moneda no está en la lista de monedas soportadas."),
    "MONEDA_CONFLICTO": ("error", "El campo de moneda y el símbolo del monto indican monedas distintas."),
    "FECHA_INVALIDA": ("error", "La fecha no coincide con ningún formato configurado para su fuente."),
    "ESTADO_DESCONOCIDO": ("error", "El estado no aparece en el mapeo de estados."),
    "FECHA_FUTURA": ("advertencia/error", "Fecha posterior al procesamiento (error si rechazar_fechas_futuras = true)."),
    "MONTO_REDONDEADO": ("advertencia", "El monto tenía más decimales de los permitidos y se redondeó."),
    "MONEDA_SUPUESTA": ("advertencia", "La moneda se dedujo de un símbolo ambiguo ($)."),
    "POSIBLE_DUPLICADO": ("advertencia", "Otra fuente reporta el mismo monto, moneda y fecha."),
}


def validar_transaccion(tx: Transaccion, reglas: Reglas, ahora: datetime) -> None:
    if tx.source is None:
        return  # ya tiene un error de formato o de fuente; no hay más que revisar
    regla = reglas.fuentes[tx.source]

    # 1. Campos obligatorios (solo si el campo no tiene ya un error de formato)
    for campo in CAMPOS_ESQUEMA:
        if getattr(tx, campo) is None and not tx.tiene_error_en(campo):
            if campo == "currency" and "currency" not in regla.campos and tx.tiene_error_en("amount"):
                continue  # la moneda venía en el monto, que ya está reportado como inválido
            tx.errores.append(Incidencia("CAMPO_FALTANTE", _motivo_faltante(tx, campo, regla.campos.get(campo)), campo))

    # 2. Reglas de negocio sobre valores ya normalizados
    if tx.amount is not None:
        if tx.amount <= reglas.monto_minimo_exclusivo:
            tx.errores.append(Incidencia(
                "MONTO_NO_POSITIVO", f"{tx.amount} debe ser mayor que {reglas.monto_minimo_exclusivo}", "amount"))
        elif reglas.monto_maximo is not None and tx.amount > reglas.monto_maximo:
            tx.errores.append(Incidencia(
                "MONTO_EXCEDE_MAXIMO", f"{tx.amount} supera el máximo de {reglas.monto_maximo}", "amount"))

    if tx.currency is not None and tx.currency not in reglas.monedas_soportadas:
        tx.errores.append(Incidencia(
            "MONEDA_NO_SOPORTADA",
            f"{tx.currency} no está entre las soportadas ({', '.join(sorted(reglas.monedas_soportadas))})",
            "currency"))

    if tx.timestamp is not None and tx.timestamp > ahora:
        incidencia = Incidencia("FECHA_FUTURA", f"{tx.timestamp_iso} es posterior al momento del procesamiento", "timestamp")
        (tx.errores if reglas.rechazar_fechas_futuras else tx.advertencias).append(incidencia)


def _motivo_faltante(tx: Transaccion, campo: str, origen: Optional[str]) -> str:
    if origen is None:
        if campo == "currency":
            return "la fuente no trae campo de moneda y el monto no incluye símbolo ni código"
        return f"la fuente no tiene mapeado el campo '{campo}'"
    if origen not in tx.original:
        return f"no existe el campo '{origen}'"
    return f"el campo '{origen}' está vacío"


def marcar_ids_duplicados(transacciones: list) -> None:
    """El ID es único dentro de cada fuente; la primera aparición es la que vale."""
    vistos = {}
    for tx in transacciones:
        if tx.source is None or tx.id is None:
            continue
        clave = (tx.source, tx.id)
        if clave in vistos:
            tx.errores.append(Incidencia(
                "ID_DUPLICADO", f"el ID '{tx.id}' de {tx.source} ya aparece en el registro #{vistos[clave]}", "id"))
        else:
            vistos[clave] = tx.indice


def marcar_posibles_duplicados(transacciones: list) -> None:
    """Misma operación reportada por dos fuentes: igual monto, moneda e instante.

    No se invalida (pueden ser dos cobros legítimos), solo se avisa.
    """
    primeras = {}
    for tx in transacciones:
        if not tx.es_valida:
            continue
        clave = (tx.amount, tx.currency, tx.timestamp)
        previa = primeras.get(clave)
        if previa is None:
            primeras[clave] = tx
        elif previa.source != tx.source:
            tx.advertencias.append(Incidencia(
                "POSIBLE_DUPLICADO",
                f"coincide en monto, moneda y fecha con el registro #{previa.indice} ({previa.source})"))


def validar_lote(transacciones: list, reglas: Reglas, ahora: Optional[datetime] = None) -> list:
    ahora = ahora or datetime.now(timezone.utc)
    for tx in transacciones:
        validar_transaccion(tx, reglas, ahora)
    marcar_ids_duplicados(transacciones)
    if reglas.detectar_duplicados_entre_fuentes:
        marcar_posibles_duplicados(transacciones)
    return transacciones

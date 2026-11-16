"""Normalización: detecta la fuente de cada registro y lleva sus campos al esquema común.

Este módulo solo *interpreta formatos*. Si un valor no se puede interpretar,
registra un error en ese campo y lo deja vacío. Decidir si la transacción es
válida (campos obligatorios, rangos, duplicados) le corresponde a validacion.py.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from .modelo import Incidencia, Transaccion
from .reglas import FORMATO_ISO, ReglaFuente, Reglas


class ErrorNormalizacion(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje

    def a_incidencia(self, campo: Optional[str] = None) -> Incidencia:
        return Incidencia(self.codigo, self.mensaje, campo)


def es_vacio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


# --------------------------------------------------------------------------- #
# Detección de fuente
# --------------------------------------------------------------------------- #
def detectar_fuente(registro: dict, reglas: Reglas) -> str:
    """Elige la fuente cuyas claves coinciden mejor con las del registro.

    1. Si el registro trae "source" con el nombre de una fuente configurada, se usa.
    2. Si no, se calcula qué fracción de los campos de cada fuente aparece en el
       registro. Gana la mayor, siempre que supere el umbral y no haya empate.
    """
    declarada = registro.get("source")
    if isinstance(declarada, str) and declarada.strip() in reglas.fuentes:
        return declarada.strip()

    claves = set(registro) - {"source"}
    puntajes = []
    for nombre, regla in reglas.fuentes.items():
        esperadas = set(regla.campos.values())
        puntajes.append((len(claves & esperadas) / len(esperadas), nombre))
    puntajes.sort(key=lambda p: p[0], reverse=True)

    mejor, nombre = puntajes[0]
    if mejor < reglas.umbral_deteccion:
        raise ErrorNormalizacion(
            "FUENTE_DESCONOCIDA",
            f"las claves {sorted(claves)} no coinciden con ninguna fuente configurada",
        )
    empatadas = [n for p, n in puntajes if p == mejor]
    if len(empatadas) > 1:
        raise ErrorNormalizacion("FUENTE_AMBIGUA", f"el registro coincide por igual con {empatadas}")
    return nombre


# --------------------------------------------------------------------------- #
# Campos individuales
# --------------------------------------------------------------------------- #
def normalizar_id(valor) -> str:
    if isinstance(valor, bool):
        raise ErrorNormalizacion("ID_INVALIDO", f"{valor!r} no es un identificador")
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    if isinstance(valor, str):
        return valor.strip()
    raise ErrorNormalizacion("ID_INVALIDO", f"{valor!r} no es texto ni número entero")


_CODIGO_AL_INICIO = re.compile(r"^([A-Za-z]{3})\s*(.*)$")
_CODIGO_AL_FINAL = re.compile(r"^(.*?)\s*([A-Za-z]{3})$")


def separar_moneda(texto: str, reglas: Reglas) -> tuple:
    """Separa un símbolo o código de moneda pegado al monto.

    "€99,99" -> ("99,99", "EUR", False);  "$10" -> ("10", "USD", True)  (ambiguo)
    "15,5 EUR" -> ("15,5", "EUR", False); "100.50" -> ("100.50", None, False)
    """
    t = texto.strip()
    mayus = t.upper()
    for alias in sorted(reglas.alias_moneda, key=len, reverse=True):  # "US$" antes que "$"
        ambiguo = alias in reglas.alias_ambiguos
        if mayus.startswith(alias):
            return t[len(alias):].strip(), reglas.alias_moneda[alias], ambiguo
        if mayus.endswith(alias):
            return t[: len(t) - len(alias)].strip(), reglas.alias_moneda[alias], ambiguo
    m = _CODIGO_AL_INICIO.match(t)
    if m:
        return m.group(2).strip(), m.group(1).upper(), False
    m = _CODIGO_AL_FINAL.match(t)
    if m:
        return m.group(1).strip(), m.group(2).upper(), False
    return t, None, False


def texto_a_decimal(texto: str, separador_decimal: str) -> Decimal:
    """Convierte texto numérico según el separador decimal de la fuente.

    Los separadores de miles se aceptan solo en grupos de 3 dígitos, así
    "1,250.75" (punto decimal) o "1.234,50" (coma decimal) son válidos, pero
    "100.50" en una fuente de coma decimal se rechaza en vez de adivinarse.
    """
    t = texto.replace(" ", "").replace(" ", "")
    signo = ""
    if t[:1] in ("+", "-"):
        signo = "-" if t[0] == "-" else ""
        t = t[1:]
    miles = "," if separador_decimal == "." else "."
    sep_re, miles_re = re.escape(separador_decimal), re.escape(miles)
    patron = rf"\d{{1,3}}(?:{miles_re}\d{{3}})+(?:{sep_re}\d+)?|\d+(?:{sep_re}\d+)?"
    if not re.fullmatch(patron, t):
        raise ErrorNormalizacion(
            "MONTO_INVALIDO",
            f"'{texto}' no es un número válido (separador decimal de la fuente: '{separador_decimal}')",
        )
    return Decimal(signo + t.replace(miles, "").replace(separador_decimal, "."))


def normalizar_monto(valor, regla: ReglaFuente, reglas: Reglas) -> tuple:
    """Devuelve (monto, moneda_en_el_monto, moneda_ambigua, fue_redondeado)."""
    moneda, ambigua = None, False
    if isinstance(valor, bool):
        raise ErrorNormalizacion("MONTO_INVALIDO", f"{valor!r} no es un monto")
    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and not math.isfinite(valor):
            raise ErrorNormalizacion("MONTO_INVALIDO", f"{valor!r} no es un número finito")
        numero = Decimal(str(valor))
    elif isinstance(valor, str):
        resto, moneda, ambigua = separar_moneda(valor, reglas)
        if not resto:
            raise ErrorNormalizacion("MONTO_INVALIDO", f"'{valor}' no contiene un número")
        try:
            numero = texto_a_decimal(resto, regla.separador_decimal)
        except ErrorNormalizacion:
            raise ErrorNormalizacion(
                "MONTO_INVALIDO",
                f"'{valor}' no es un monto válido (separador decimal de la fuente: '{regla.separador_decimal}')",
            ) from None
    else:
        raise ErrorNormalizacion("MONTO_INVALIDO", f"tipo no soportado para un monto: {type(valor).__name__}")

    if regla.unidad_monto == "centavos":
        if numero != numero.to_integral_value():
            raise ErrorNormalizacion(
                "MONTO_INVALIDO",
                f"la fuente '{regla.nombre}' reporta centavos enteros y se recibió {valor!r}",
            )
        numero = numero / 100

    try:
        redondeado = numero.quantize(Decimal(1).scaleb(-reglas.decimales), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ErrorNormalizacion("MONTO_INVALIDO", f"{valor!r} está fuera de rango") from None
    return redondeado, moneda, ambigua, redondeado != numero


def normalizar_moneda(valor, reglas: Reglas) -> str:
    if not isinstance(valor, str):
        raise ErrorNormalizacion("MONEDA_INVALIDA", f"{valor!r} no es un código de moneda")
    t = valor.strip().upper()
    if t in reglas.alias_moneda:
        return reglas.alias_moneda[t]
    if not re.fullmatch(r"[A-Z]{3}", t):
        raise ErrorNormalizacion("MONEDA_INVALIDA", f"'{valor}' no es un código ISO 4217 ni un alias conocido")
    return t


def _parsear_iso(texto: str) -> datetime:
    if texto[-1:] in ("Z", "z"):
        texto = texto[:-1] + "+00:00"
    return datetime.fromisoformat(texto)


def normalizar_fecha(valor, regla: ReglaFuente) -> datetime:
    """Prueba los formatos de la fuente en orden. Sin zona -> zona de la fuente. Resultado en UTC."""
    if not isinstance(valor, str):
        raise ErrorNormalizacion("FECHA_INVALIDA", f"se esperaba texto y se recibió {valor!r}")
    texto = valor.strip()
    for formato in regla.formatos_fecha:
        try:
            fecha = _parsear_iso(texto) if formato == FORMATO_ISO else datetime.strptime(texto, formato)
        except ValueError:
            continue
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=regla.zona)
        return fecha.astimezone(timezone.utc)
    raise ErrorNormalizacion(
        "FECHA_INVALIDA",
        f"'{valor}' no coincide con los formatos de '{regla.nombre}': {', '.join(regla.formatos_fecha)}",
    )


def normalizar_estado(valor, reglas: Reglas) -> str:
    if isinstance(valor, str):
        destino = reglas.mapa_estados.get(valor.strip().lower())
        if destino:
            return destino
    raise ErrorNormalizacion("ESTADO_DESCONOCIDO", f"{valor!r} no está en el mapeo de estados")


# --------------------------------------------------------------------------- #
# Registro completo
# --------------------------------------------------------------------------- #
def normalizar_registro(indice: int, registro, reglas: Reglas) -> Transaccion:
    tx = Transaccion(indice=indice, original=registro)
    if not isinstance(registro, dict):
        tipo = "null" if registro is None else type(registro).__name__
        tx.errores.append(Incidencia("FORMATO_REGISTRO", f"se esperaba un objeto JSON y se recibió {tipo}"))
        return tx

    try:
        tx.source = detectar_fuente(registro, reglas)
    except ErrorNormalizacion as e:
        tx.errores.append(e.a_incidencia())
        return tx
    regla = reglas.fuentes[tx.source]

    def convertir(campo, funcion):
        origen = regla.campos.get(campo)
        valor = registro.get(origen) if origen else None
        if es_vacio(valor):
            return None  # si falta o no, lo decide la validación
        try:
            return funcion(valor)
        except ErrorNormalizacion as e:
            tx.errores.append(e.a_incidencia(campo))
            return None

    tx.id = convertir("id", normalizar_id)
    tx.timestamp = convertir("timestamp", lambda v: normalizar_fecha(v, regla))
    tx.status = convertir("status", lambda v: normalizar_estado(v, reglas))
    moneda_campo = convertir("currency", lambda v: normalizar_moneda(v, reglas))
    resultado_monto = convertir("amount", lambda v: normalizar_monto(v, regla, reglas))

    moneda_monto, ambigua = None, False
    if resultado_monto is not None:
        tx.amount, moneda_monto, ambigua, redondeado = resultado_monto
        if redondeado:
            original = registro.get(regla.campos["amount"])
            tx.advertencias.append(Incidencia(
                "MONTO_REDONDEADO", f"{original!r} se redondeó a {tx.amount} ({reglas.decimales} decimales)", "amount"))

    if not tx.tiene_error_en("currency"):
        tx.currency = _resolver_moneda(tx, moneda_campo, moneda_monto, ambigua)
    return tx


def _resolver_moneda(tx: Transaccion, moneda_campo, moneda_monto, ambigua: bool):
    """Regla: el campo de moneda explícito manda; el símbolo del monto lo complementa."""
    if moneda_campo and moneda_monto and moneda_campo != moneda_monto:
        if ambigua:
            return moneda_campo  # "$" puede ser USD o MXN: se respeta el campo explícito
        tx.errores.append(Incidencia(
            "MONEDA_CONFLICTO", f"el campo de moneda dice {moneda_campo} pero el monto trae {moneda_monto}", "currency"))
        return None
    if moneda_campo:
        return moneda_campo
    if moneda_monto and ambigua:
        tx.advertencias.append(Incidencia(
            "MONEDA_SUPUESTA", f"la moneda se dedujo de un símbolo ambiguo; se asumió {moneda_monto}", "currency"))
    return moneda_monto


def normalizar_lote(registros: list, reglas: Reglas) -> list:
    return [normalizar_registro(i, r, reglas) for i, r in enumerate(registros, start=1)]

"""Carga y verificación del archivo de reglas (config/reglas.json).

Las reglas se validan al cargarlas: si el archivo es incoherente (por ejemplo,
un alias que apunta a una moneda no soportada o un estado mapeado a dos
destinos) el programa se detiene con un mensaje claro en lugar de producir
datos mal normalizados.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from .modelo import CAMPOS_ESQUEMA, ESTADOS

FORMATO_ISO = "ISO8601"
UNIDADES_MONTO = ("unidades", "centavos")
SEPARADORES_DECIMALES = (".", ",")
CAMPOS_OBLIGATORIOS_EN_FUENTE = ("id", "amount", "timestamp", "status")  # currency puede venir en el monto

_FALTA = object()


class ErrorReglas(Exception):
    """El archivo de reglas no existe, no es JSON válido o es incoherente."""


@dataclass(frozen=True)
class ReglaFuente:
    nombre: str
    descripcion: str
    campos: dict  # campo normalizado -> nombre del campo en la fuente
    unidad_monto: str
    separador_decimal: str
    formatos_fecha: tuple
    zona_nombre: str
    zona: tzinfo


@dataclass(frozen=True)
class Reglas:
    ruta: str
    fuentes: dict
    monedas_soportadas: frozenset
    alias_moneda: dict  # alias en MAYÚSCULAS -> código ISO
    alias_ambiguos: frozenset
    mapa_estados: dict  # variante en minúsculas -> SUCCESS/FAILED/PENDING
    umbral_deteccion: float
    decimales: int
    monto_minimo_exclusivo: Decimal
    monto_maximo: Optional[Decimal]
    rechazar_fechas_futuras: bool
    detectar_duplicados_entre_fuentes: bool

    def variantes_de(self, estado: str) -> list:
        return sorted(k for k, v in self.mapa_estados.items() if v == estado)


def cargar_reglas(ruta) -> Reglas:
    ruta = Path(ruta)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErrorReglas(f"No se encontró el archivo de reglas: {ruta}") from None
    except json.JSONDecodeError as e:
        raise ErrorReglas(f"{ruta}: JSON inválido (línea {e.lineno}, columna {e.colno}): {e.msg}") from None
    if not isinstance(datos, dict):
        raise ErrorReglas(f"{ruta}: la raíz del archivo de reglas debe ser un objeto")
    return construir_reglas(datos, str(ruta))


def construir_reglas(datos: dict, ruta: str = "(memoria)") -> Reglas:
    # ---- Monedas ----
    monedas = _obtener(datos, "monedas", dict, "raíz")
    soportadas = frozenset(str(m).strip().upper() for m in _obtener(monedas, "soportadas", list, "monedas"))
    if not soportadas:
        raise ErrorReglas("monedas.soportadas no puede estar vacía")
    for m in soportadas:
        if not re.fullmatch(r"[A-Z]{3}", m):
            raise ErrorReglas(f"monedas.soportadas: '{m}' no es un código ISO 4217 de 3 letras")

    alias = {}
    for clave, destino in _obtener(monedas, "alias", dict, "monedas", {}).items():
        destino = str(destino).strip().upper()
        if destino not in soportadas:
            raise ErrorReglas(f"monedas.alias: '{clave}' apunta a '{destino}', que no está en monedas.soportadas")
        alias[clave.strip().upper()] = destino
    ambiguos = frozenset(str(a).strip().upper() for a in _obtener(monedas, "alias_ambiguos", list, "monedas", []))
    for a in ambiguos:
        if a not in alias:
            raise ErrorReglas(f"monedas.alias_ambiguos: '{a}' no está definido en monedas.alias")

    # ---- Estados ----
    mapa_estados = {}
    for destino, variantes in _obtener(datos, "estados", dict, "raíz").items():
        if destino not in ESTADOS:
            raise ErrorReglas(f"estados: '{destino}' no es un estado normalizado ({', '.join(ESTADOS)})")
        if not isinstance(variantes, list):
            raise ErrorReglas(f"estados.{destino} debe ser una lista")
        for variante in [*variantes, destino]:  # el valor canónico siempre se acepta
            v = str(variante).strip().lower()
            if mapa_estados.get(v, destino) != destino:
                raise ErrorReglas(f"estados: '{variante}' está mapeado a {mapa_estados[v]} y a {destino}")
            mapa_estados[v] = destino

    # ---- Fechas, detección y validación ----
    fechas = _obtener(datos, "fechas", dict, "raíz", {})
    formatos_defecto = _obtener(fechas, "formatos_por_defecto", list, "fechas", [FORMATO_ISO])
    zona_defecto = _obtener(fechas, "zona_horaria_por_defecto", str, "fechas", "UTC")

    deteccion = _obtener(datos, "deteccion", dict, "raíz", {})
    umbral = float(_obtener(deteccion, "umbral_coincidencia", (int, float), "deteccion", 0.6))
    if not 0 < umbral <= 1:
        raise ErrorReglas("deteccion.umbral_coincidencia debe estar entre 0 (excluido) y 1")

    val = _obtener(datos, "validacion", dict, "raíz", {})
    decimales = _obtener(val, "decimales", int, "validacion", 2)
    minimo = _decimal(_obtener(val, "monto_minimo_exclusivo", (int, float, str), "validacion", 0), "validacion.monto_minimo_exclusivo")
    maximo_cfg = val.get("monto_maximo")
    maximo = None if maximo_cfg is None else _decimal(maximo_cfg, "validacion.monto_maximo")

    # ---- Fuentes ----
    fuentes_cfg = _obtener(datos, "fuentes", dict, "raíz")
    if not fuentes_cfg:
        raise ErrorReglas("Debe definirse al menos una fuente en 'fuentes'")
    fuentes = {}
    for nombre, cfg in fuentes_cfg.items():
        ctx = f"fuentes.{nombre}"
        if not isinstance(cfg, dict):
            raise ErrorReglas(f"{ctx} debe ser un objeto")
        campos = _obtener(cfg, "campos", dict, ctx)
        desconocidos = set(campos) - set(CAMPOS_ESQUEMA)
        if desconocidos:
            raise ErrorReglas(f"{ctx}.campos: campos no reconocidos {sorted(desconocidos)}; válidos: {list(CAMPOS_ESQUEMA)}")
        faltan = [c for c in CAMPOS_OBLIGATORIOS_EN_FUENTE if c not in campos]
        if faltan:
            raise ErrorReglas(f"{ctx}.campos: falta mapear {faltan}")
        monto = _obtener(cfg, "monto", dict, ctx, {})
        unidad = monto.get("unidad", "unidades")
        if unidad not in UNIDADES_MONTO:
            raise ErrorReglas(f"{ctx}.monto.unidad debe ser una de {UNIDADES_MONTO}")
        separador = monto.get("separador_decimal", ".")
        if separador not in SEPARADORES_DECIMALES:
            raise ErrorReglas(f"{ctx}.monto.separador_decimal debe ser '.' o ','")
        formatos = tuple(_obtener(cfg, "formatos_fecha", list, ctx, formatos_defecto))
        if not formatos:
            raise ErrorReglas(f"{ctx}.formatos_fecha no puede estar vacía")
        zona_nombre = _obtener(cfg, "zona_horaria", str, ctx, zona_defecto)
        fuentes[nombre] = ReglaFuente(
            nombre=nombre,
            descripcion=cfg.get("descripcion", ""),
            campos=dict(campos),
            unidad_monto=unidad,
            separador_decimal=separador,
            formatos_fecha=formatos,
            zona_nombre=zona_nombre,
            zona=resolver_zona(zona_nombre, ctx),
        )

    return Reglas(
        ruta=ruta,
        fuentes=fuentes,
        monedas_soportadas=soportadas,
        alias_moneda=alias,
        alias_ambiguos=ambiguos,
        mapa_estados=mapa_estados,
        umbral_deteccion=umbral,
        decimales=decimales,
        monto_minimo_exclusivo=minimo,
        monto_maximo=maximo,
        rechazar_fechas_futuras=bool(val.get("rechazar_fechas_futuras", False)),
        detectar_duplicados_entre_fuentes=bool(val.get("detectar_duplicados_entre_fuentes", True)),
    )


def resolver_zona(nombre: str, contexto: str = "zona") -> tzinfo:
    """Acepta 'UTC', desfases fijos como '-06:00' o nombres IANA como 'America/El_Salvador'."""
    if nombre.strip().upper() in ("UTC", "Z"):
        return timezone.utc
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", nombre.strip())
    if m:
        signo = 1 if m.group(1) == "+" else -1
        return timezone(signo * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(nombre)
    except Exception:
        raise ErrorReglas(
            f"{contexto}: zona horaria desconocida '{nombre}'. Use 'UTC', un desfase como '-06:00' "
            "o un nombre IANA (en Windows los nombres IANA requieren 'pip install tzdata')."
        ) from None


def _obtener(d: dict, clave: str, tipo, contexto: str, defecto=_FALTA):
    if clave not in d:
        if defecto is not _FALTA:
            return defecto
        raise ErrorReglas(f"Falta la clave '{clave}' en {contexto}")
    valor = d[clave]
    if not isinstance(valor, tipo) or isinstance(valor, bool) and tipo is not bool:
        raise ErrorReglas(f"'{contexto}.{clave}' tiene un tipo incorrecto ({type(valor).__name__})")
    return valor


def _decimal(valor, contexto: str) -> Decimal:
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        raise ErrorReglas(f"{contexto}: '{valor}' no es un número") from None

"""Interfaz de línea de comandos interactiva: menús, filtros, vistas y métricas.

Solo presenta datos y pide opciones. La lógica vive en los demás módulos
(normalizacion, validacion, metricas, consultas, pipeline).
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .consultas import CAMPOS_ORDEN, Filtro, aplicar_filtro, ordenar, valores_distintos
from .metricas import calcular_metricas
from .modelo import ESTADOS
from .pipeline import ErrorEntrada, exportar, procesar_archivo
from .reglas import ErrorReglas, Reglas, cargar_reglas
from .validacion import CATALOGO

TAMANO_PAGINA = 15
ANCHO = 78
_SIN_CAMBIO = object()


class _Salir(Exception):
    """Señal interna para cerrar la aplicación."""


# --------------------------------------------------------------------------- #
# Utilidades de presentación
# --------------------------------------------------------------------------- #
class Estilo:
    def __init__(self):
        self.activo = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def _c(self, codigo, texto):
        return f"\033[{codigo}m{texto}\033[0m" if self.activo else texto

    def negrita(self, t): return self._c("1", t)
    def tenue(self, t): return self._c("2", t)
    def verde(self, t): return self._c("32", t)
    def rojo(self, t): return self._c("31", t)
    def amarillo(self, t): return self._c("33", t)
    def cian(self, t): return self._c("36", t)

    def estado(self, estado, texto=None):
        texto = texto if texto is not None else (estado or "—")
        return {"SUCCESS": self.verde, "FAILED": self.rojo, "PENDING": self.amarillo}.get(estado, str)(texto)


def recortar(texto: str, ancho: int) -> str:
    return texto if len(texto) <= ancho else texto[: ancho - 1] + "…"


def guion(valor) -> str:
    return "—" if valor is None or valor == "" else str(valor)


def fmt_monto(monto) -> str:
    return "—" if monto is None else f"{monto:,.2f}"


def fmt_fecha(tx) -> str:
    return "—" if tx.timestamp is None else tx.timestamp.strftime("%Y-%m-%d %H:%M")


def ruta_corta(ruta) -> str:
    """Muestra la ruta relativa a la carpeta actual cuando es posible."""
    try:
        return str(Path(ruta).resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(ruta)


def barra(valor, total, ancho=24) -> str:
    llenos = round(ancho * valor / total) if total else 0
    return "█" * llenos + "░" * (ancho - llenos)


def tabla(encabezados, filas, alinear=None, colorear=None, ancho_max=42, estilo=None) -> str:
    """Tabla de texto. alinear: 'i'/'d' por columna. colorear(fila, col, texto) -> texto."""
    n = len(encabezados)
    alinear = alinear or "i" * n
    filas = [[recortar(str(c), ancho_max) for c in fila] for fila in filas]
    anchos = [max([len(encabezados[i])] + [len(f[i]) for f in filas]) for i in range(n)]

    def celda(texto, i):
        return texto.rjust(anchos[i]) if alinear[i] == "d" else texto.ljust(anchos[i])

    cabecera = " │ ".join(celda(h, i) for i, h in enumerate(encabezados))
    lineas = ["  " + (estilo.negrita(cabecera) if estilo else cabecera),
              "  " + "─┼─".join("─" * a for a in anchos)]
    for r, fila in enumerate(filas):
        partes = []
        for i, c in enumerate(fila):
            texto = celda(c, i)
            partes.append(colorear(r, i, texto) if colorear else texto)
        lineas.append("  " + " │ ".join(partes))
    return "\n".join(lineas)


# --------------------------------------------------------------------------- #
# Aplicación
# --------------------------------------------------------------------------- #
class InterfazCLI:
    def __init__(self, reglas: Reglas, carpeta_datos: Path, carpeta_salida: Path):
        self.reglas = reglas
        self.carpeta_datos = Path(carpeta_datos)
        self.carpeta_salida = Path(carpeta_salida)
        self.resultado = None
        self.filtro = Filtro()
        self.orden = ("indice", False)
        self.e = Estilo()

    # ---------------- ciclo principal ----------------
    def iniciar(self, ruta_inicial=None):
        if ruta_inicial:
            self._cargar(ruta_inicial)
        try:
            while True:
                self._menu_principal()
        except (_Salir, KeyboardInterrupt):
            print("\n  Hasta luego.")

    def _leer(self, mensaje: str) -> str:
        try:
            return input(mensaje).strip()
        except EOFError:
            raise _Salir from None

    def _pausa(self):
        self._leer(self.e.tenue("\n  Enter para continuar..."))

    def _titulo(self, texto: str):
        print("\n" + self.e.negrita(f"  ── {texto} " + "─" * max(0, ANCHO - len(texto) - 6)))

    def _menu_principal(self):
        print("\n" + self.e.negrita("═" * ANCHO))
        print(self.e.negrita("  NORMALIZADOR DE TRANSACCIONES MULTIFUENTE"))
        print(self.e.negrita("═" * ANCHO))
        if self.resultado:
            r = self.resultado
            validas, invalidas = len(r.validas), len(r.invalidas)
            print(f"  Archivo : {ruta_corta(r.ruta)}")
            print(f"  Registros: {len(r.transacciones)}  │  "
                  f"{self.e.verde(str(validas) + ' válidas')}  │  {self.e.rojo(str(invalidas) + ' inválidas')}")
            campo, desc = self.orden
            print(f"  Vista   : {self.filtro.describir()}  │  orden: {CAMPOS_ORDEN[campo]}"
                  f"{' ↓' if desc else ' ↑'}  │  {len(self._vista())} en vista")
        else:
            print(self.e.amarillo("  Sin archivo cargado. Use la opción 8."))
        print()

        opciones = [
            ("1", "Listar transacciones (vista actual)", self._listar),
            ("2", "Filtrar", self._menu_filtros),
            ("3", "Ordenar", self._menu_orden),
            ("4", "Ver detalle de un registro (original vs. normalizado)", self._pedir_detalle),
            ("5", "Ver inválidas y sus motivos", self._ver_invalidas),
            ("6", "Métricas", self._metricas),
            ("7", "Exportar resultados", self._exportar),
            ("8", "Cargar otro archivo", self._cargar_interactivo),
            ("9", "Ver / recargar reglas de normalización", self._ver_reglas),
            ("0", "Salir", None),
        ]
        for clave, texto, _ in opciones:
            print(f"   {self.e.cian(clave)}. {texto}")
        op = self._leer("\n  Opción: ")
        if op == "0":
            raise _Salir
        accion = next((a for c, _, a in opciones if c == op), None)
        if accion is None:
            print(self.e.rojo("  Opción no válida."))
        elif self.resultado is None and op not in ("8", "9"):
            print(self.e.amarillo("  Primero cargue un archivo (opción 8)."))
        else:
            accion()

    def _vista(self) -> list:
        return ordenar(aplicar_filtro(self.resultado.transacciones, self.filtro), *self.orden)

    def _buscar(self, indice: int):
        return next((t for t in self.resultado.transacciones if t.indice == indice), None)

    # ---------------- carga ----------------
    def _cargar(self, ruta) -> bool:
        try:
            self.resultado = procesar_archivo(ruta, self.reglas)
        except ErrorEntrada as ex:
            print(self.e.rojo(f"  ✖ No se pudo cargar: {ex}"))
            return False
        self.filtro = Filtro()
        r = self.resultado
        print(self.e.verde(f"  ✔ {ruta_corta(r.ruta)}: {len(r.transacciones)} registros "
                           f"({len(r.validas)} válidas, {len(r.invalidas)} inválidas)"))
        return True

    def _cargar_interactivo(self):
        self._titulo("Cargar archivo")
        archivos = sorted(self.carpeta_datos.glob("*.json")) if self.carpeta_datos.is_dir() else []
        for i, a in enumerate(archivos, 1):
            print(f"   {self.e.cian(str(i))}. {a.name}")
        txt = self._leer("\n  Número de la lista o ruta a un .json (Enter = cancelar): ")
        if not txt:
            return
        if txt.isdigit() and 1 <= int(txt) <= len(archivos):
            ruta = archivos[int(txt) - 1]
        else:
            ruta = Path(txt.strip('"\'')).expanduser()
        self._cargar(ruta)
        self._pausa()

    # ---------------- listado ----------------
    def _tabla_transacciones(self, txs) -> str:
        filas = []
        for t in txs:
            if t.errores:
                obs = "✖ " + t.errores[0].codigo + (f" +{len(t.errores) - 1}" if len(t.errores) > 1 else "")
            elif t.advertencias:
                obs = "⚠ " + t.advertencias[0].codigo + (f" +{len(t.advertencias) - 1}" if len(t.advertencias) > 1 else "")
            else:
                obs = "✔"
            filas.append([str(t.indice), guion(t.source), guion(t.id), fmt_monto(t.amount),
                          guion(t.currency), fmt_fecha(t), guion(t.status), obs])

        def colorear(r, c, texto):
            t = txs[r]
            if c == 6:
                return self.e.estado(t.status, texto)
            if c == 7:
                return self.e.rojo(texto) if t.errores else self.e.amarillo(texto) if t.advertencias else self.e.verde(texto)
            return texto

        return tabla(["N°", "Fuente", "ID", "Monto", "Moneda", "Fecha (UTC)", "Estado", "Observación"],
                     filas, "diidiiii", colorear, estilo=self.e)

    def _listar(self):
        txs = self._vista()
        if not txs:
            print(self.e.amarillo("  Ningún registro coincide con el filtro actual."))
            self._pausa()
            return
        paginas = math.ceil(len(txs) / TAMANO_PAGINA)
        pagina = 0
        while True:
            bloque = txs[pagina * TAMANO_PAGINA:(pagina + 1) * TAMANO_PAGINA]
            self._titulo(f"Transacciones — página {pagina + 1}/{paginas} ({len(txs)} registros)")
            print(f"  {self.e.tenue('Filtro: ' + self.filtro.describir())}\n")
            print(self._tabla_transacciones(bloque))
            op = self._leer("\n  [Enter] siguiente  [a] anterior  [N°] ver detalle  [v] volver: ").lower()
            if op == "":
                if pagina + 1 >= paginas:
                    return
                pagina += 1
            elif op == "a":
                pagina = max(0, pagina - 1)
            elif op == "v":
                return
            elif op.isdigit():
                self._detalle(int(op))
            else:
                print(self.e.rojo("  Opción no válida."))

    # ---------------- detalle ----------------
    def _pedir_detalle(self):
        txt = self._leer("  N° de registro (columna N° del listado): ")
        if not txt.isdigit():
            print(self.e.rojo("  Debe ingresar un número."))
            return
        self._detalle(int(txt))

    def _detalle(self, indice: int):
        t = self._buscar(indice)
        if t is None:
            print(self.e.rojo(f"  No existe el registro #{indice}."))
            return
        if t.es_valida:
            veredicto = self.e.verde("VÁLIDA") + (self.e.amarillo(f" con {len(t.advertencias)} advertencia(s)") if t.advertencias else "")
        else:
            veredicto = self.e.rojo(f"INVÁLIDA ({len(t.errores)} error(es))")
        self._titulo(f"Registro #{t.indice}")
        print(f"  Resultado: {veredicto}")
        if t.source:
            print(f"  Fuente   : {t.source} — {self.reglas.fuentes[t.source].descripcion if t.source in self.reglas.fuentes else ''}")
        print(self.e.negrita("\n  Original (como llegó):"))
        print(self._sangrar(json.dumps(t.original, ensure_ascii=False, indent=2)))
        print(self.e.negrita("\n  Normalizado:"))
        print(self._sangrar(json.dumps(t.a_esquema(), ensure_ascii=False, indent=2)))
        for inc in t.errores:
            print(self.e.rojo(f"  ✖ [{inc.codigo}]") + f" {inc.campo or 'registro'}: {inc.mensaje}")
        for inc in t.advertencias:
            print(self.e.amarillo(f"  ⚠ [{inc.codigo}]") + f" {inc.campo or 'registro'}: {inc.mensaje}")
        self._pausa()

    @staticmethod
    def _sangrar(texto: str) -> str:
        return "\n".join("    " + linea for linea in texto.splitlines())

    # ---------------- inválidas ----------------
    def _ver_invalidas(self):
        invalidas = self.resultado.invalidas
        self._titulo(f"Transacciones inválidas ({len(invalidas)})")
        if not invalidas:
            print(self.e.verde("  No hay transacciones inválidas."))
            self._pausa()
            return
        filas = [[str(t.indice), guion(t.source), guion(t.id), e.codigo, guion(e.campo), e.mensaje]
                 for t in invalidas for e in t.errores]
        print(tabla(["N°", "Fuente", "ID", "Código", "Campo", "Motivo"], filas, "diiiii",
                    lambda r, c, x: self.e.rojo(x) if c == 3 else x, ancho_max=60, estilo=self.e))
        print(self.e.negrita("\n  Política: ") + "las inválidas NO se descartan; se separan (invalidas.json) "
              "con su registro original\n  y quedan fuera de las métricas de negocio.")
        while True:
            op = self._leer("\n  [N°] ver detalle  [Enter] volver: ")
            if not op:
                return
            if op.isdigit():
                self._detalle(int(op))

    # ---------------- filtros ----------------
    def _elegir(self, titulo, opciones, permitir_todos=True):
        print(f"\n  {titulo}:")
        if permitir_todos:
            print(f"   {self.e.cian('0')}. (cualquiera)")
        for i, o in enumerate(opciones, 1):
            print(f"   {self.e.cian(str(i))}. {o}")
        txt = self._leer("  Elija: ")
        if permitir_todos and txt == "0":
            return None
        if txt.isdigit() and 1 <= int(txt) <= len(opciones):
            return opciones[int(txt) - 1]
        print(self.e.rojo("  Opción no válida; el filtro no cambió."))
        return _SIN_CAMBIO

    def _leer_fecha(self, etiqueta):
        txt = self._leer(f"  {etiqueta} (AAAA-MM-DD, Enter = sin límite): ")
        if not txt:
            return None
        try:
            return date.fromisoformat(txt)
        except ValueError:
            print(self.e.rojo(f"  '{txt}' no es una fecha AAAA-MM-DD."))
            return _SIN_CAMBIO

    def _leer_monto(self, etiqueta):
        txt = self._leer(f"  {etiqueta} (ej. 100.50, Enter = sin límite): ").replace(",", ".")
        if not txt:
            return None
        try:
            return Decimal(txt)
        except InvalidOperation:
            print(self.e.rojo(f"  '{txt}' no es un número."))
            return _SIN_CAMBIO

    def _menu_filtros(self):
        while True:
            f = self.filtro
            validas = self.resultado.validas
            self._titulo("Filtros")
            print(f"  Vista actual: {self.e.cian(f.describir())} → {len(self._vista())} registros\n")
            opciones = [
                ("1", "Validez", {"todas": "todas", "validas": "solo válidas", "invalidas": "solo inválidas"}[f.validez]),
                ("2", "Estado", f.estado or "cualquiera"),
                ("3", "Moneda", f.moneda or "cualquiera"),
                ("4", "Fuente", f.fuente or "cualquiera"),
                ("5", "Rango de fechas (UTC)", f"{f.desde or '…'} a {f.hasta or '…'}"),
                ("6", "Rango de montos", f"{f.monto_min if f.monto_min is not None else '…'} a "
                                         f"{f.monto_max if f.monto_max is not None else '…'}"),
                ("7", "ID contiene", f.texto_id or "—"),
                ("8", "Solo con advertencias", "sí" if f.solo_con_advertencias else "no"),
                ("9", "Limpiar todos los filtros", ""),
                ("0", "Volver", ""),
            ]
            for clave, texto, valor in opciones:
                print(f"   {self.e.cian(clave)}. {texto:<24} {self.e.tenue(valor)}")
            op = self._leer("\n  Opción: ")
            if op in ("0", ""):
                return
            if op == "1":
                v = self._elegir("Validez", ["todas", "validas", "invalidas"], permitir_todos=False)
                if v is not _SIN_CAMBIO:
                    f.validez = v
            elif op == "2":
                v = self._elegir("Estado", list(ESTADOS))
                if v is not _SIN_CAMBIO:
                    f.estado = v
            elif op == "3":
                monedas = sorted(set(valores_distintos(validas, "currency")) | self.reglas.monedas_soportadas)
                v = self._elegir("Moneda", monedas)
                if v is not _SIN_CAMBIO:
                    f.moneda = v
            elif op == "4":
                v = self._elegir("Fuente", list(self.reglas.fuentes))
                if v is not _SIN_CAMBIO:
                    f.fuente = v
            elif op == "5":
                desde = self._leer_fecha("Desde")
                hasta = self._leer_fecha("Hasta") if desde is not _SIN_CAMBIO else _SIN_CAMBIO
                if _SIN_CAMBIO in (desde, hasta):
                    continue
                if desde and hasta and desde > hasta:
                    print(self.e.rojo("  'Desde' no puede ser posterior a 'Hasta'."))
                    continue
                f.desde, f.hasta = desde, hasta
            elif op == "6":
                minimo = self._leer_monto("Mínimo")
                maximo = self._leer_monto("Máximo") if minimo is not _SIN_CAMBIO else _SIN_CAMBIO
                if _SIN_CAMBIO in (minimo, maximo):
                    continue
                if minimo is not None and maximo is not None and minimo > maximo:
                    print(self.e.rojo("  El mínimo no puede ser mayor que el máximo."))
                    continue
                f.monto_min, f.monto_max = minimo, maximo
            elif op == "7":
                f.texto_id = self._leer("  Texto a buscar en el ID (Enter = quitar): ") or None
            elif op == "8":
                f.solo_con_advertencias = not f.solo_con_advertencias
            elif op == "9":
                self.filtro = Filtro()
            else:
                print(self.e.rojo("  Opción no válida."))

    # ---------------- orden ----------------
    def _menu_orden(self):
        self._titulo("Ordenar")
        campos = list(CAMPOS_ORDEN)
        for i, c in enumerate(campos, 1):
            print(f"   {self.e.cian(str(i))}. {CAMPOS_ORDEN[c]}")
        txt = self._leer("  Campo: ")
        if not (txt.isdigit() and 1 <= int(txt) <= len(campos)):
            print(self.e.rojo("  Opción no válida."))
            return
        desc = self._leer("  ¿Descendente? [s/N]: ").lower() == "s"
        self.orden = (campos[int(txt) - 1], desc)

    # ---------------- métricas ----------------
    def _metricas(self):
        txs, alcance = self.resultado.transacciones, "carga completa"
        if self.filtro.activo:
            if self._leer("  ¿Métricas de [1] la carga completa o [2] la vista filtrada? [1]: ") == "2":
                txs, alcance = self._vista(), f"vista filtrada: {self.filtro.describir()}"
        m = calcular_metricas(txs)
        total = m["total_procesadas"]

        self._titulo(f"Métricas ({alcance})")
        print(f"  Total procesadas : {total}")
        print(f"  Válidas          : {m['validas']:>4}  {self.e.verde(barra(m['validas'], total))} {m['porcentaje_validas']}%")
        print(f"  Inválidas        : {m['invalidas']:>4}  {self.e.rojo(barra(m['invalidas'], total))} "
              f"{round(100 - m['porcentaje_validas'], 1) if total else 0.0}%")
        print(f"  Válidas con advertencias: {m['validas_con_advertencias']}")

        print(self.e.negrita("\n  Conteo por estado (válidas)"))
        for estado, n in m["por_estado"].items():
            print(f"   {self.e.estado(estado, f'{estado:<8}')} {n:>4}  {self.e.estado(estado, barra(n, m['validas']))}")

        print(self.e.negrita("\n  Totales por moneda (válidas)"))
        if m["totales_por_moneda"]:
            filas = [[moneda, str(d["cantidad"]), fmt_monto(d["total"])] + [fmt_monto(d["por_estado"][e]) for e in ESTADOS]
                     for moneda, d in m["totales_por_moneda"].items()]
            print(tabla(["Moneda", "N°", "Total", "SUCCESS", "FAILED", "PENDING"], filas, "iddddd", estilo=self.e))
            print(self.e.tenue("  (no se suman monedas distintas entre sí: no hay tipo de cambio en las reglas)"))
        else:
            print("  (sin transacciones válidas)")

        print(self.e.negrita("\n  Por fuente"))
        filas = [[f, str(d["total"]), str(d["validas"]), str(d["invalidas"])] for f, d in m["por_fuente"].items()]
        print(tabla(["Fuente", "Total", "Válidas", "Inválidas"], filas, "iddd", estilo=self.e))

        if m["errores_por_codigo"]:
            print(self.e.negrita("\n  Errores más frecuentes"))
            filas = [[c, str(n), CATALOGO.get(c, ("", ""))[1]] for c, n in m["errores_por_codigo"].items()]
            print(tabla(["Código", "N°", "Descripción"], filas, "idi", ancho_max=70, estilo=self.e))
        if m["advertencias_por_codigo"]:
            print(self.e.negrita("\n  Advertencias"))
            filas = [[c, str(n), CATALOGO.get(c, ("", ""))[1]] for c, n in m["advertencias_por_codigo"].items()]
            print(tabla(["Código", "N°", "Descripción"], filas, "idi", ancho_max=70, estilo=self.e))
        self._pausa()

    # ---------------- exportar ----------------
    def _exportar(self):
        self._titulo("Exportar")
        txs = self.resultado.transacciones
        if self.filtro.activo and self._leer("  ¿Exportar [1] la carga completa o [2] la vista filtrada? [1]: ") == "2":
            txs = self._vista()
        destino = self._leer(f"  Carpeta de salida [{self.carpeta_salida}]: ") or str(self.carpeta_salida)
        try:
            rutas = exportar(txs, Path(destino).expanduser())
        except OSError as ex:
            print(self.e.rojo(f"  ✖ No se pudo exportar: {ex}"))
        else:
            for nombre, ruta in rutas.items():
                print(self.e.verde("  ✔ ") + str(ruta))
        self._pausa()

    # ---------------- reglas ----------------
    def _ver_reglas(self):
        r = self.reglas
        self._titulo(f"Reglas cargadas ({r.ruta})")
        print(f"  Monedas soportadas: {', '.join(sorted(r.monedas_soportadas))}")
        alias = ", ".join(f"{a}→{m}" + (" (ambiguo)" if a in r.alias_ambiguos else "") for a, m in r.alias_moneda.items())
        print(f"  Alias de moneda   : {alias}")
        print(self.e.negrita("\n  Mapeo de estados"))
        for estado in ESTADOS:
            print(f"   {self.e.estado(estado, f'{estado:<8}')} ← {', '.join(r.variantes_de(estado))}")
        print(self.e.negrita("\n  Fuentes"))
        for f in r.fuentes.values():
            print(f"   {self.e.cian(f.nombre)}: {f.descripcion}")
            print(f"      campos : " + ", ".join(f"{dest}←{orig}" for dest, orig in f.campos.items()))
            print(f"      monto  : {f.unidad_monto}, separador decimal '{f.separador_decimal}'")
            print(f"      fechas : {' | '.join(f.formatos_fecha)} (sin zona → {f.zona_nombre})")
        print(self.e.negrita("\n  Validación"))
        print(f"   monto > {r.monto_minimo_exclusivo}, máximo {r.monto_maximo}, {r.decimales} decimales")
        print(f"   fechas futuras: {'error' if r.rechazar_fechas_futuras else 'advertencia'}  │  "
              f"duplicados entre fuentes: {'sí' if r.detectar_duplicados_entre_fuentes else 'no'}")
        print(self.e.negrita("\n  Catálogo de errores y advertencias"))
        print(tabla(["Código", "Severidad", "Descripción"], [[c, s, d] for c, (s, d) in CATALOGO.items()],
                    ancho_max=80, estilo=self.e))

        if self._leer("\n  [r] recargar reglas desde el archivo y reprocesar  [Enter] volver: ").lower() == "r":
            try:
                self.reglas = cargar_reglas(r.ruta)
            except ErrorReglas as ex:
                print(self.e.rojo(f"  ✖ Reglas no recargadas: {ex}"))
            else:
                print(self.e.verde("  ✔ Reglas recargadas."))
                if self.resultado:
                    self._cargar(self.resultado.ruta)
            self._pausa()

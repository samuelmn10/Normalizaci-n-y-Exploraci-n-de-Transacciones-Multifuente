import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from normalizador.consultas import Filtro, aplicar_filtro, ordenar
from normalizador.metricas import calcular_metricas
from normalizador.pipeline import ErrorEntrada, exportar, leer_transacciones, procesar
from normalizador.reglas import ErrorReglas

from .utilidades import AHORA, RAIZ, reglas

R = reglas()


def api(**cambios):
    base = {"id": "t1", "amount": "10.00", "currency": "USD", "timestamp": "2025-03-10 10:00:00", "status": "ok"}
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not ...}


def errores(registros, reglas_=R):
    return [[e.codigo for e in t.errores] for t in procesar(registros, reglas_, ahora=AHORA).transacciones]


class Validacion(unittest.TestCase):
    def test_campo_faltante(self):
        self.assertEqual(errores([api(amount=...)]), [["CAMPO_FALTANTE"]])
        self.assertEqual(errores([api(id="  ")]), [["CAMPO_FALTANTE"]])

    def test_reglas_de_monto_y_moneda(self):
        self.assertEqual(errores([api(amount="-1"), api(id="t2", amount=0), api(id="t3", amount=2000000)]),
                         [["MONTO_NO_POSITIVO"], ["MONTO_NO_POSITIVO"], ["MONTO_EXCEDE_MAXIMO"]])
        self.assertEqual(errores([api(currency="JPY")]), [["MONEDA_NO_SOPORTADA"]])

    def test_id_duplicado_conserva_la_primera(self):
        self.assertEqual(errores([api(), api()]), [[], ["ID_DUPLICADO"]])

    def test_mismo_id_en_otra_fuente_no_es_duplicado(self):
        legacy = {"transaction_id": "t1", "total": 999, "currency_code": "USD", "created_at": "10/03/2025 10:00", "state": "OK"}
        self.assertEqual(errores([api(), legacy]), [[], []])

    def test_fecha_futura_advertencia_o_error_segun_config(self):
        futura = [api(timestamp="2030-01-01 00:00:00")]
        tx = procesar(futura, R, ahora=AHORA).transacciones[0]
        self.assertTrue(tx.es_valida)
        self.assertEqual([a.codigo for a in tx.advertencias], ["FECHA_FUTURA"])
        estricta = reglas(lambda d: d["validacion"].update(rechazar_fechas_futuras=True))
        self.assertEqual(errores(futura, estricta), [["FECHA_FUTURA"]])

    def test_posible_duplicado_entre_fuentes(self):
        resultado = procesar(leer_transacciones(RAIZ / "datos" / "ejemplo_enunciado.json"), R, ahora=AHORA)
        self.assertEqual([[a.codigo for a in t.advertencias] for t in resultado.transacciones],
                         [[], ["POSIBLE_DUPLICADO"], []])

    def test_registros_que_no_son_objetos(self):
        self.assertEqual(errores(["texto", None, {"x": 1}]),
                         [["FORMATO_REGISTRO"], ["FORMATO_REGISTRO"], ["FUENTE_DESCONOCIDA"]])


class DatosDePrueba(unittest.TestCase):
    def setUp(self):
        self.resultado = procesar(leer_transacciones(RAIZ / "datos" / "transacciones_prueba.json"), R, ahora=AHORA)

    def test_conteos(self):
        m = calcular_metricas(self.resultado.transacciones)
        self.assertEqual((m["total_procesadas"], m["validas"], m["invalidas"]), (38, 17, 21))
        self.assertEqual(sum(m["por_estado"].values()), m["validas"])

    def test_totales_por_moneda(self):
        m = calcular_metricas(self.resultado.transacciones)
        self.assertEqual(m["totales_por_moneda"]["EUR"]["total"], Decimal("1644.99"))
        self.assertEqual(m["totales_por_moneda"]["USD"]["por_estado"]["SUCCESS"], Decimal("1461.75"))

    def test_filtros_y_orden(self):
        txs = self.resultado.transacciones
        usd_ok = aplicar_filtro(txs, Filtro(validez="validas", estado="SUCCESS", moneda="USD"))
        self.assertEqual([t.id for t in usd_ok], ["tx_001", "204", "tx_004", "A-84"])
        rango = aplicar_filtro(txs, Filtro(validez="validas", desde=date(2025, 3, 13), hasta=date(2025, 3, 13),
                                           monto_min=Decimal("40"), monto_max=Decimal("100")))
        self.assertEqual([t.id for t in rango], ["tx_006", "tx_007", "A-79"])
        self.assertEqual(ordenar(usd_ok, "amount", descendente=True)[0].id, "tx_004")
        self.assertIsNone(ordenar(txs, "amount")[-1].amount)  # los vacíos van al final

    def test_exportacion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            rutas = exportar(self.resultado.transacciones, carpeta)
            self.assertEqual(set(rutas), {"normalizadas.json", "normalizadas.csv", "invalidas.json",
                                          "advertencias.json", "metricas.json"})
            self.assertIn('"status": "SUCCESS"', Path(rutas["normalizadas.json"]).read_text(encoding="utf-8"))


class ErroresDeArchivos(unittest.TestCase):
    def test_json_mal_formado(self):
        with self.assertRaises(ErrorEntrada):
            leer_transacciones(RAIZ / "datos" / "archivo_mal_formado.json")

    def test_reglas_incoherentes(self):
        with self.assertRaises(ErrorReglas):
            reglas(lambda d: d["monedas"]["alias"].update({"¥": "JPY"}))
        with self.assertRaises(ErrorReglas):
            reglas(lambda d: d["estados"]["FAILED"].append("ok"))


if __name__ == "__main__":
    unittest.main()

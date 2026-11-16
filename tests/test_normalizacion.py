import unittest
from decimal import Decimal

from normalizador.normalizacion import (
    ErrorNormalizacion, detectar_fuente, normalizar_estado, normalizar_fecha,
    normalizar_moneda, normalizar_monto, normalizar_registro,
)
from normalizador.pipeline import leer_transacciones, procesar

from .utilidades import AHORA, RAIZ, reglas

R = reglas()
API, LEGACY, PARTNER = R.fuentes["api_v1"], R.fuentes["legacy_pos"], R.fuentes["partner_eu"]


def codigos(tx):
    return [e.codigo for e in tx.errores]


class EjemploDelEnunciado(unittest.TestCase):
    def test_las_tres_fuentes_quedan_en_el_esquema_comun(self):
        resultado = procesar(leer_transacciones(RAIZ / "datos" / "ejemplo_enunciado.json"), R, ahora=AHORA)
        self.assertEqual([t.a_esquema() for t in resultado.transacciones], [
            {"id": "tx_001", "amount": 100.5, "currency": "USD", "timestamp": "2025-03-10T14:22:00Z",
             "status": "SUCCESS", "source": "api_v1"},
            {"id": "204", "amount": 100.5, "currency": "USD", "timestamp": "2025-03-10T14:22:00Z",
             "status": "SUCCESS", "source": "legacy_pos"},
            {"id": "A-77", "amount": 99.99, "currency": "EUR", "timestamp": "2025-03-10T14:22:00Z",
             "status": "SUCCESS", "source": "partner_eu"},
        ])


class DeteccionDeFuente(unittest.TestCase):
    def test_por_claves(self):
        self.assertEqual(detectar_fuente({"transaction_id": 1, "total": 5, "created_at": "x", "state": "OK"}, R), "legacy_pos")
        self.assertEqual(detectar_fuente({"ref": "A", "amount": "€1", "date": "x", "result": "ok"}, R), "partner_eu")

    def test_con_un_campo_faltante_igual_se_detecta(self):
        self.assertEqual(detectar_fuente({"id": "t", "currency": "USD", "timestamp": "x", "status": "ok"}, R), "api_v1")

    def test_campo_source_explicito(self):
        self.assertEqual(detectar_fuente({"source": "legacy_pos", "id": "x"}, R), "legacy_pos")

    def test_desconocida(self):
        with self.assertRaises(ErrorNormalizacion) as ctx:
            detectar_fuente({"cliente": "x", "valor": 1}, R)
        self.assertEqual(ctx.exception.codigo, "FUENTE_DESCONOCIDA")


class Montos(unittest.TestCase):
    def monto(self, valor, regla=API):
        return normalizar_monto(valor, regla, R)

    def test_punto_decimal_y_miles(self):
        self.assertEqual(self.monto("1,250.75")[0], Decimal("1250.75"))
        self.assertEqual(self.monto(75)[0], Decimal("75.00"))

    def test_coma_decimal_con_simbolo(self):
        monto, moneda, ambigua, _ = self.monto("€1.234,50", PARTNER)
        self.assertEqual((monto, moneda, ambigua), (Decimal("1234.50"), "EUR", False))
        self.assertEqual(self.monto("15,5 EUR", PARTNER)[:2], (Decimal("15.50"), "EUR"))

    def test_simbolo_ambiguo(self):
        self.assertEqual(self.monto("$10,00", PARTNER)[1:3], ("USD", True))

    def test_separador_equivocado_no_se_adivina(self):
        with self.assertRaises(ErrorNormalizacion):
            self.monto("100.50", PARTNER)

    def test_centavos(self):
        self.assertEqual(self.monto(10050, LEGACY)[0], Decimal("100.50"))
        self.assertEqual(self.monto("4500", LEGACY)[0], Decimal("45.00"))
        with self.assertRaises(ErrorNormalizacion):
            self.monto(100.5, LEGACY)

    def test_redondeo(self):
        monto, _, _, redondeado = self.monto(19.999)
        self.assertEqual(monto, Decimal("20.00"))
        self.assertTrue(redondeado)

    def test_valores_no_numericos(self):
        for valor in ("abc", "€", True, [1], "1,2,3"):
            with self.subTest(valor=valor), self.assertRaises(ErrorNormalizacion):
                self.monto(valor)


class FechasEstadosMonedas(unittest.TestCase):
    def test_formato_por_fuente_y_conversion_a_utc(self):
        self.assertEqual(normalizar_fecha("10/03/2025 14:22", LEGACY).isoformat(), "2025-03-10T14:22:00+00:00")
        self.assertEqual(normalizar_fecha("2025-03-12T10:15:30-06:00", API).isoformat(), "2025-03-12T16:15:30+00:00")

    def test_fechas_invalidas(self):
        for valor, regla in (("31/02/2025 10:00", LEGACY), ("2025-03-14", LEGACY), ("ayer", API), (20250310, API)):
            with self.subTest(valor=valor), self.assertRaises(ErrorNormalizacion):
                normalizar_fecha(valor, regla)

    def test_estados(self):
        self.assertEqual(normalizar_estado(" Completed ", R), "SUCCESS")
        self.assertEqual(normalizar_estado("OK", R), "SUCCESS")
        self.assertEqual(normalizar_estado("declined", R), "FAILED")
        self.assertEqual(normalizar_estado("PEND", R), "PENDING")
        with self.assertRaises(ErrorNormalizacion):
            normalizar_estado("refunded", R)

    def test_monedas(self):
        self.assertEqual(normalizar_moneda(" usd ", R), "USD")
        self.assertEqual(normalizar_moneda("€", R), "EUR")
        with self.assertRaises(ErrorNormalizacion):
            normalizar_moneda("XX", R)


class ResolucionDeMoneda(unittest.TestCase):
    def registro(self, monto, moneda):
        return normalizar_registro(1, {"id": "t", "amount": monto, "currency": moneda,
                                       "timestamp": "2025-03-10 10:00:00", "status": "ok"}, R)

    def test_conflicto(self):
        self.assertEqual(codigos(self.registro("€50.00", "USD")), ["MONEDA_CONFLICTO"])

    def test_simbolo_ambiguo_respeta_el_campo(self):
        tx = self.registro("$80.00", "MXN")
        self.assertEqual((tx.currency, tx.errores), ("MXN", []))


if __name__ == "__main__":
    unittest.main()

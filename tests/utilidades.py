import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from normalizador.reglas import construir_reglas

RAIZ = Path(__file__).resolve().parent.parent
RUTA_REGLAS = RAIZ / "config" / "reglas.json"
AHORA = datetime(2025, 6, 1, tzinfo=timezone.utc)  # "ahora" fijo para pruebas reproducibles


def config_base() -> dict:
    return json.loads(RUTA_REGLAS.read_text(encoding="utf-8"))


def reglas(modificar=None):
    datos = copy.deepcopy(config_base())
    if modificar:
        modificar(datos)
    return construir_reglas(datos, str(RUTA_REGLAS))

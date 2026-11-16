# Normalización y Exploración de Transacciones Multifuente

Sistema en Python que lee transacciones de **varias fuentes con estructuras distintas**, las lleva a un **esquema común**, separa las inválidas con su motivo, calcula métricas y permite **explorar los datos desde una CLI interactiva** (listar, filtrar, ordenar, ver detalle, métricas y exportar).

- Solo usa la biblioteca estándar: **no hay que instalar dependencias**.
- Requiere **Python 3.9 o superior**.

## Cómo ejecutarlo

```bash
python main.py                                   # CLI interactiva con datos/transacciones_prueba.json
python main.py -e datos/ejemplo_enunciado.json   # otro archivo de entrada
python main.py --exportar salida                 # sin menú: procesa, exporta y muestra un resumen
python -m unittest -v                            # pruebas automáticas
```

En Windows usa `py` o `python` según tu instalación.

### Menú de la CLI

| Opción | Qué hace |
|---|---|
| 1. Listar | Tabla paginada de la vista actual (filtro + orden). Escribe un N° para ver el detalle. |
| 2. Filtrar | Combina filtros por validez, estado, moneda, fuente, rango de fechas, rango de montos, texto en el ID y "solo con advertencias". |
| 3. Ordenar | Por fecha, monto, ID, fuente, estado o moneda, ascendente o descendente. |
| 4. Detalle | Registro **original** al lado del **normalizado**, con sus errores y advertencias. |
| 5. Inválidas | Cada error con su código, campo y motivo. |
| 6. Métricas | De la carga completa o de la vista filtrada. |
| 7. Exportar | Escribe los archivos de salida (ver abajo). |
| 8. Cargar | Elige otro archivo de `datos/` o escribe una ruta. |
| 9. Reglas | Muestra las reglas activas y permite **recargarlas** después de editar `config/reglas.json`. |

## Estructura

```
config/reglas.json          Reglas: fuentes, mapeo de estados, monedas, formatos de fecha, límites
normalizador/
  modelo.py                 Esquema normalizado (Transaccion, Incidencia)
  reglas.py                 Carga y verificación del archivo de reglas
  normalizacion.py          Detección de fuente y conversión de cada campo
  validacion.py             Criterios de validez y catálogo de errores/advertencias
  metricas.py               Cálculo de métricas
  consultas.py              Filtros y ordenamiento (independientes de la interfaz)
  pipeline.py               Leer → normalizar → validar → exportar
  interfaz_cli.py           Interfaz interactiva (solo presentación)
main.py                     Punto de entrada
datos/                      Archivos de prueba
tests/                      Pruebas unitarias (unittest)
NOTA_TECNICA.md             Decisiones de diseño y uso de IA
```

## Esquema normalizado

```json
{
  "id": "204",
  "amount": 100.5,
  "currency": "USD",
  "timestamp": "2025-03-10T14:22:00Z",
  "status": "SUCCESS",
  "source": "legacy_pos"
}
```

| Campo | Regla |
|---|---|
| `id` | Siempre texto, sin espacios en los extremos (`204` → `"204"`). Es único **dentro de cada fuente**. |
| `amount` | En unidades (no centavos), 2 decimales, redondeo *half-up*. Internamente se usa `Decimal`. |
| `currency` | Código ISO 4217 en mayúsculas. Solo se aceptan las monedas de `monedas.soportadas`. |
| `timestamp` | ISO-8601 en **UTC** (`...Z`). Las fechas sin zona se interpretan en la zona de su fuente. |
| `status` | `SUCCESS`, `FAILED` o `PENDING`, según el mapeo explícito de `estados`. |
| `source` | Nombre de la fuente detectada. |

## Fuentes configuradas

| Fuente | Campos de origen | Monto | Fecha |
|---|---|---|---|
| `api_v1` | `id, amount, currency, timestamp, status` | unidades, punto decimal (`"1,250.75"`) | `AAAA-MM-DD HH:MM:SS` o ISO-8601 |
| `legacy_pos` | `transaction_id, total, currency_code, created_at, state` | **centavos enteros** (`10050` → `100.50`) | `DD/MM/AAAA HH:MM[:SS]` |
| `partner_eu` | `ref, amount, date, result` | coma decimal, **moneda dentro del monto** (`"€1.234,50"`) | ISO-8601 |

La fuente se detecta por la fracción de sus campos presentes en el registro (umbral 0.6); si hay empate o ninguna supera el umbral, el registro es inválido. Agregar una fuente nueva solo requiere un bloque más en `config/reglas.json`.

## Qué pasa con los registros inválidos

Se **marcan y separan**, no se descartan:

- **Error** → la transacción es inválida: queda fuera de las métricas de negocio y se exporta a `invalidas.json` con su registro original y la lista de motivos.
- **Advertencia** → la transacción sigue siendo válida, pero queda marcada para revisión (`advertencias.json`).

Errores: `FORMATO_REGISTRO`, `FUENTE_DESCONOCIDA`, `FUENTE_AMBIGUA`, `CAMPO_FALTANTE`, `ID_INVALIDO`, `ID_DUPLICADO`, `MONTO_INVALIDO`, `MONTO_NO_POSITIVO`, `MONTO_EXCEDE_MAXIMO`, `MONEDA_INVALIDA`, `MONEDA_NO_SOPORTADA`, `MONEDA_CONFLICTO`, `FECHA_INVALIDA`, `ESTADO_DESCONOCIDO`.
Advertencias: `MONTO_REDONDEADO`, `MONEDA_SUPUESTA`, `POSIBLE_DUPLICADO`, `FECHA_FUTURA` (o error, según la configuración).

## Métricas

Total procesadas, válidas e inválidas (con porcentaje), conteo por estado, totales por moneda (con desglose por estado), resumen por fuente y frecuencia de cada error y advertencia. Los totales **no mezclan monedas** porque las reglas no definen tipos de cambio.

## Salidas (`--exportar` u opción 7)

| Archivo | Contenido |
|---|---|
| `normalizadas.json` / `.csv` | Transacciones válidas en el esquema normalizado exacto |
| `invalidas.json` | Inválidas: original + normalizado parcial + errores |
| `advertencias.json` | Válidas con advertencias |
| `metricas.json` | Métricas del conjunto exportado |

## Datos de prueba

- `datos/ejemplo_enunciado.json`: los 3 registros del enunciado. Resultado: 3 válidas, con el mismo instante (2025-03-10 14:22 UTC).
- `datos/transacciones_prueba.json`: 38 registros, **17 válidos y 21 inválidos**. Cubren montos con miles, centavos, símbolos, coma decimal, redondeo, zonas horarias, estados en mayúsculas/minúsculas, `$` ambiguo, fecha futura, y cada uno de los errores del catálogo (ID duplicado, moneda en conflicto, 31 de febrero, formato de fecha de otra fuente, registros que no son objetos, etc.).
- `datos/archivo_mal_formado.json`: JSON roto, para comprobar que la CLI muestra el error sin cerrarse.

# Nota técnica

## 1. Diseño y separación de responsabilidades
El flujo es **leer → normalizar → validar → métricas → interfaz**, y cada etapa está en su propio módulo. `normalizacion.py` solo interpreta formatos; `validacion.py` decide qué es válido; `consultas.py` y `metricas.py` no dependen de la interfaz; `interfaz_cli.py` solo presenta los datos. Las reglas están en `config/reglas.json`, no en el código: se puede agregar una fuente, un estado o una moneda sin programar. El archivo se verifica al cargarse, y un alias hacia una moneda no soportada o un estado mapeado a dos destinos detienen el programa con un mensaje claro.

## 2. Decisiones sobre el esquema y las reglas
- **`id` como texto y único en todo el archivo**: la fuente legacy usa números (`204` → `"204"`). Un ID repetido, aunque venga de otra fuente, hace inválido el segundo registro, porque un ID que se repite ya no identifica una sola transacción.
- **Montos con `Decimal`, no con `float`/`double`**: los tipos de punto flotante producen decimales largos e inexactos (`0.1 + 0.2 = 0.30000000000000004`), algo inaceptable en dinero. Todos los montos quedan con 2 decimales y redondeo *half-up*. Cada fuente declara su unidad (`centavos` en legacy) y su separador decimal. Los separadores de miles solo se aceptan en grupos de 3 dígitos: `"100.50"` en una fuente de coma decimal se **rechaza**, no se adivina.
- **Fechas en UTC (ISO-8601)**, con formatos definidos **por fuente**. `10/03/2025` se lee como **día/mes**: `tx_001` y `204` tienen el mismo monto y hora, y solo coinciden si la fecha es el 10 de marzo.
- **Moneda**: el campo explícito manda sobre el símbolo del monto. Si se contradicen (`€50` con `USD`) es error. `$` es ambiguo (USD/MXN): si hay campo de moneda se respeta; si no, se asume USD con advertencia.
- **Estados**: mapeo explícito que no distingue mayúsculas. Un estado que no está en la lista (`refunded`) es error: no se supone su significado.

## 3. Criterios de validez y tratamiento de las inválidas
Política: **marcar y separar**. Una transacción con al menos un error queda fuera de las métricas de negocio, pero se conserva y se exporta (`invalidas.json`) con su registro original y todos los motivos, para corregirla en el origen. Las advertencias (redondeo, moneda supuesta, fecha futura, posible duplicado entre fuentes) no invalidan. Si un ID se repite, la primera aparición es la válida. Monto válido: mayor que 0 y hasta 1 000 000.

## 4. Uso de IA
Usé Claude (Claude Code) como asistente. A partir del enunciado generó la estructura de módulos, la lógica de parsing de montos y fechas, la CLI, las pruebas unitarias, los datos de prueba con inconsistencias y un primer borrador de esta nota. Las reglas quedaron en un archivo de configuración aparte para poder revisarlas y cambiarlas sin tocar el código.

## 5. Ajustes realizados sobre las sugerencias de la IA
- **Unicidad del ID**: la IA propuso que el ID fuera único solo dentro de cada fuente (el mismo ID en dos fuentes era válido). Lo cambié para que sea **único en todo el archivo**, porque no considero correcto que dos transacciones compartan ID. Quedó configurable (`validacion.unicidad_id`: `global` o `por_fuente`), con una prueba para cada modo y un caso en los datos de prueba (`A-77` repetido en legacy).
- **Representación de montos**: decidí usar `Decimal` en lugar de `float`/`double` para que los montos no arrastren decimales largos ni errores de redondeo, y exportarlos siempre con 2 decimales.
- Mantuve las demás reglas propuestas: fechas futuras como advertencia, `$` como USD supuesto y el máximo de 1 000 000.

# Nota técnica

> ✏️ **Antes de entregar:** la rúbrica pide que el esquema, las reglas y los criterios de validez sean decisiones **tuyas**, no de la IA. Revisa cada punto de las secciones 1 a 3, cambia lo que no compartas (casi todo se ajusta en `config/reglas.json`) y completa las secciones 4 y 5 con lo que hiciste realmente. Borra este recuadro al terminar.

## 1. Diseño y separación de responsabilidades
El flujo es **leer → normalizar → validar → métricas → interfaz**, y cada etapa está en su propio módulo. `normalizacion.py` solo interpreta formatos; `validacion.py` decide qué es válido; `consultas.py` y `metricas.py` no saben nada de la interfaz; `interfaz_cli.py` solo presenta. Las reglas viven en `config/reglas.json`, no en el código: se puede agregar una fuente, un estado o una moneda sin programar, y el archivo se verifica al cargarlo (un alias hacia una moneda no soportada o un estado mapeado a dos destinos detienen el programa con un mensaje claro).

## 2. Decisiones sobre el esquema y las reglas
- **`id` como texto y único por fuente**: la fuente legacy usa números (`204`), y dos fuentes pueden repetir el mismo ID sin ser la misma transacción.
- **Montos con `Decimal`** y 2 decimales *half-up*, para no perder centavos con `float`. Cada fuente declara su unidad (`centavos` en legacy) y su separador decimal. Los separadores de miles solo se aceptan en grupos de 3 dígitos: `"100.50"` en una fuente de coma decimal se **rechaza**, no se adivina.
- **Fechas en UTC.** Los formatos son **por fuente**. `10/03/2025` se lee como **día/mes**: `tx_001` y `204` tienen el mismo monto y hora, y solo coinciden si la fecha es el 10 de marzo.
- **Moneda**: el campo explícito manda sobre el símbolo del monto. Si se contradicen (`€50` con `USD`) es error. `$` es ambiguo (USD/MXN): si hay campo de moneda se respeta; si no, se asume USD y se deja una advertencia.
- **Estados**: mapeo explícito y sin distinguir mayúsculas. Un estado que no está en la lista (`refunded`) es error: no se supone su significado.

## 3. Criterios de validez y tratamiento de las inválidas
Política: **marcar y separar**. Una transacción con al menos un error queda fuera de las métricas de negocio, pero se conserva y se exporta con su registro original y todos los motivos, para poder corregirla en el origen. Las advertencias (redondeo, moneda supuesta, fecha futura, posible duplicado entre fuentes) no invalidan. Si un ID se repite en la misma fuente, la primera aparición es la válida. Monto válido: mayor que 0 y hasta 1 000 000.

## 4. Uso de IA
Herramienta: Claude (Claude Code). Se usó para:
- proponer la estructura de módulos y el código de parsing de montos y fechas;
- construir la CLI y las pruebas unitarias;
- generar los datos de prueba con inconsistencias.

✏️ *Completa: qué le pediste, qué revisaste tú y qué decisiones tomaste sin la IA.*

## 5. Ajustes sobre las sugerencias de la IA
✏️ *Completa con cambios que hiciste tú. Ideas de qué revisar:* ¿una fecha futura debe ser error y no advertencia? (`rechazar_fechas_futuras`) · ¿el máximo de 1 000 000 es razonable? · ¿`$` debería suponer USD o invalidar el registro? · ¿agregarías o quitarías variantes de estado (p. ej. `cancelled` como FAILED)? · ¿el umbral de detección de fuente (0.6) es adecuado?

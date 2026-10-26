# AI_LOG — fleet_inspection

## Herramientas
- Google Gemini (Advanced Agentic Assistant)

## Prompts clave (3 a 5)
1. *Identificar elementos obsoletos de Odoo 16 en vistas XML y modelos Python de fleet_inspection.*
   - Analizó las vistas XML y modelos: detectó el uso de `attrs`, `states` en botones y en definiciones de campo en Python, `name_get`, y la firma mono-registro en `create`.
2. *Generar script de migración SQL para pasar el campo vehicle_type de selection a many2one preservando valores existentes.*
   - Diseñó el script de migración para poblar el catálogo y actualizar en lotes con `UPDATE ... FROM ... WHERE ...` e idempotencia con fallback a `'other'`.
3. *Diseñar benchmark y estructura del plan de migración MIGRATION_PLAN.md para 10.000 inspecciones.*
   - Estructuró los pasos de pre-verificación, ejecución por chunks con medición de memoria y tiempos reales, y pasos de rollback.

## Lo que la IA hizo mal
- Inicialmente sugirió usar `ALTER TABLE fleet_inspection ALTER COLUMN vehicle_type TYPE integer USING vehicle_type::integer;`.
- *Cómo nos dimos cuenta:* El campo antiguo `vehicle_type` contiene cadenas de texto ('motorcycle', 'car', 'truck', 'other'), por lo que un cast directo a integer en Postgres arroja error de conversión. La solución limpia en Odoo es agregar la nueva columna `vehicle_type_id`, mapear por SQL mediante JOIN al catálogo `fleet_inspection_vehicle_type` sobre el código, y mantener la compatibilidad en Python.

## Lo que escribiste tú sin IA
- Redacción detallada de la tabla comparativa de cambios de versión en el `README.md`.
- Verificación de la preservación estricta del valor «otro» en inspecciones sin clasificar.


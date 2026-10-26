# Inspecciones de vehículos (`fleet_inspection`)

Módulo para el registro y gestión de inspecciones y checklists de vehículos de la flota.

---

## Tramos completados

- **Tramo A:** Migración completa de Odoo 16 a Odoo 17 (manifiesto, modelos, vistas, métodos del ciclo de vida y pruebas unitarias).
- **Tramo B:** Migración del campo `vehicle_type` de Selection a catálogo `fleet.inspection.vehicle.type` (Many2one) con scripts de migración automáticos en `migrations/17.0.2.0.0/post-migrate.py` y pruebas de migración de datos.
- **Tramo C:** Script de migración idempotente y por lotes (procesamiento de 10.000 registros), benchmark de tiempos y documento [`MIGRATION_PLAN.md`](./MIGRATION_PLAN.md).

---

## Tabla de Cambios de Versión (Odoo 16 → Odoo 17)

| Componente | Qué cambió | Por qué | Cómo se resolvió |
|---|---|---|---|
| **Manifiesto (`__manifest__.py`)** | Versión actualizada de `16.0.1.0.0` a `17.0.1.0.0` (y luego `17.0.2.0.0` en Tramo B). | Odoo 17 valida el prefijo de versión y rechaza módulos con prefijo de versión incompatible (`16.0.*`). | Se actualizó el número de versión en el manifiesto al estándar `17.0.x`. |
| **Modelos (`fleet_inspection.py`)** | Eliminado `name_get(self)` e implementado `_compute_display_name(self)`. | En Odoo 17, `name_get` fue formalmente deprecado en favor de la sobreescritura/cómputo del campo `display_name`. | Se definió `@api.depends(...) def _compute_display_name(self)` calculando `name - placa/modelo`. Se mantuvo un método `name_get()` delegando en `display_name` para compatibilidad retroactiva. |
| **Modelos (`fleet_inspection.py`)** | Firma de `create(self, vals)` adaptada a `@api.model_create_multi def create(self, vals_list)`. | En Odoo 17 el ORM invoca `create` en modo batch recibiendo una lista de diccionarios (`vals_list`) para mejorar el rendimiento. | Se decoró el método con `@api.model_create_multi` y se itera sobre `vals_list` para asignar secuencias y precargar el checklist en lote. |
| **Modelos (`fleet_inspection.py`)** | Eliminado el argumento `states={"draft": [("readonly", False)]}` en definiciones de campos Python. | El parámetro `states` a nivel de campo en Python está deprecado en Odoo 17 y genera advertencias de obsolescencia. | La restricción de solo lectura se trasladó a las vistas XML utilizando expresiones condicionales `readonly="..."`. |
| **Vistas XML (`fleet_inspection_views.xml`)** | Reemplazo de atributos obsoletos `attrs="..."` por expresiones booleanas directas (`invisible="..."`, `readonly="..."`, `required="..."`). | Odoo 17 eliminó el uso del diccionario `attrs` en favor de expresiones directas evaluadas en el cliente web OWL. | Se migraron todas las expresiones: `attrs="{'invisible': [('is_overdue', '=', False)]}"` pasó a `invisible="not is_overdue"`, y las condiciones de estado a `readonly="state != 'draft'"`, etc. |
| **Vistas XML (`fleet_inspection_views.xml`)** | Reemplazo de `states="draft"` en botones de acción. | El atributo `states` en botones XML fue deprecado en Odoo 17. | Se reemplazó por expresiones booleanas estándar: `invisible="state != 'draft'"`, `invisible="state != 'in_progress'"`, etc. |
| **Vistas XML (`tree`/`list`)** | Reemplazo de `invisible="1"` dentro de vistas de lista/árbol por `column_invisible="True"`. | En Odoo 17, ocultar columnas en listas requiere `column_invisible` para evitar renderizar celdas vacías o desalinear la grilla. | Se reemplazó `invisible="1"` en campos ocultos de `<tree>` por `column_invisible="True"`. |

---

## Cómo probarlo

Ejecutar la suite de pruebas del módulo:

```bash
./odoo test -d prueba_limpia -m fleet_inspection
```
O con la instancia:
```bash
./odoo test prueba-tecnica fleet_inspection
```

---

## Supuestos y limitaciones conocidas

1. **Checklist inicial:** Al crear una inspección sin líneas explícitas, el sistema carga automáticamente todos los ítems activos del catálogo `fleet.inspection.item`.
2. **Aprobación bloqueada por críticos:** Si al menos un ítem crítico tiene resultado `fail`, la inspección no puede ser aprobada y requiere corrección o rechazo.
3. **Preservación del tipo «otro»:** En la migración de Selection a catálogo Many2one, cualquier valor no clasificado o nulo se mapea al tipo de catálogo `Otro` (`code='other'`), garantizando integridad de datos.

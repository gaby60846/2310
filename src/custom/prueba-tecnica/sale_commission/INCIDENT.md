# Reporte de Incidente: T-200 — ¡No podemos vender!

- **Cliente:** Comercial Los Andes C.A.
- **Severidad:** Crítica (Bloqueo total de ventas para usuarios regulares)
- **Fecha y Hora del Reporte:** Viernes, 17:40 hrs.
- **Hora del Despliegue Causante:** Viernes, 12:00 hrs.
- **Estado:** Resuelto y Verificado.
- **Rama de Hotfix:** `hotfix/T-200`

---

## 1. Tramo A — Diagnóstico, Causa Raíz y Corrección

### 1.1. Cómo se reproduce el error
1. Iniciar sesión en Odoo con un usuario que pertenezca únicamente al grupo **Ventas / Usuario: Solo sus documentos** (`sales_team.group_sale_salesman`), por ejemplo el vendedor `commission_salesman`.
2. Crear un presupuesto de venta (`sale.order`) con al menos una línea de producto.
3. Hacer clic en el botón **Confirmar** (`action_confirm`).
4. **Resultado observado:** Aparece un mensaje de error rojo de Odoo (`AccessError`):
   > *No tiene los permisos necesarios para acceder a las reglas de comisión (`sale.commission.rule`). Contacte a su administrador.*
5. **Comportamiento anómalo adicional observado:**
   Cuando el gerente de ventas confirma el pedido en lugar del vendedor, el pedido se confirma sin error, pero a las líneas se les asigna la tasa de comisión del gerente en lugar de la del vendedor titular del pedido.

### 1.2. Causa Raíz
El incidente tuvo dos fallas concurrentes introducidas en la actualización desplegada a las 12:00 hrs:

1. **Permisos de acceso insuficientes (`AccessError`):**
   Al confirmar un pedido, `sale.order.action_confirm()` invoca `line._get_commission_percent()`, el cual ejecuta una búsqueda ORM sobre `sale.commission.rule`:
   ```python
   rules = self.env["sale.commission.rule"].search([...])
   ```
   En el archivo de seguridad `ir.model.access.csv`, el modelo `sale.commission.rule` sólo tenía permisos asignados al grupo de gerentes:
   ```csv
   access_sale_commission_rule_manager,sale.commission.rule.manager,model_sale_commission_rule,sales_team.group_sale_manager,1,1,1,1
   ```
   El grupo de vendedores (`sales_team.group_sale_salesman`) carece de permiso de lectura (`perm_read=0`), disparando la excepción de seguridad inmediata.

2. **Error de atribución de usuario (`self.env.user` vs `order.user_id`):**
   En el fallback de `_get_commission_percent()`:
   ```python
   return self.env.user.commission_percent  # ERROR: toma el usuario de la sesión actual
   ```
   Si el pedido lo confirma el gerente, `self.env.user` es el gerente, asignándole su comisión a las ventas del vendedor. Debió referenciar a `self.order_id.user_id.commission_percent`.

### 1.3. Corrección Aplicada
En `models/sale_order_line.py`:
- Se aplicó `sudo()` en la consulta de `sale.commission.rule`:
  ```python
  rules = self.env["sale.commission.rule"].sudo().search([
      ("categ_id", "parent_of", self.product_id.categ_id.id),
      ("company_id", "in", [False, self.company_id.id]),
  ])
  ```
- Se corrigió el retorno del porcentaje al vendedor del pedido:
  ```python
  return self.order_id.user_id.commission_percent if self.order_id.user_id else 0.0
  ```
- En `models/sale_order.py`:
  Se refactorizó `action_recompute_commissions` para que delegue directamente en `line._get_commission_percent()`, asegurando coherencia total.

**Justificación de `sudo()` vs modificar `ir.model.access.csv`:**
El modelo `sale.commission.rule` define políticas y márgenes comerciales de la empresa. En `product.category`, el campo `commission_percent` está explícitamente restringido a `groups="sales_team.group_sale_manager"`. Si se otorgara permiso de lectura en el CSV a los vendedores, estos podrían consultar las reglas y márgenes globales mediante RPC o vistas técnicas. Elevar privilegios puntualmente con `sudo()` durante el cálculo interno al confirmar cumple estrictamente con el principio de mínimo privilegio.

### 1.4. Prueba Automatizada
Se implementó en `tests/test_sale_commission.py`:
- `test_salesman_can_confirm_order`: Ejecuta la confirmación simulando el usuario vendedor (`order.with_user(self.salesman).action_confirm()`). Falla con `AccessError` antes del cambio y pasa con éxito después.
- `test_manager_confirming_order_preserves_salesman_commission`: Verifica que si el gerente (`self.manager`, con 15%) confirma el pedido del vendedor (`self.salesman`, con 5%), el pedido conserva el 5% del vendedor.

---

## 2. Tramo B — Contención, Análisis y Despliegue

### 2.1. Contención en los primeros 15 minutos (antes del fix definitivo)
Para permitir que la empresa opere sin interrupciones mientras se valida y despliega el código:

- **Medida temporal:** Otorgar temporalmente permiso de lectura sobre el modelo `sale.commission.rule` al grupo `sales_team.group_sale_salesman` directamente en la base de datos de producción mediante Odoo Shell:
  ```python
  env['ir.model.access'].create({
      'name': 'temp_read_sale_commission_rule',
      'model_id': env.ref('sale_commission.model_sale_commission_rule').id,
      'group_id': env.ref('sales_team.group_sale_salesman').id,
      'perm_read': True,
  })
  env.cr.commit()
  ```
- **Riesgos:** Los vendedores podrían consultar temporalmente los porcentajes por categoría configurados en el sistema si acceden a la API/RPC. No obstante, no pueden modificar nada y el riesgo de negocio es mínimo comparado con la paralización total de las ventas del sábado.
- **Reversibilidad:** 100% reversible. Una vez desplegada la rama de hotfix, este registro temporal se elimina automáticamente con `unlink()`.

### 2.2. Commit que introdujo el error y por qué pasó la revisión
- **Commit identificador:** `3f4d73fb2810f1fd650ce1de24557cb9b49624b3` (`[FEAT] sale_commission: porcentaje de comisión por categoría de producto`).
- **Por qué pasó la revisión técnica:**
  1. El test existente `test_commission_on_confirm` corría bajo el contexto del usuario administrador (`self.env.user`).
  2. En el commit se modificó `_create_order` eliminando el `.with_user(user)` que estaba en el commit original.
  3. En `setUpClass`, el desarrollador agregó la línea `cls.env.user.commission_percent = 5.0` para que coincidiera con el vendedor, enmascarando que `_get_commission_percent()` consultaba `self.env.user` en lugar de `order.user_id`.
  4. Ningún test ejecutó `action_confirm` con un usuario de ventas sin permisos de gerente.

### 2.3. Pasos para desplegar la corrección y verificarla en producción
1. **Respaldo preventivo:**
   ```bash
   ./odoo backup <instancia>
   ```
2. **Obtención del hotfix:**
   ```bash
   git fetch origin
   git checkout hotfix/T-200
   ```
3. **Actualización del módulo:**
   ```bash
   ./odoo update <instancia> sale_commission
   ```
4. **Verificación en producción:**
   - Iniciar sesión con un usuario vendedor y confirmar un pedido de prueba: confirmar que no muestra error y queda en estado 'sale'.
   - Verificar que el porcentaje y monto de comisión coincidan con la ficha del vendedor.
   - Confirmar un pedido con el usuario gerente asignado a otro vendedor y verificar que el porcentaje resultante sea el del vendedor titular.

### 2.4. Mensaje al Cliente (3 a 5 líneas, no técnico)
> Estimada Carolina,
> Le confirmamos que hemos identificado el inconveniente que impedía a los vendedores confirmar pedidos desde el mediodía de hoy y ya aplicamos la solución correspondiente en el sistema. Los vendedores ya pueden confirmar sus ventas normalmente para la jornada de mañana sábado a primera hora. Adicionalmente, estamos auditando los pedidos confirmados por gerencia durante la tarde para asegurar que todas las comisiones queden perfectamente calculadas. Cualquier duda adicional, estamos a su completa disposición.

---

## 3. Tramo C — Impacto en los Datos y Prevención

### 3.1. Impacto en los datos registrados
Durante la tarde del viernes, el gerente confirmó pedidos en sustitución de los vendedores. Todas las líneas de dichos pedidos cuyos productos no pertenecían a una categoría con regla propia tomaron el porcentaje de comisión del gerente (`15%`) en lugar del porcentaje del vendedor asignado al pedido (`3%` o `5%`). Esto sobrestimó las comisiones a pagar y generó inconsistencias en el reporte mensual.

### 3.2. Script de Auditoría de Solo Lectura y Plan de Remediación
- Se creó el script `scripts/audit_affected_orders.py`.
- **Ejecución de auditoría:**
  ```bash
  python3 src/custom/prueba-tecnica/sale_commission/scripts/audit_affected_orders.py
  ```
- **Plan de remediación:**
  1. Ejecutar el script de auditoría para generar la lista de pedidos con discrepancia y guardar una copia de seguridad en CSV.
  2. Compartir el resumen cuantitativo con la gerencia de administración para su visto bueno.
  3. En ventana de mantenimiento (viernes en la noche), ejecutar `order.action_recompute_commissions()` únicamente sobre los pedidos afectados:
     ```python
     for row in affected_orders:
         order = env['sale.order'].browse(row['order_id'])
         order.action_recompute_commissions()
     env.cr.commit()
     ```
  4. Re-ejecutar `audit_affected_orders.py` para constatar que las discrepancias sean exactamente 0.

### 3.3. Detección de patrones similares en el módulo
Se auditó todo el código de `sale_commission`:
- `models/sale_order.py`: `action_recompute_commissions` utilizaba `rules = self.env["sale.commission.rule"].search([])` sin `sudo()`. Si un usuario no-gerente intentaba recalcular, hubiera fallado. Se corrigió delegando en `line._get_commission_percent()`.
- `models/product_category.py`: Protegido correctamente con `groups="sales_team.group_sale_manager"`.
- `report/sale_commission_report.py`: La vista SQL agrupa por `o.user_id` del pedido y no por el confirmador, por lo que una vez recalculadas las líneas, el reporte reflejará los datos correctos inmediatamente.

### 3.4. Reglas de prevención para el equipo
1. **Obligatoriedad de tests bajo perfiles de menor privilegio:** En todo PR que involucre transacciones de ventas o compras, los tests unitarios deben ejecutarse explícitamente con `.with_user(vendedor)`. Se prohíbe evaluar flujos de usuario final únicamente como `self.env.user` (administrador).
2. **Regla de revisión sobre `self.env.user`:** En modelos de documentos (`sale.order`, `account.move`), queda prohibido usar `self.env.user` para lógica de negocio o cálculos financieros; debe emplearse la relación de modelo (`order.user_id`).
3. **Validación de matriz ACL:** Los PRs que agreguen modelos deben acompañarse de un test de permisos que pruebe lectura/escritura tanto para el rol de usuario como para el de administrador.


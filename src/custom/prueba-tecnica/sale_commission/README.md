# Comisiones de vendedores (`sale_commission`)

Calcula la comisión del vendedor en cada línea de pedido de venta y ofrece un análisis mensual por vendedor.

---

## Tramos completados

- **Tramo A:** Reproducción y corrección de causa raíz del ticket urgente T-200 (`AccessError` por permisos de `sale.commission.rule` y fallo de cálculo de comisión atribuida con `self.env.user` en lugar de `self.order_id.user_id`). Pruebas unitarias multi-usuario con `with_user(salesman)`.
- **Tramo B:** Estrategia de contención en los primeros 15 minutos, identificación del commit causante (`3f4d73fb`), explicación de por qué falló la revisión, procedimiento de despliegue en producción y redacción del mensaje al cliente sin jerga técnica.
- **Tramo C:** Script de auditoría de solo lectura (`scripts/audit_affected_orders.py`), plan de remediación paso a paso para pedidos confirmados por el gerente durante la tarde, revisión de patrones análogos y propuesta de reglas de prevención técnica y de revisión de código para el equipo.

Detalle completo en [`INCIDENT.md`](./INCIDENT.md).

---

## Configuración

- **Porcentaje del vendedor:** Ajustes › Usuarios › pestaña *Comisiones* (solo gerentes de ventas).
- **Porcentaje por categoría (desde la 1.1):** Inventario/Ventas › Configuración › Categorías de producto, campo *Comisión (%)*. Si la categoría (o una categoría padre) tiene porcentaje, reemplaza al del vendedor.

---

## Cómo probarlo

Ejecutar la suite de pruebas del módulo:

```bash
./odoo test -d prueba_limpia -m sale_commission
```
O con la instancia:
```bash
./odoo test prueba-tecnica sale_commission
```

Para correr el script de auditoría de pedidos afectados:
```bash
python3 src/custom/prueba-tecnica/sale_commission/scripts/audit_affected_orders.py
```

---

## Supuestos y limitaciones conocidas

1. **Jerarquía de reglas:** Si existen varias reglas configuradas en la jerarquía de categorías, prevalece la categoría más específica (nodo más profundo en `parent_path`).
2. **Atribución en pedidos sin vendedor:** Si un pedido no tiene vendedor asignado (`order.user_id` es falso) y los productos no tienen regla de categoría, el porcentaje de comisión se asigna como `0.0%`.
3. **Inmutabilidad:** Las comisiones se fijan en el momento de confirmar el pedido (`action_confirm`). Si se modifican las reglas con posterioridad, los pedidos confirmados mantienen sus valores salvo que un gerente pulse expresamente el botón *Recalcular comisiones*.

# Integración con API para Tienda en Línea (`shop_integration_api`)

Módulo que expone servicios REST seguros para que la plataforma de comercio electrónico consulte catálogo con inventario en tiempo real y cree pedidos de venta en Odoo.

---

## Tramos completados

- **Tramo A:** Endpoint `GET /api/v1/products` con autenticación, filtros individuales y combinados (categoría, `only_stock`, `updated_since`), manejo de errores de formato de fecha (HTTP 400 en vez de 500) y pruebas unitarias.
- **Tramo B:** Autenticación por token Bearer con API Keys nativas de Odoo (`res.users.apikeys`), endpoint `POST /api/v1/orders` con validación de RIF, código de producto y cantidades (> 0), formato de error HTTP 422 con campo exacto, modelo de auditoría `api.request.log` (sin almacenar claves) y pruebas con `HttpCase`.
- **Tramo C:** Paginación con metadatos (`total`, `page`, `limit`, `has_next`), soporte de cabecera `Idempotency-Key` (detección de reintentos idénticos y detección de conflictos HTTP 409), cálculo masivo de stock en una sola consulta SQL, webhook de entrega saliente resiliente en `stock.picking` con cola de reintentos en `api.webhook.log` y documentación completa en [`openapi.yaml`](./openapi.yaml).

---

## Documentación de Códigos HTTP y Formato de Errores

Todas las respuestas de error siguen estrictamente el estándar JSON unificado:

```json
{
  "error": {
    "code": "CODIGO_ERROR",
    "field": "campo_afectado",
    "message": "Descripción legible para humanos"
  }
}
```

| Código HTTP | Significado | Escenario de uso |
|---|---|---|
| **200 OK** | Éxito | Consulta exitosa de catálogo de productos o reintento idempotente reconocido. |
| **201 Created** | Creado | Pedido de venta creado exitosamente en Odoo. |
| **400 Bad Request** | Solicitud Inválida | Formato JSON defectuoso o fecha en `updated_since` mal estructurada (`INVALID_DATE_FORMAT`). |
| **401 Unauthorized** | No Autorizado | Cabecera `Authorization: Bearer <token>` ausente o API Key inválida / revocada (`UNAUTHORIZED`). |
| **409 Conflict** | Conflicto | Se reutilizó la misma cabecera `Idempotency-Key` pero con un cuerpo de petición diferente (`IDEMPOTENCY_CONFLICT`). |
| **422 Unprocessable** | Error de Validación | Parámetros de negocio inválidos: RIF inexistente (`PARTNER_NOT_FOUND`), producto inexistente (`PRODUCT_NOT_FOUND`) o cantidad `<= 0` (`INVALID_QUANTITY`). |

---

## Cómo probarlo

Ejecutar la suite completa de pruebas HTTP:

```bash
./odoo test -d prueba_limpia -m shop_integration_api
```
O con la instancia:
```bash
./odoo test prueba-tecnica shop_integration_api
```

---

## Supuestos y limitaciones conocidas

1. **Estado del pedido creado:** Se configuró por defecto que los pedidos entren en estado **Cotización / Borrador** (`state='draft'`). Esto permite que el personal administrativo o de almacén verifique disponibilidad y condiciones antes de confirmar. Si la tienda opera con pasarela de pago en línea que ya cobró la orden, la empresa puede cambiar la opción a **Confirmado automáticamente** (`state='sale'`) desde Ajustes › Ventas › Integración con Tienda en Línea.
2. **Identificación de clientes:** Los clientes se identifican unívocamente a través del campo `vat` (RIF / Cédula / NIF). No se crean clientes automáticamente vía API para evitar duplicación de contactos en Odoo.
3. **Resiliencia de Webhooks:** Cuando un almacenista valida una entrega en Odoo (`stock.picking`), si la tienda está caída o responde lento, el proceso de validación en almacén no se interrumpe ni arroja error; el webhook queda registrado con estado `failed` y una acción planificada (`ir.cron`) reintenta la entrega con retroceso exponencial.

# Prueba técnica — Desarrollador Odoo

**Versión declarada de Odoo:** **17.0** (`ODOO_VERSION=17.0` en `.env` e `instances.json`).

Esta carpeta es el directorio de addons de la prueba técnica. Aquí se encuentran **todos los módulos de la entrega**:

| Módulo | Ejercicio | Estado |
|---|---|---|
| `sale_commission` | Ejercicio 3 — Ticket urgente (T-200) | Corregido, auditado y documentado con `hotfix/T-200` e `INCIDENT.md`. |
| `fleet_inspection` | Ejercicio 2 — Migración de Odoo 16 a Odoo 17 | Migrado a 17.0, catálogo Many2one con scripts idempotentes en `migrations/` y `MIGRATION_PLAN.md`. |
| `shop_integration_api` | Ejercicio 1 — Integración API para tienda en línea | Implementado con Auth Bearer API keys nativas, endpoints GET/POST, idempotencia, webhook y `openapi.yaml`. |
| `payment_request` | Ejercicio 4 — Solicitudes de pago con aprobación | Implementado con aprobaciones jerárquicas, wizards de pago/rechazo, multi-compañía, bloqueo pesimista contra concurrencia y `ARCHITECTURE.md`. |

---

## Levantar el entorno y ejecutar pruebas

La instancia está configurada en `instances.json` (`prueba-tecnica` sobre Odoo 17.0 y PostgreSQL 16):

1. **Construir y levantar la instancia:**
   ```bash
   ./odoo build prueba-tecnica
   ./odoo start prueba-tecnica
   ```

2. **Ejecutar la suite completa de pruebas sobre base de datos limpia:**
   ```bash
   ./odoo test -d prueba_limpia -m shop_integration_api,fleet_inspection,sale_commission,payment_request
   ```
   O directamente especificando la instancia:
   ```bash
   ./odoo test prueba-tecnica shop_integration_api,fleet_inspection,sale_commission,payment_request -d prueba_limpia
   ```

# AI_LOG — sale_commission

## Herramientas
- Google Gemini (Advanced Agentic Assistant)

## Prompts clave (3 a 5)
1. *Identificar el error que impide a los vendedores confirmar pedidos en `sale_commission` y revisar el historial de commits recientes.*
   - Analizó el historial de `git log` e identificó que el commit `3f4d73fb` agregó la búsqueda de `sale.commission.rule`, pero omitió permisos de lectura en `ir.model.access.csv` para vendedores y usó `self.env.user.commission_percent`. Se procedió a diseñar la corrección con `sudo()` acotado y `self.order_id.user_id.commission_percent`.
2. *Diseñar un test que reproduzca el error simulando un usuario vendedor real.*
   - Sugirió tests con `with_user(salesman)` tanto para confirmación regular como para confirmación delegada por el gerente, garantizando que el test falle antes del hotfix y pase después.
3. *Elaborar el script de auditoría de solo lectura y el plan de contención de 15 minutos.*
   - Estructuró `audit_affected_orders.py` para comparar el porcentaje real en línea vs el esperado por regla o vendedor sin escribir en base de datos, y formuló el plan de contención temporal en `INCIDENT.md`.

## Lo que la IA hizo mal
- Inicialmente propuso otorgar permisos de lectura directa a `sale.commission.rule` en `ir.model.access.csv` para el grupo de vendedores.
- *Cómo nos dimos cuenta:* Al revisar los requerimientos del ejercicio ("no repartir permisos de más") y notar que el campo `commission_percent` en `product.category` tiene `groups="sales_team.group_sale_manager"`, dar lectura en CSV permitiría a los vendedores consultar las reglas por API/RPC. Se prefirió usar `sudo()` acotado y debidamente justificado en `_get_commission_percent()`.

## Lo que escribiste tú sin IA
- Redacción del mensaje de comunicación de 4 líneas dirigido a Carolina sin jerga técnica.
- Decisión de diseño de delegar `action_recompute_commissions` directamente en `line._get_commission_percent()` para mantener una única fuente de verdad (principio DRY).

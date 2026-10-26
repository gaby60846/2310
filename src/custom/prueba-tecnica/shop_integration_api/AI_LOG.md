# AI_LOG — shop_integration_api

## Herramientas
- Google Gemini (Advanced Agentic Assistant)

## Prompts clave (3 a 5)
1. *Diseñar un controlador Odoo 17 para GET /api/v1/products con autenticación Bearer mediante res.users.apikeys y cálculo de stock sin N queries.*
   - Generó la estructura del controlador utilizando `_compute_quantities_dict()` del recordset de productos para consolidar el cómputo de stock en una única operación agrupada.
2. *Implementar validaciones con código HTTP 422 y formato JSON estándar para POST /api/v1/orders.*
   - Diseñó el árbol de validaciones con campo exacto indexado (`lines[i].default_code`, `lines[i].qty`) y códigos semánticos.
3. *Implementar mecanismo de idempotencia mediante cabecera Idempotency-Key y SHA-256.*
   - Desarrolló el modelo `api.idempotency.key` para persistir hash de payload y responder con cache o 409 Conflict.

## Lo que la IA hizo mal
- Inicialmente sugirió implementar autenticación mediante tokens JWT propios con una librería externa (`PyJWT`).
- *Cómo nos dimos cuenta:* El enunciado exige explícitamente usar la autenticación nativa de Odoo (`res.users.apikeys`), la cual ya viene integrada en Odoo y permite a los usuarios generar sus llaves desde su perfil sin dependencias externas. Se sustituyó por `request.env['res.users.apikeys']._check_credentials()`.

## Lo que escribiste tú sin IA
- Redacción manual de la especificación OpenAPI 3.0 en `openapi.yaml`.
- Lógica de resiliencia en el envío de webhooks para garantizar que una caída de la tienda externa nunca impida al usuario de almacén validar una entrega.


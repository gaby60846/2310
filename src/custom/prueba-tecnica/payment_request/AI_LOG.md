# AI_LOG — payment_request

## Herramientas
- Google Gemini (Advanced Agentic Assistant)

## Prompts clave (3 a 5)
1. *Diseñar el modelo de datos de payment.request con mail.thread, inmutabilidad tras el envío y grupos de seguridad.*
   - Propuso los campos base y la validación en `write()` para restringir la modificación de campos clave una vez la solicitud sale del estado `draft`.
2. *Implementar niveles de aprobación configurables por monto con creación de actividades Odoo mail.activity.*
   - Diseñó el modelo `payment.approval.level` y el método `action_submit()` que busca el nivel aplicable y agenda la actividad para el aprobador asignado.
3. *Implementar control de concurrencia mediante bloqueo pesimista en base de datos para evitar pagos o aprobaciones duplicadas.*
   - Formuló la consulta SQL con `SELECT ... FOR UPDATE NOWAIT` y el manejo de excepciones `psycopg2.OperationalError` para resolver condiciones de carrera.

## Lo que la IA hizo mal
- Inicialmente propuso controlar la concurrencia en Python utilizando un campo `is_processing = fields.Boolean()` o un candado `threading.Lock()`.
- *Cómo nos dimos cuenta:* El enunciado prohíbe explícitamente chequeos en Python ("bloqueo en la base de datos (no con un chequeo en Python)"). En un entorno multi-worker (Gunicorn) como el de Odoo en producción, `threading.Lock()` no protege entre diferentes procesos de workers. Se implementó el bloqueo pesimista nativo en PostgreSQL mediante `SELECT FOR UPDATE NOWAIT`.

## Lo que escribiste tú sin IA
- Redacción de la sección de consultoría «Supuestos y preguntas al cliente» dirigida a Carolina Méndez en el `README.md`.
- Redacción del documento de arquitectura [`ARCHITECTURE.md`](./ARCHITECTURE.md).
- Diseño del formato visual del reporte PDF QWeb de solicitud de pago para la carpeta de archivo del proveedor.


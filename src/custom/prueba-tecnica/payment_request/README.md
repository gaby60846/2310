# Solicitudes de Pago con Aprobación (`payment_request`)

Módulo para la gestión, control jerárquico de aprobaciones, registro contable y trazabilidad de solicitudes de pago a proveedores para Distribuidora Andina C.A.

---

## Tramos completados

- **Tramo A:** Modelo `payment.request` con `mail.thread` y secuencia `SP/2026/0001`, grupos de seguridad (Solicitante, Aprobador, Tesorería), inmutabilidad de solicitudes enviadas, validación de monto positivo, reglas de registro para que los solicitantes solo vean sus solicitudes e imposibilidad de aprobar siendo solicitante.
- **Tramo B:** Niveles de aprobación configurables por monto (`payment.approval.level`) con asignación automática y actividades programadas; solo el aprobador asignado puede aprobar; wizard de rechazo con motivo obligatorio publicado en el chatter; wizard de pago con diario contable que genera el `account.payment` vinculado; protección para que una solicitud no pueda pagarse dos veces; reporte impreso PDF (QWeb) que muestra quién aprobó y cuándo.
- **Tramo C:** Pagos multi-divisa con conversión automática (ej. solicitud en USD liquidada desde diario en VES a la tasa de la fecha de pago); soporte multi-compañía con reglas de aislamiento estricto; control de concurrencia con bloqueo pesimista en base de datos (`SELECT FOR UPDATE NOWAIT`); garantía de atomicidad transaccional (si el pago contable falla, la solicitud no queda en pagada); documento [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Supuestos y preguntas al cliente

A partir del correo inicial recibido de **Carolina Méndez** (*Gerente de Administración*), como consultores identificamos varios aspectos operacionales no definidos. A continuación se detallan las preguntas formuladas y las decisiones adoptadas como supuestos de diseño para avanzar:

### Preguntas a Carolina:
1. **Facturas de Proveedor existentes:** ¿Las solicitudes de pago deben vincularse a una factura de proveedor ya cargada en Odoo (`account.move`), o son anticipos / órdenes de compra previas a la factura?
2. **Umbral de aprobación de Gerencia:** ¿A partir de qué monto exacto se considera un pago "grande" que requiere la firma de Gerencia en lugar del Jefe de Área?
3. **Múltiples aprobaciones escalonadas:** ¿Un pago grande requiere ambas aprobaciones (primero el Jefe y luego Gerencia) o una sola aprobación directa por el nivel más alto?
4. **Tratamiento de la Diferencia en Cambio:** Si la solicitud se aprueba en USD pero se liquida en VES, ¿quién asume y cómo desean registrar contablemente la ganancia o pérdida cambiaria si la tasa varía entre la emisión y el pago?
5. **Cuentas bancarias del proveedor:** ¿Se debe exigir que el proveedor tenga registrada una cuenta bancaria activa antes de poder enviar la solicitud a aprobación?

### Supuestos asumidos para avanzar:
1. **Niveles configurables por empresa:** Se asumió que los montos mínimos y aprobadores varían por compañía y con el tiempo, por lo que se implementó el modelo flexible `payment.approval.level`, dejando configurado por defecto que montos `< $1,000` son aprobados por el Jefe de Área y `>= $1,000` por Gerencia.
2. **Aprobación de nivel superior único:** Al enviar la solicitud, el sistema determina el nivel más alto que aplica según el monto y le asigna la tarea al responsable de ese nivel directamente.
3. **Conversión de divisas a la fecha del pago:** Al momento de generar el pago desde tesorería, el sistema toma la tasa oficial vigente en Odoo en la fecha seleccionada en el wizard para calcular el monto exacto en VES que egresará del banco.
4. **Registro de anticipo/pago directo:** Dado que muchos pagos son anticipos de WhatsApp sin factura formal previa, el wizard crea un `account.payment` de salida de proveedor que queda disponible para conciliar posteriormente contra la factura cuando el proveedor la entregue.

---

## Cómo probarlo

Ejecutar la suite de pruebas del módulo:

```bash
./odoo test -d prueba_limpia -m payment_request
```
O con la instancia:
```bash
./odoo test prueba-tecnica payment_request
```

# Arquitectura Técnica: Solicitudes de Pago con Aprobación (`payment_request`)

Este documento expone las decisiones de diseño, modelo de datos, gestión de concurrencia y tratamiento contable multi-divisa del módulo `payment_request` para Odoo 17.

---

## 1. Modelo de Dominio y Máquina de Estados

El modelo central `payment.request` implementa un ciclo de vida unidireccional y predecible:
- `draft` (Borrador): Editable por el solicitante.
- `submitted` (Enviada): Inmutable para el solicitante; asigna aprobador por monto y genera actividad `mail.activity`.
- `approved` (Aprobada): Aprobada formalmente por el responsable asignado; disponible para tesorería.
- `paid` (Pagada): Vinculada de forma atómica e irreversible a un asiento `account.payment`.
- `rejected` (Rechazada): Estado terminal que preserva el motivo obligatorio en el chatter.

### Inmutabilidad Controlada
Una vez que el registro transiciona a `submitted`, el método `write()` bloquea modificaciones sobre campos estructurales (`partner_id`, `amount`, `currency_id`, `date`, `concept`). Esto garantiza que lo evaluado y aprobado por el jefe o gerente no sufra alteraciones antes o durante el pago en tesorería.

---

## 2. Gestión de Concurrencia: Bloqueo Pesimista en Base de Datos

### El Problema
Cuando una solicitud es enviada, o cuando tesorería procede al pago, dos usuarios o procesos concurrentes podrían interactuar simultáneamente (por ejemplo, dos directores aprobando al mismo tiempo, o un clic duplicado en el botón de pago).
Un chequeo simple en Python:
```python
if self.state != 'submitted':  # INSUFICIENTE
    raise UserError(...)
```
es vulnerable a condiciones de carrera (*race conditions* / *time-of-check to time-of-use*), ya que ambas transacciones pueden leer `state == 'submitted'` antes de que ninguna haya hecho `commit`, aprobando o pagando dos veces.

### La Solución Arquitectónica
Se implementó **bloqueo pesimista a nivel de fila en PostgreSQL**:
```python
self.env.cr.execute(
    "SELECT id, state FROM payment_request WHERE id = %s FOR UPDATE NOWAIT",
    [self.id],
)
```
- **Por qué `FOR UPDATE`:** Adquiere un bloqueo exclusivo de fila en PostgreSQL para la transacción actual.
- **Por qué `NOWAIT`:** Si otra transacción ya tiene bloqueada la fila, no se queda suspendida en cola (evitando *deadlocks* y consumo innecesario de conexiones), sino que falla inmediatamente, permitiendo capturar `psycopg2.OperationalError` y devolver un mensaje amigable de concurrencia al usuario.
- **Resultado:** Garantiza que estrictamente **un solo aprobador o tesorero gane la transacción**, asegurando que una solicitud **nunca pueda ser pagada dos veces**.

---

## 3. Integración Contable y Atomicidad Transaccional

El registro del pago no se realiza mediante métodos directos en el modelo, sino delegando en un asistente de tesorería (`payment.request.pay.wizard`):
1. **Validación Previa:** Constata que `state == 'approved'` y `payment_id == False`.
2. **Creación del Asiento Contable:** Genera un registro nativo `account.payment` (`payment_type='outbound'`, `partner_type='supplier'`) y ejecuta `action_post()`.
3. **Atomicidad:** Al ejecutarse dentro del mismo bloque de transacción de Odoo, si la contabilización falla (ej. período cerrado, cuentas desbalanceadas o diario sin secuencia), la base de datos ejecuta un `ROLLBACK` total. **La solicitud jamás queda en estado `paid` si el pago contable no se materializó exitosamente.**

---

## 4. Multi-divisa y Conversión de Monedas (USD / VES)

Para resolver el requerimiento de Carolina (facturación de proveedores en USD y liquidación en VES):
- La solicitud almacena la moneda de origen pactada con el proveedor (`req.currency_id`).
- El wizard detecta la moneda configurada en el diario de pago bancario (`journal_id.currency_id` o moneda de compañía).
- Si difieren, aplica la conversión nativa de Odoo a la fecha efectiva de pago:
  ```python
  payment_amount = req_currency._convert(
      req.amount, journal_currency, company, payment_date
  )
  ```
Esto asegura que el asiento contable se registre con el tipo de cambio oficial vigente en la fecha en que tesorería ejecuta la transferencia, sin cálculos manuales propensos a error.

---

## 5. Aislamiento Multi-Compañía

El módulo opera con soporte multi-compañía nativo:
- Tanto `payment.request` como `payment.approval.level` poseen el campo `company_id`.
- Se configuran reglas de registro globales (`ir.rule` con `global=True`) con el dominio:
  ```xml
  <field name="domain_force">['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]</field>
  ```
- **Garantía:** Un usuario de la Compañía B no puede leer, consultar ni interactuar con las solicitudes ni niveles de la Compañía A, manteniendo la estricta confidencialidad entre razones sociales.

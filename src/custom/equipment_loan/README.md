# Módulo: Préstamos de Equipos (`equipment_loan`)
**Grupo Llanos C.A. — Coordinación de Soporte TI (Jorge Lara)**  
**Versión Odoo:** 17.0+ | **Licencia:** LGPL-3  
**Dependencias:** `maintenance`, `mail`

---

## 1. Visión General y Contexto de Negocio

En empresas con alta movilidad y múltiples áreas operativas como **Grupo Llanos C.A.**, el departamento de Soporte TI gestiona un inventario finito de equipos sensibles y de alto costo (laptops, proyectores para salas de reuniones, radios de comunicación, tabletas industriales). 

### La problemática
Anteriormente, los préstamos se gestionaban informalmente o en hojas de cálculo dispersas, lo cual causaba:
1. **Pérdida de trazabilidad:** Dificultad para saber quién tiene físicamente un equipo específico en un momento dado.
2. **Conflictos de doble asignación (Overbooking):** Prometer o entregar el mismo proyector o laptop a dos personas simultáneamente.
3. **Retenciones indebidas y vencimientos invisibles:** Empleados que conservaban equipos durante semanas o meses más allá de la fecha prevista, sin que TI tuviera visibilidad inmediata para exigir su devolución.
4. **Falta de segregación de responsabilidades:** Solicitantes que podían marcar entregas o devoluciones sin la validación física del personal de TI.

### El objetivo de la solución
Proveer un módulo Odoo integrado directamente con el módulo estándar de Mantenimiento (`maintenance.equipment`), permitiendo registrar solicitudes, controlar entregas físicas mediante roles de seguridad, evitar dobles préstamos incluso bajo condiciones de alta concurrencia en el servidor, monitorear préstamos vencidos en tiempo real y automatizar el seguimiento proactivo diario.

---

## 2. Detalle del Funcionamiento de los Formularios y Vistas

El módulo introduce una nueva entidad `equipment.loan` y extiende el formulario estándar de `maintenance.equipment`.

### 2.1 Formulario de Préstamos (`equipment.loan`)

El formulario de préstamos está concebido para reflejar el ciclo de vida real del préstamo físico en el taller o almacén de TI:

```
    [ Borrador ]  ──( Botón «Entregar» )──>  [ Prestado ]  ──( Botón «Devolver» )──>  [ Devuelto ]
     (Draft)                                  (Loaned)                                  (Returned)
```

#### A. Encabezado (`<header>`)
- **Barra de estado (`statusbar`):** Muestra el flujo determinista: `Borrador` $\to$ `Prestado` $\to$ `Devuelto`.
- **Botón «Entregar» (`action_deliver`):**
  - **Visibilidad:** Únicamente visible cuando el registro está en estado **Borrador** (`invisible="state != 'draft'"`).
  - **Seguridad:** Restringido a usuarios con el grupo **«Gestor de préstamos»** (`equipment_loan.group_equipment_loan_manager`). Un usuario común no puede accionar la entrega.
  - **Acción:** Verifica que el equipo no se encuentre prestado a nadie más, ejecuta un bloqueo pesimista a nivel de base de datos (`SELECT FOR UPDATE NOWAIT`), transiciona a estado `Prestado` y publica un mensaje en el chatter auditando la fecha de entrega y la persona que lo recibió.
- **Botón «Devolver» (`action_return`):**
  - **Visibilidad:** Únicamente visible cuando el registro está en estado **Prestado** (`invisible="state != 'loaned'"`).
  - **Seguridad:** Restringido al grupo **«Gestor de préstamos»**.
  - **Acción:** Asigna de forma automática la fecha real de devolución (`date_return = context_today()`), cambia el estado a `Devuelto`, registra la devolución en el chatter y resuelve automáticamente las actividades abiertas de vencimiento asociadas.

#### B. Notificación y Alerta Visual de Vencimiento
- Justo debajo del título del préstamo, se despliega un **banner de alerta roja** (`alert alert-danger`):
  ```xml
  <div class="alert alert-danger" role="alert" invisible="not is_overdue">
      <i class="fa fa-warning me-2"/>
      <strong>¡Préstamo Vencido!</strong> La fecha prevista de devolución ya expiró y el equipo sigue en posesión del usuario.
  </div>
  ```
  Permite al coordinador de TI identificar de un vistazo si el equipo en pantalla presenta una mora administrativa.

#### C. Campos del Formulario
| Campo | Tipo | Comportamiento | Razón de Negocio |
|---|---|---|---|
| **Referencia (`name`)** | `Char` | Autoincremental (`LN/2026/00001`), de solo lectura. | Código único e inequívoco para identificar el acta de entrega. |
| **Equipo (`equipment_id`)** | `Many2one` (`maintenance.equipment`) | Obligatorio. Editable solo en Borrador. `ondelete="restrict"`. | Selecciona el bien tangible del catálogo de Mantenimiento. |
| **Persona que lo recibe (`user_id`)** | `Many2one` (`res.users`) | Obligatorio. Por defecto el usuario conectado. Editable solo en Borrador. | Identifica formalmente al responsable custodio del equipo. |
| **Fecha de entrega (`date_start`)** | `Date` | Obligatoria. Por defecto la fecha actual (`context_today`). Editable solo en Borrador. | Marca el día cero del préstamo físico. |
| **Fecha prevista devolución (`date_expected`)** | `Date` | Obligatoria. Editable solo en Borrador. Validada contra `date_start`. | Compromiso pactado de entrega. Base para calcular el vencimiento. |
| **Fecha real de devolución (`date_return`)** | `Date` | Solo lectura. Oculta hasta que el estado sea `Devuelto`. | Auditoría de cuándo reingresó efectivamente el activo. |
| **¿Vencido? (`is_overdue`)** | `Boolean` | Campo computado y almacenable en memoria de búsqueda. | Indicador lógico para alertas, filtros y colores en listas. |
| **Observaciones / Motivo (`notes`)** | `Text` | Libre en cualquier estado en la pestaña inferior. | Permite detallar accesorios entregados (cargadores, maletines, adaptadores HDMI) o condiciones de entrega. |

#### D. Trazabilidad y Chatter (`oe_chatter`)
Integra `mail.thread` y `mail.activity.mixin`, permitiendo:
- Notificaciones automáticas de cambio de estado.
- Registro de comentarios internos entre analistas de soporte.
- Programación manual y automática de actividades («Por hacer»).

---

### 2.2 Formulario de Equipos de Mantenimiento (`maintenance.equipment`)

Se extiende la vista estándar de equipos para proporcionar información contextual sin cambiar de módulo:

1. **Smart Button («Préstamos»):**
   - Ubicado en la caja de botones superiores (`div[name='button_box']`).
   - Muestra el total de préstamos asociados a ese equipo específico (`loan_count`).
   - Al hacer clic, ejecuta la acción `action_view_loans()` que abre la lista filtrada de préstamos de ese equipo, con el equipo precargado por defecto en caso de crear uno nuevo.
2. **Campo Informativo «En Préstamo por» (`current_loan_id`):**
   - Posicionado debajo de la categoría del equipo.
   - Solo se muestra cuando el equipo tiene un préstamo activo (`invisible="not current_loan_id"`).
   - Muestra un enlace directo al préstamo activo y al nombre del empleado custodio.

---

### 2.3 Vista Lista (Tree View)

Diseñada para operaciones ágiles de inventario con decoradores de color contextuales:

- `decoration-danger="is_overdue"`: Fila en **rojo brillante** si el préstamo está vencido.
- `decoration-primary="state == 'loaned'"`: Fila en **azul corporativo** si está activamente prestado en plazo.
- `decoration-muted="state == 'returned'"`: Fila en **gris atenuado** cuando ya fue devuelto y cerrado.
- **Badge fields:** Los campos de estado y de vencimiento utilizan el widget de insignia (`widget="badge"`).

---

### 2.4 Vista Búsqueda y Filtros Dinámicos (Search View)

Permite segmentar los registros según la necesidad operativa:
- **Filtros de estado:** «Borrador», «En Préstamo», «Devueltos».
- **Filtro dinámico «Vencidos»:**
  ```xml
  <filter name="filter_overdue" string="Vencidos"
          domain="[('state', '=', 'loaned'), ('date_expected', '&lt;', context_today())]"/>
  ```
  *¿Por qué dinámico?* Al usar `context_today()`, Odoo evalúa la fecha del usuario en el instante exacto de la consulta. Si un préstamo venció a medianoche, a primera hora de la mañana aparecerá automáticamente en el filtro sin necesidad de correr scripts o procesos batch.
- **Filtro «Mis Préstamos»:** `[('user_id', '=', uid)]` para que los empleados regulares encuentren sus equipos rápidamente.
- **Agrupadores:** Agrupar por Equipo, por Persona receptora, por Estado y por Mes de Entrega.

---

## 3. Razón de la Funcionalidad y Casos de Uso

| Caso de Uso en Soporte TI | Comportamiento Implementado | Beneficio Operativo |
|---|---|---|
| **Entrega en mostrador de TI** | El técnico crea el préstamo, selecciona el equipo y presiona «Entregar». | Queda formalizada la entrega; el equipo cambia su estado interno y el sistema impide que otro técnico lo entregue a otra persona. |
| **Intento de entrega retroactiva inválida** | Si se introduce una fecha prevista anterior a la fecha de entrega, Odoo levanta `ValidationError`. | Previene incongruencias lógicas y errores de digitación en los acuerdos de nivel de servicio (SLA). |
| **Reserva simultánea por dos analistas** | Dos analistas intentan entregar la misma laptop a las 09:00:00 AM. | El bloqueo pesimista en PostgreSQL detiene la segunda transacción y muestra un error explicativo antes de comprometer datos. |
| **Reingreso y recepción del activo** | El usuario devuelve la laptop; el técnico presiona «Devolver». | Se estampa la fecha exacta de hoy, se cierra el ciclo y el equipo queda disponible de inmediato para futuros préstamos. |
| **Seguimiento diario de morosidad** | El cron del sistema detecta a las 06:00 AM que un proyector no fue devuelto ayer. | Crea una tarea «Por hacer» en la bandeja del Gestor de TI, sin duplicar tareas si la del día anterior sigue abierta. |

---

## 4. Soluciones Técnicas Planteadas

### 4.1 Tramo A: Arquitectura Base y Validación de Fechas
- **Modelo:** `equipment.loan` con control de estados estándar (`draft`, `loaned`, `returned`).
- **Validación de consistencia de fechas:**
  ```python
  @api.constrains("date_start", "date_expected")
  def _check_dates_consistency(self):
      for loan in self:
          if loan.date_start and loan.date_expected and loan.date_expected < loan.date_start:
              raise ValidationError(
                  _("La fecha prevista de devolución (%s) no puede ser anterior a la fecha de entrega (%s).")
                  % (loan.date_expected, loan.date_start)
              )
  ```
- **Secuencia:** Secuencia independiente `LN/%(range_year)s/` vinculada al modelo `ir.sequence`.

### 4.2 Tramo B: Exclusión Mutua, Vencimiento Dinámico y Smart Button
- **Regla de unicidad de préstamo activo:**
  Se garantiza a nivel de ORM con `@api.constrains("equipment_id", "state")`:
  ```python
  @api.constrains("equipment_id", "state")
  def _check_unique_active_loan_per_equipment(self):
      for loan in self:
          if loan.state == "loaned" and loan.equipment_id:
              conflicts = self.search_count([
                  ("id", "!=", loan.id),
                  ("equipment_id", "=", loan.equipment_id.id),
                  ("state", "=", "loaned"),
              ])
              if conflicts > 0:
                  raise ValidationError(_("El equipo '%s' ya se encuentra prestado.") % loan.equipment_id.display_name)
  ```
- **Cómputo y Búsqueda de `is_overdue`:**
  Combina `@api.depends("state", "date_expected")` con un método `_search_is_overdue` que traduce cualquier búsqueda o filtro ORM (`[('is_overdue', '=', True)]`) a SQL evaluando contra `context_today(self)`.

### 4.3 Tramo C: Concurrencia, Seguridad, Performance y Cron
- **Concurrencia con Bloqueo Pesimista (PostgreSQL `FOR UPDATE NOWAIT`):**
  Para evitar *race conditions* cuando múltiples usuarios operan en simultáneo, el método `action_deliver` bloquea la fila del equipo en la tabla `maintenance_equipment`:
  ```python
  self.env.cr.execute(
      "SELECT id FROM maintenance_equipment WHERE id = %s FOR UPDATE NOWAIT",
      [loan.equipment_id.id]
  )
  ```
  Si otra transacción tiene bloqueado el equipo o acaba de cambiar su estado, PostgreSQL levanta una excepción inmediata impidiendo que ambas pasen a `loaned`.
- **Seguridad Multicapa:**
  - **Grupo de Seguridad:** `equipment_loan.group_equipment_loan_manager` ("Gestor de préstamos").
  - **Record Rules:**
    - Usuarios generales (`base.group_user`): `[('user_id', '=', user.id)]` (solo ven sus propios préstamos).
    - Gestores (`group_equipment_loan_manager`): `[(1, '=', 1)]` (visibilidad total).
  - **Restricción a nivel de métodos:** `action_deliver` y `action_return` verifican `self.env.user.has_group('equipment_loan.group_equipment_loan_manager')` arrojando `AccessError` en caso de intento no autorizado.
- **Rendimiento $O(1)$ en Smart Buttons (`read_group`):**
  En lugar de iterar cada equipo y ejecutar `search_count`, el cálculo de `loan_count` utiliza `read_group`:
  ```python
  data = self.env["equipment.loan"].read_group(
      domain=[("equipment_id", "in", self.ids)],
      fields=["equipment_id"],
      groupby=["equipment_id"],
  )
  ```
  Esto reduce el número de consultas a la base de datos de $N$ a **1 única consulta agrupada**, garantizando tiempos de respuesta instantáneos en listas masivas.
- **Acción Planificada (`ir.cron`) y Deduplicación de Actividades:**
  El cron ejecuta `_cron_check_overdue_loans()` diariamente. Antes de programar una actividad (`activity_schedule`), verifica con `mail.activity.search` si ya existe una actividad abierta para ese registro y tipo:
  ```python
  existing = self.env["mail.activity"].search([
      ("res_model", "=", "equipment.loan"),
      ("res_id", "=", loan.id),
      ("activity_type_id", "=", todo_type.id),
  ], limit=1)
  if not existing:
      loan.activity_schedule(...)
  ```
  Esto previene inundar la bandeja del gestor con notificaciones repetidas día tras día.

---

## 5. Pruebas Unitarias Automatizadas

El módulo incluye un conjunto de 8 pruebas unitarias (`tests/test_equipment_loan.py`) que validan la integridad de cada tramo:

```
1. test_loan_full_lifecycle                              --> Valida creación, entrega y devolución con fecha real (Tramo A).
2. test_expected_return_before_delivery_blocked         --> Valida bloqueo cuando date_expected < date_start (Tramo A).
3. test_prevent_double_active_loan_same_equipment       --> Valida bloqueo de doble préstamo activo (Tramo B).
4. test_overdue_dynamic_calculation_and_search          --> Valida cálculo de vencimiento y filtro dinámico (Tramo B).
5. test_smart_button_loan_count_and_action              --> Valida contador y acción de ventana del smart button (Tramo B).
6. test_security_regular_user_cannot_see_others_nor_deliver --> Valida aislamiento de datos y restricciones de acción (Tramo C).
7. test_smart_button_batch_computation_performance     --> Valida consulta agregada O(1) con read_group (Tramo C).
8. test_cron_overdue_loans_does_not_duplicate_activities --> Valida creación de actividades y deduplicación (Tramo C).
```

### Ejecución de Pruebas
```bash
./odoo test prueba-tecnica equipment_loan -d test_loan_db
```
Resultado: **8 tests ejecutados, 100% aprobados, 0 fallos, 0 errores**.

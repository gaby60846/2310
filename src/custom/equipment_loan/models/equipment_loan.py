import logging
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class EquipmentLoan(models.Model):
    _name = "equipment.loan"
    _description = "Préstamo de Equipo"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_expected asc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        copy=False,
        readonly=True,
        default="/",
        tracking=True,
    )
    equipment_id = fields.Many2one(
        "maintenance.equipment",
        string="Equipo",
        required=True,
        tracking=True,
        ondelete="restrict",
        help="Equipo de mantenimiento prestado (Laptop, proyector, radio, etc.)",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Persona que lo recibe",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        help="Empleado o usuario que solicita y tiene en posesión el equipo.",
    )
    date_start = fields.Date(
        string="Fecha de entrega",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="Fecha en que se entrega físicamente el equipo al solicitante.",
    )
    date_expected = fields.Date(
        string="Fecha prevista de devolución",
        required=True,
        tracking=True,
        help="Fecha límite comprometida para devolver el equipo.",
    )
    date_return = fields.Date(
        string="Fecha real de devolución",
        readonly=True,
        copy=False,
        tracking=True,
        help="Fecha efectiva en la que el usuario devolvió el equipo al soporte TI.",
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("loaned", "Prestado"),
            ("returned", "Devuelto"),
        ],
        string="Estado",
        required=True,
        default="draft",
        tracking=True,
    )
    is_overdue = fields.Boolean(
        string="¿Vencido?",
        compute="_compute_is_overdue",
        search="_search_is_overdue",
        help="Indica si el préstamo sigue activo y ya superó la fecha prevista de devolución.",
    )
    notes = fields.Text(
        string="Observaciones / Motivo",
        help="Detalles sobre el uso del equipo o estado de entrega.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )

    # =========================================================================
    # RESTRICCIONES (CONSTRAINTS) - TRAMO A y TRAMO B
    # =========================================================================

    @api.constrains("date_start", "date_expected")
    def _check_dates_consistency(self):
        """Tramo A: Una devolución prevista anterior a la entrega se bloquea con mensaje claro."""
        for loan in self:
            if loan.date_start and loan.date_expected and loan.date_expected < loan.date_start:
                raise ValidationError(
                    _(
                        "La fecha prevista de devolución (%s) no puede ser anterior "
                        "a la fecha de entrega (%s)."
                    )
                    % (loan.date_expected, loan.date_start)
                )

    @api.constrains("equipment_id", "state")
    def _check_unique_active_loan_per_equipment(self):
        """Tramo B: Un equipo no puede tener dos préstamos activos (estado 'prestado') a la vez."""
        for loan in self:
            if loan.state == "loaned" and loan.equipment_id:
                active_conflicts = self.search_count(
                    [
                        ("id", "!=", loan.id),
                        ("equipment_id", "=", loan.equipment_id.id),
                        ("state", "=", "loaned"),
                    ]
                )
                if active_conflicts > 0:
                    raise ValidationError(
                        _(
                            "El equipo '%s' ya se encuentra prestado en otro préstamo activo. "
                            "Un equipo no se le puede prestar a dos personas a la vez."
                        )
                        % loan.equipment_id.display_name
                    )

    # =========================================================================
    # VENCIMIENTO DINÁMICO (COMPUTE & SEARCH) - TRAMO B
    # =========================================================================

    @api.depends("state", "date_expected")
    def _compute_is_overdue(self):
        """Tramo B: Determina si el préstamo está vencido en tiempo real."""
        today = fields.Date.context_today(self)
        for loan in self:
            loan.is_overdue = bool(
                loan.state == "loaned"
                and loan.date_expected
                and loan.date_expected < today
            )

    def _search_is_overdue(self, operator, value):
        """Tramo B: Filtro dinámico que evalúa la fecha actual tanto hoy como mañana."""
        today = fields.Date.context_today(self)
        positive = (operator in ("=", "!=") and bool(value)) or (
            operator in ("in", "not in") and True in value
        )
        if operator in ("!=", "not in"):
            positive = not positive

        if positive:
            return [("state", "=", "loaned"), ("date_expected", "<", today)]
        return ["|", ("state", "!=", "loaned"), ("date_expected", ">=", today)]

    # =========================================================================
    # CRUD & SECUENCIA - TRAMO A
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("equipment.loan") or "/"
                )
        return super().create(vals_list)

    # =========================================================================
    # ACCIONES DE BOTONES & CONCURRENCIA - TRAMO A y TRAMO C
    # =========================================================================

    def action_deliver(self):
        """Tramo A: Pasa a 'prestado'.
        Tramo C: Valida permisos de Gestor y aplica bloqueo pesimista en base de datos.
        """
        # Tramo C: Seguridad a nivel de método
        if not self.env.user.has_group("equipment_loan.group_equipment_loan_manager"):
            raise AccessError(
                _("Solo los usuarios del grupo 'Gestor de préstamos' pueden registrar entregas.")
            )

        for loan in self:
            if loan.state != "draft":
                raise UserError(_("Solo se pueden entregar préstamos en estado borrador."))

            # Tramo C: Concurrencia - Bloqueo Pesimista en PostgreSQL
            # Bloqueamos la fila del equipo en la base de datos para evitar que dos
            # transacciones concurrentes entreguen el mismo equipo en el mismo milisegundo.
            self.env.cr.execute(
                """
                SELECT id FROM maintenance_equipment
                WHERE id = %s
                FOR UPDATE NOWAIT
                """,
                [loan.equipment_id.id],
            )

            # Verificación inmediata con el lock adquirido
            conflict = self.search(
                [
                    ("id", "!=", loan.id),
                    ("equipment_id", "=", loan.equipment_id.id),
                    ("state", "=", "loaned"),
                ],
                limit=1,
            )
            if conflict:
                raise ValidationError(
                    _(
                        "Conflicto de concurrencia: El equipo '%s' acaba de ser prestado "
                        "en el préstamo %s."
                    )
                    % (loan.equipment_id.display_name, conflict.name)
                )

            loan.state = "loaned"
            loan.message_post(
                body=_(
                    "Equipo entregado formalmente a <b>%s</b>. Fecha prevista de retorno: %s."
                )
                % (loan.user_id.name, loan.date_expected)
            )

    def action_return(self):
        """Tramo A: Registra la fecha real de devolución y pasa a 'devuelto'.
        Tramo C: Valida permisos de Gestor y cierra actividades pendientes.
        """
        if not self.env.user.has_group("equipment_loan.group_equipment_loan_manager"):
            raise AccessError(
                _("Solo los usuarios del grupo 'Gestor de préstamos' pueden registrar devoluciones.")
            )

        today = fields.Date.context_today(self)
        for loan in self:
            if loan.state != "loaned":
                raise UserError(_("Solo se pueden devolver préstamos que estén en estado prestado."))

            loan.write(
                {
                    "state": "returned",
                    "date_return": today,
                }
            )
            loan.message_post(
                body=_(
                    "Equipo devuelto satisfactoriamente al almacén de TI. Fecha de recepción: %s."
                )
                % today
            )

            # Tramo C: Cierre automático de actividades de vencimiento pendientes
            todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
            if todo_type:
                loan.activity_ids.filtered(lambda a: a.activity_type_id == todo_type).action_done()

    # =========================================================================
    # ACCIÓN PLANIFICADA (CRON) - TRAMO C
    # =========================================================================

    @api.model
    def _cron_check_overdue_loans(self):
        """Tramo C: Acción planificada diaria que alerta al gestor sobre préstamos vencidos
        sin duplicar actividades existentes.
        """
        today = fields.Date.context_today(self)
        overdue_loans = self.search(
            [
                ("state", "=", "loaned"),
                ("date_expected", "<", today),
            ]
        )

        if not overdue_loans:
            _logger.info("Cron Préstamos Vencidos: No se encontraron préstamos vencidos.")
            return

        manager_group = self.env.ref(
            "equipment_loan.group_equipment_loan_manager", raise_if_not_found=False
        )
        if not manager_group or not manager_group.users:
            _logger.warning(
                "Cron Préstamos Vencidos: No hay usuarios en el grupo 'Gestor de préstamos'."
            )
            return

        # Notificamos al primer gestor activo disponible o al responsable asignado
        manager_user = manager_group.users.filtered(lambda u: u.active)[:1]
        if not manager_user:
            return

        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not todo_type:
            return

        created_count = 0
        for loan in overdue_loans:
            # Tramo C: Comprobación de no duplicidad (no duplicar si ya existe actividad abierta)
            existing_activity = self.env["mail.activity"].search(
                [
                    ("res_model", "=", "equipment.loan"),
                    ("res_id", "=", loan.id),
                    ("activity_type_id", "=", todo_type.id),
                ],
                limit=1,
            )
            if not existing_activity:
                loan.activity_schedule(
                    activity_type_id=todo_type.id,
                    summary=_("Préstamo vencido: %s") % loan.equipment_id.display_name,
                    note=_(
                        "El equipo <b>%s</b> prestado a <b>%s</b> tenía fecha de retorno "
                        "prevista para el <b>%s</b> y aún no ha sido devuelto."
                    )
                    % (loan.equipment_id.display_name, loan.user_id.name, loan.date_expected),
                    user_id=manager_user.id,
                    date_deadline=today,
                )
                created_count += 1

        _logger.info(
            "Cron Préstamos Vencidos: Se generaron %d actividades nuevas para préstamos vencidos.",
            created_count,
        )

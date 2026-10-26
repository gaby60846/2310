import logging
import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PaymentRequest(models.Model):
    _name = "payment.request"
    _description = "Solicitud de Pago a Proveedor"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Número",
        required=True,
        copy=False,
        readonly=True,
        default="/",
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Proveedor",
        required=True,
        tracking=True,
        domain="['|', ('supplier_rank', '>', 0), ('is_company', '=', True)]",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Solicitante",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    amount = fields.Monetary(
        string="Monto solicitado",
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    concept = fields.Text(
        string="Concepto del pago",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("submitted", "Enviada"),
            ("approved", "Aprobada"),
            ("paid", "Pagada"),
            ("rejected", "Rechazada"),
        ],
        string="Estado",
        default="draft",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )

    approver_id = fields.Many2one(
        "res.users",
        string="Aprobador Asignado",
        readonly=True,
        tracking=True,
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Aprobado por",
        readonly=True,
        copy=False,
    )
    date_approved = fields.Datetime(
        string="Fecha de aprobación",
        readonly=True,
        copy=False,
    )
    reject_reason = fields.Text(
        string="Motivo de rechazo",
        readonly=True,
        copy=False,
    )
    payment_id = fields.Many2one(
        "account.payment",
        string="Pago contable vinculado",
        readonly=True,
        copy=False,
    )

    _sql_constraints = [
        ("name_uniq", "unique(name, company_id)", "El número de la solicitud debe ser único por compañía."),
    ]

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("El monto de la solicitud debe ser estrictamente mayor a cero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("payment.request") or "/"
        return super().create(vals_list)

    def write(self, vals):
        """Inmutabilidad: una solicitud enviada o aprobada no puede ser modificada por el solicitante."""
        restricted_fields = {"partner_id", "amount", "currency_id", "date", "concept", "user_id"}
        for rec in self:
            if rec.state != "draft" and any(k in restricted_fields for k in vals):
                raise UserError(
                    _("No se puede modificar una solicitud de pago que ya ha sido enviada o procesada.")
                )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo se pueden eliminar solicitudes en estado borrador."))
        return super().unlink()

    def action_submit(self):
        """Asigna el nivel de aprobación adecuado según el monto y programa la actividad."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo se pueden enviar solicitudes en estado borrador."))

            # Buscar niveles de aprobación en la compañía
            # Se convierte el monto a la moneda del nivel si difieren
            levels = self.env["payment.approval.level"].search(
                [("company_id", "=", rec.company_id.id)],
                order="amount_min desc",
            )
            assigned_approver = None
            for level in levels:
                level_amount = rec.currency_id._convert(
                    rec.amount, level.currency_id, rec.company_id, rec.date or fields.Date.today()
                )
                if level_amount >= level.amount_min:
                    assigned_approver = level.approver_id
                    break

            if not assigned_approver:
                # Si no hay niveles configurados o ninguno supera el umbral, asigna al gerente del área/tesorería
                treasury_group = self.env.ref("payment_request.group_payment_request_treasury")
                assigned_approver = treasury_group.users[:1] or self.env.ref("base.user_admin")

            rec.write({
                "state": "submitted",
                "approver_id": assigned_approver.id,
            })

            # Crear actividad en el chatter
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=assigned_approver.id,
                summary=_("Aprobación requerida: %s para %s") % (rec.name, rec.partner_id.name),
                note=_("Por favor revise y apruebe la solicitud de pago por %s %s para %s.")
                % (rec.amount, rec.currency_id.name, rec.partner_id.name),
            )
        return True

    def action_approve(self):
        """Aprueba la solicitud con bloqueo pesimista contra condiciones de carrera (Tramo C)."""
        for rec in self:
            # 1. Bloqueo a nivel de Base de Datos (SELECT ... FOR UPDATE NOWAIT)
            try:
                self.env.cr.execute(
                    "SELECT id, state FROM payment_request WHERE id = %s FOR UPDATE NOWAIT",
                    [rec.id],
                )
                locked_row = self.env.cr.fetchone()
            except psycopg2.OperationalError:
                raise UserError(
                    _("La solicitud está siendo procesada concurrentemente por otro usuario. Por favor recargue.")
                )

            if not locked_row or locked_row[1] != "submitted":
                raise UserError(
                    _("La solicitud %s ya no se encuentra en estado 'Enviada'.") % rec.name
                )

            # 2. Control de Acceso: solo el aprobador asignado o administradores
            current_user = self.env.user
            is_assigned = rec.approver_id and current_user.id == rec.approver_id.id
            is_manager = current_user.has_group("payment_request.group_payment_request_treasury") or self.env.is_admin()

            if not (is_assigned or is_manager):
                raise UserError(
                    _("Solo el aprobador asignado (%s) tiene autorización para aprobar esta solicitud.")
                    % (rec.approver_id.name if rec.approver_id else "responsable")
                )

            # 3. Aplicar aprobación
            rec.write({
                "state": "approved",
                "approved_by_id": current_user.id,
                "date_approved": fields.Datetime.now(),
            })

            # Marcar actividades de aprobación pendientes como hechas
            rec.activity_feedback(["mail.mail_activity_data_todo"], feedback=_("Solicitud aprobada exitosamente."))
        return True

    def action_reject_wizard(self):
        """Abre el wizard para ingresar el motivo obligatorio de rechazo."""
        self.ensure_one()
        return {
            "name": _("Rechazar Solicitud de Pago"),
            "type": "ir.actions.act_window",
            "res_model": "payment.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payment_request_id": self.id},
        }

    def action_pay_wizard(self):
        """Abre el wizard de tesorería para registrar el pago contable."""
        self.ensure_one()
        return {
            "name": _("Registrar Pago de Solicitud"),
            "type": "ir.actions.act_window",
            "res_model": "payment.request.pay.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payment_request_id": self.id},
        }

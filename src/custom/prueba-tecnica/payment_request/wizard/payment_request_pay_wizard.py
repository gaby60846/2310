import psycopg2
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PaymentRequestPayWizard(models.TransientModel):
    _name = "payment.request.pay.wizard"
    _description = "Asistente de Pago para Solicitud de Proveedor"

    payment_request_id = fields.Many2one("payment.request", string="Solicitud", required=True)
    company_id = fields.Many2one(
        "res.company", related="payment_request_id.company_id", readonly=True
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario de pago",
        required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    payment_date = fields.Date(
        string="Fecha del pago",
        required=True,
        default=fields.Date.context_today,
    )
    request_currency_id = fields.Many2one(
        "res.currency", related="payment_request_id.currency_id", readonly=True
    )
    request_amount = fields.Monetary(
        string="Monto en moneda de solicitud",
        related="payment_request_id.amount",
        currency_field="request_currency_id",
        readonly=True,
    )
    payment_currency_id = fields.Many2one(
        "res.currency",
        string="Moneda del pago",
        compute="_compute_payment_currency_id",
        readonly=True,
    )
    payment_amount = fields.Monetary(
        string="Monto efectivo a pagar",
        currency_field="payment_currency_id",
        compute="_compute_payment_amount",
        store=True,
        readonly=False,
    )

    @api.depends("journal_id", "company_id")
    def _compute_payment_currency_id(self):
        for wiz in self:
            if wiz.journal_id and wiz.journal_id.currency_id:
                wiz.payment_currency_id = wiz.journal_id.currency_id
            else:
                wiz.payment_currency_id = wiz.company_id.currency_id or self.env.company.currency_id

    @api.depends("journal_id", "payment_date", "request_amount", "payment_currency_id")
    def _compute_payment_amount(self):
        for wiz in self:
            if not wiz.payment_request_id or not wiz.payment_currency_id:
                wiz.payment_amount = 0.0
                continue

            req = wiz.payment_request_id
            pay_currency = wiz.payment_currency_id
            req_currency = req.currency_id

            if req_currency == pay_currency:
                wiz.payment_amount = req.amount
            else:
                # Conversión a la tasa de la fecha de pago (Tramo C)
                wiz.payment_amount = req_currency._convert(
                    req.amount,
                    pay_currency,
                    wiz.company_id,
                    wiz.payment_date or fields.Date.today(),
                )

    def action_confirm_payment(self):
        """Crea el account.payment vinculado y marca la solicitud como pagada con bloqueo pesimista."""
        self.ensure_one()
        req = self.payment_request_id

        # 1. Bloqueo pesimista a nivel de base de datos contra pagos concurrentes
        try:
            self.env.cr.execute(
                "SELECT id, state FROM payment_request WHERE id = %s FOR UPDATE NOWAIT",
                [req.id],
            )
            locked_row = self.env.cr.fetchone()
        except psycopg2.OperationalError:
            raise UserError(
                _("La solicitud está siendo procesada en este momento por otro usuario. Intente nuevamente.")
            )

        if not locked_row or locked_row[1] != "approved":
            raise UserError(
                _("Solo se pueden pagar solicitudes en estado 'Aprobada'. Estado actual: %s.")
                % (locked_row[1] if locked_row else "no encontrada")
            )

        # 2. Validación estricta: Una solicitud no se puede pagar dos veces (Tramo B)
        if req.payment_id or req.state == "paid":
            raise UserError(_("Esta solicitud de pago ya ha sido pagada previamente."))

        if self.payment_amount <= 0:
            raise ValidationError(_("El monto a pagar debe ser mayor a cero."))

        pay_currency = self.payment_currency_id

        # 3. Creación y validación atómica del pago contable
        payment_vals = {
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": req.partner_id.id,
            "amount": self.payment_amount,
            "currency_id": pay_currency.id,
            "date": self.payment_date,
            "journal_id": self.journal_id.id,
            "ref": _("Solicitud %s: %s") % (req.name, req.concept[:50]),
            "payment_request_id": req.id,
        }

        # La creación ocurre dentro de la misma transacción; si account.payment falla,
        # Odoo revierte toda la transacción y la solicitud NO queda en 'paid'
        payment = self.env["account.payment"].create(payment_vals)
        payment.action_post()

        req.write({
            "state": "paid",
            "payment_id": payment.id,
        })

        # Notificación en chatter
        msg = _(
            "<b>Pago Registrado Exitosamente</b> por tesorería.<br/>"
            "Diario: %s<br/>"
            "Monto pagado: %s %s (Fecha: %s)<br/>"
            "Asiento/Pago contable: %s"
        ) % (
            self.journal_id.display_name,
            self.payment_amount,
            pay_currency.name,
            self.payment_date,
            payment.name,
        )
        req.message_post(body=msg, subtype_xmlid="mail.mt_comment")

        return {"type": "ir.actions.act_window_close"}


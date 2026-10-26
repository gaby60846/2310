from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    payment_request_id = fields.Many2one(
        "payment.request",
        string="Solicitud de Pago Origen",
        readonly=True,
        copy=False,
    )

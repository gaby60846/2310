from odoo import fields, models


class PaymentApprovalLevel(models.Model):
    _name = "payment.approval.level"
    _description = "Nivel de Aprobación de Solicitudes de Pago"
    _order = "amount_min desc, id asc"

    name = fields.Char(string="Descripción", required=True)
    amount_min = fields.Monetary(string="Monto mínimo", required=True)
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    approver_id = fields.Many2one("res.users", string="Aprobador responsable", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)


from odoo import fields, models


class ApiIdempotencyKey(models.Model):
    _name = "api.idempotency.key"
    _description = "Registro de Idempotencia para API"
    _order = "create_date desc, id desc"

    key = fields.Char(string="Clave de idempotencia", required=True, index=True)
    payload_hash = fields.Char(string="Hash SHA-256 del contenido", required=True)
    response_status = fields.Integer(string="Código HTTP almacenado", required=True)
    response_body = fields.Text(string="Cuerpo de respuesta JSON", required=True)
    order_id = fields.Many2one("sale.order", string="Pedido creado", ondelete="set null")

    _sql_constraints = [
        ("key_uniq", "unique(key)", "La clave de idempotencia debe ser única."),
    ]


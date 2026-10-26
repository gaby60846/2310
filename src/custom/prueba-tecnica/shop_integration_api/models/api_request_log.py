from odoo import fields, models


class ApiRequestLog(models.Model):
    _name = "api.request.log"
    _description = "Registro de peticiones API"
    _order = "create_date desc, id desc"

    endpoint = fields.Char(string="Endpoint", required=True, index=True)
    method = fields.Char(string="Método HTTP", default="GET")
    user_id = fields.Many2one("res.users", string="Usuario", index=True)
    status_code = fields.Integer(string="Código de respuesta", required=True, index=True)
    duration_ms = fields.Float(string="Duración (ms)", digits=(10, 2))
    ip_address = fields.Char(string="Dirección IP")


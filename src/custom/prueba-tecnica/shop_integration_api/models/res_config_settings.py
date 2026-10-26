from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    shop_webhook_url = fields.Char(
        string="URL del Webhook de la tienda",
        config_parameter="shop_integration_api.webhook_url",
        help="URL HTTP a la cual Odoo notificará cuando se valide la entrega de un pedido.",
    )
    shop_order_default_state = fields.Selection(
        [
            ("draft", "Cotización (Borrador)"),
            ("sale", "Pedido de venta confirmado"),
        ],
        string="Estado por defecto de pedidos API",
        default="draft",
        config_parameter="shop_integration_api.order_default_state",
        help="Decide si los pedidos creados por la API se crean en estado cotización o confirmados.",
    )


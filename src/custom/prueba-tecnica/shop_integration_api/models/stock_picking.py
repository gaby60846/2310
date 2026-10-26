import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            if picking.picking_type_code == "outgoing" and picking.sale_id:
                picking._trigger_delivery_webhook()
        return res

    def _trigger_delivery_webhook(self):
        """Dispara de forma asíncrona y protegida el webhook de entrega hacia la tienda."""
        self.ensure_one()
        url = self.env["ir.config_parameter"].sudo().get_param("shop_integration_api.webhook_url")
        if not url:
            return

        payload = {
            "event": "order.delivered",
            "order_id": self.sale_id.id,
            "order_name": self.sale_id.name,
            "client_order_ref": self.sale_id.client_order_ref or False,
            "picking_id": self.id,
            "picking_name": self.name,
            "tracking_number": getattr(self, "carrier_tracking_ref", False) or False,
            "date_done": str(self.date_done),
            "lines": [
                {
                    "default_code": move.product_id.default_code,
                    "product_name": move.product_id.name,
                    "qty_done": move.quantity if hasattr(move, "quantity") else move.product_uom_qty,
                }
                for move in self.move_ids.filtered(lambda m: m.state == "done")
            ],
        }

        try:
            webhook_log = self.env["api.webhook.log"].sudo().create({
                "target_url": url,
                "payload": json.dumps(payload),
                "picking_id": self.id,
                "state": "pending",
            })
            # Intento de envío inmediato sin bloquear el hilo principal si la tienda está caída
            webhook_log.action_send()
        except Exception as e:
            _logger.warning("No se pudo encolar el webhook de entrega para el albarán %s: %s", self.name, e)


import json
import logging
from datetime import timedelta
import urllib.request
import urllib.error

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ApiWebhookLog(models.Model):
    _name = "api.webhook.log"
    _description = "Registro y cola de reintentos para Webhooks"
    _order = "create_date desc, id desc"

    event = fields.Char(string="Evento", required=True, default="order.delivered")
    target_url = fields.Char(string="URL destino", required=True)
    payload = fields.Text(string="Cuerpo JSON enviado", required=True)
    state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("sent", "Enviado"),
            ("failed", "Fallido"),
        ],
        string="Estado",
        default="pending",
        required=True,
        index=True,
    )
    attempts = fields.Integer(string="Intentos realizados", default=0)
    max_attempts = fields.Integer(string="Máximo de intentos", default=5)
    last_attempt = fields.Datetime(string="Último intento")
    next_retry = fields.Datetime(string="Próximo reintento", index=True)
    response_code = fields.Integer(string="Código de respuesta HTTP")
    response_body = fields.Text(string="Respuesta del servidor")
    picking_id = fields.Many2one("stock.picking", string="Albarán de entrega", ondelete="set null")

    def action_send(self):
        """Intenta enviar el webhook de forma resiliente."""
        for log in self:
            log.attempts += 1
            log.last_attempt = fields.Datetime.now()
            headers = {"Content-Type": "application/json", "User-Agent": "Odoo-ShopIntegration/1.0"}
            data = log.payload.encode("utf-8")
            req = urllib.request.Request(log.target_url, data=data, headers=headers, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    status_code = response.getcode()
                    resp_body = response.read().decode("utf-8", errors="ignore")
                    log.write({
                        "response_code": status_code,
                        "response_body": resp_body[:2000],
                        "state": "sent" if 200 <= status_code < 300 else "failed",
                    })
            except urllib.error.HTTPError as e:
                resp_body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
                log.write({
                    "response_code": e.code,
                    "response_body": resp_body[:2000],
                    "state": "failed",
                    "next_retry": fields.Datetime.now() + timedelta(minutes=log.attempts * 5),
                })
                _logger.warning("Webhook a %s falló con HTTP %s", log.target_url, e.code)
            except Exception as e:
                log.write({
                    "response_code": 0,
                    "response_body": str(e)[:2000],
                    "state": "failed",
                    "next_retry": fields.Datetime.now() + timedelta(minutes=log.attempts * 5),
                })
                _logger.warning("Error de conexión al enviar webhook a %s: %s", log.target_url, e)

    @api.model
    def cron_process_webhooks(self):
        """Procesa webhooks pendientes o fallidos con fecha de reintento cumplida."""
        now = fields.Datetime.now()
        domain = [
            ("state", "in", ["pending", "failed"]),
            ("attempts", "<", 5),
            "|",
            ("next_retry", "=", False),
            ("next_retry", "<=", now),
        ]
        pending_logs = self.search(domain, limit=50)
        for log in pending_logs:
            log.action_send()
        return True

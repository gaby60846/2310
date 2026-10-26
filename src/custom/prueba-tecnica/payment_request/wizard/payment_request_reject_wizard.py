from odoo import _, fields, models
from odoo.exceptions import UserError


class PaymentRequestRejectWizard(models.TransientModel):
    _name = "payment.request.reject.wizard"
    _description = "Asistente de Rechazo de Solicitud de Pago"

    payment_request_id = fields.Many2one("payment.request", string="Solicitud", required=True)
    reason = fields.Text(string="Motivo del rechazo", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        req = self.payment_request_id
        if req.state != "submitted":
            raise UserError(_("Solo se pueden rechazar solicitudes en estado 'Enviada'."))

        if not self.reason or not self.reason.strip():
            raise UserError(_("Debe especificar un motivo obligatorio para rechazar la solicitud."))

        # Publicar motivo en el chatter
        message = _("<b>Solicitud Rechazada</b> por %s.<br/><b>Motivo:</b> %s") % (
            self.env.user.name,
            self.reason,
        )
        req.message_post(body=message, subtype_xmlid="mail.mt_comment")

        req.write({
            "state": "rejected",
            "reject_reason": self.reason,
        })

        # Cancelar actividades pendientes
        req.activity_feedback(["mail.mail_activity_data_todo"], feedback=_("Rechazada: %s") % self.reason)
        return {"type": "ir.actions.act_window_close"}


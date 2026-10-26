from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    commission_percent = fields.Float(
        string="Comisión (%)",
        digits=(5, 2),
        readonly=True,
        copy=False,
        help="Se fija al confirmar el pedido, para que la comisión no cambie si después se modifican los porcentajes.",
    )
    commission_amount = fields.Monetary(
        string="Comisión",
        compute="_compute_commission_amount",
        store=True,
    )

    @api.depends("commission_percent", "price_subtotal")
    def _compute_commission_amount(self):
        for line in self:
            line.commission_amount = line.price_subtotal * line.commission_percent / 100.0

    def _get_commission_percent(self):
        """Porcentaje de la categoría del producto (la más específica) o, si no hay, el del vendedor.

        Justificación del uso de sudo():
        El modelo `sale.commission.rule` y los porcentajes configurados en categorías de
        producto son datos confidenciales de configuración estratégica reservados a la
        gerencia de ventas (`groups='sales_team.group_sale_manager'`).
        Siguiendo el principio de menor privilegio, no se otorga acceso de lectura global
        a los vendedores sobre dicho modelo para evitar exposiciones indebidas vía API o RPC.
        Al confirmar el pedido, la consulta de reglas aplicables a la categoría del producto
        se ejecuta con `sudo()` de manera puntual y segura únicamente para determinar la tasa.

        Corrección T-200:
        1. Se agrega sudo() a la consulta de reglas para que los vendedores no reciban AccessError.
        2. Se reemplaza self.env.user por self.order_id.user_id para que, en caso de que un gerente
           o usuario delegado confirme el pedido, la comisión atribuida corresponda al vendedor
           titular del pedido y no al usuario confirmador.
        """
        self.ensure_one()
        rules = self.env["sale.commission.rule"].sudo().search([
            ("categ_id", "parent_of", self.product_id.categ_id.id),
            ("company_id", "in", [False, self.company_id.id]),
        ])
        if rules:
            return rules.sorted(lambda r: len(r.categ_id.parent_path or ""), reverse=True)[0].percent
        return self.order_id.user_id.commission_percent if self.order_id.user_id else 0.0

from odoo import api, fields, models


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    loan_ids = fields.One2many(
        "equipment.loan",
        "equipment_id",
        string="Préstamos",
        help="Historial de préstamos asociados a este equipo.",
    )
    loan_count = fields.Integer(
        string="Total Préstamos",
        compute="_compute_loan_count",
        help="Número total de préstamos históricos y activos de este equipo.",
    )
    current_loan_id = fields.Many2one(
        "equipment.loan",
        string="Préstamo en curso",
        compute="_compute_current_loan",
        help="Préstamo actualmente activo (en posesión de un usuario).",
    )

    # =========================================================================
    # RENDIMIENTO - TRAMO C: BATCH COMPUTATION O(1)
    # =========================================================================

    @api.depends("loan_ids")
    def _compute_loan_count(self):
        """Tramo C: Calcula el contador del smart button en lote (read_group),
        garantizando que la consulta SQL sea constante O(1) y no crezca con la cantidad de equipos.
        """
        loan_data = self.env["equipment.loan"].read_group(
            domain=[("equipment_id", "in", self.ids)],
            fields=["equipment_id"],
            groupby=["equipment_id"],
        )
        mapped = {
            group["equipment_id"][0]: group["equipment_id_count"]
            for group in loan_data
            if group.get("equipment_id")
        }
        for equipment in self:
            equipment.loan_count = mapped.get(equipment.id, 0)

    @api.depends("loan_ids.state")
    def _compute_current_loan(self):
        """Identifica de forma rápida qué préstamo activo tiene el equipo."""
        active_loans = self.env["equipment.loan"].search(
            [("equipment_id", "in", self.ids), ("state", "=", "loaned")]
        )
        loan_by_equipment = {loan.equipment_id.id: loan for loan in active_loans}
        for equipment in self:
            equipment.current_loan_id = loan_by_equipment.get(equipment.id, False)

    # =========================================================================
    # ACCIÓN DEL SMART BUTTON - TRAMO B
    # =========================================================================

    def action_view_loans(self):
        """Tramo B: Abre la lista de préstamos filtrada exclusivamente para este equipo."""
        self.ensure_one()
        return {
            "name": f"Préstamos: {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "equipment.loan",
            "view_mode": "tree,form",
            "domain": [("equipment_id", "=", self.id)],
            "context": {
                "default_equipment_id": self.id,
                "search_default_equipment_id": self.id,
            },
        }

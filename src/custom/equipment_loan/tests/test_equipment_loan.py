from datetime import timedelta
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestEquipmentLoan(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env.user)

        # Categoría de equipos
        cls.category = cls.env["maintenance.equipment.category"].create({
            "name": "Laptops & TI",
        })

        # Equipos de prueba
        cls.laptop_1 = cls.env["maintenance.equipment"].create({
            "name": "Laptop Dell XPS 15",
            "category_id": cls.category.id,
        })
        cls.laptop_2 = cls.env["maintenance.equipment"].create({
            "name": "Laptop Lenovo ThinkPad",
            "category_id": cls.category.id,
        })
        cls.projector = cls.env["maintenance.equipment"].create({
            "name": "Proyector Epson EB-X06",
            "category_id": cls.category.id,
        })

        # Usuarios de prueba: Gestor y Usuarios regulares
        cls.user_manager = new_test_user(
            cls.env,
            login="manager_soporte_ti",
            name="Jorge Lara (Gestor TI)",
            groups="equipment_loan.group_equipment_loan_manager,maintenance.group_equipment_manager",
        )
        cls.user_regular_1 = new_test_user(
            cls.env,
            login="empleado_pedro",
            name="Pedro Pérez",
            groups="base.group_user",
        )
        cls.user_regular_2 = new_test_user(
            cls.env,
            login="empleada_maria",
            name="María Gómez",
            groups="base.group_user",
        )

    # =========================================================================
    # TRAMO A: FLUJO BÁSICO, VALIDACIÓN DE FECHAS Y REGISTRO DE FECHA REAL
    # =========================================================================

    def test_loan_full_lifecycle(self):
        """Tramo A: Creación en borrador, entrega y devolución con fecha real registrada."""
        loan = self.env["equipment.loan"].with_user(self.user_regular_1).create({
            "equipment_id": self.laptop_1.id,
            "date_start": self.today,
            "date_expected": self.today + timedelta(days=3),
        })

        self.assertEqual(loan.state, "draft")
        self.assertEqual(loan.user_id, self.user_regular_1)
        self.assertFalse(loan.date_return)

        # Gestor realiza la entrega física
        loan.with_user(self.user_manager).action_deliver()
        self.assertEqual(loan.state, "loaned")
        self.assertFalse(loan.date_return)

        # Gestor registra la devolución
        loan.with_user(self.user_manager).action_return()
        self.assertEqual(loan.state, "returned")
        self.assertEqual(loan.date_return, self.today)

    def test_expected_return_before_delivery_blocked(self):
        """Tramo A: Una fecha prevista de devolución anterior a la entrega debe bloquearse."""
        with self.assertRaises(ValidationError):
            self.env["equipment.loan"].create({
                "equipment_id": self.laptop_1.id,
                "user_id": self.user_regular_1.id,
                "date_start": self.today,
                "date_expected": self.today - timedelta(days=1),
            })

    # =========================================================================
    # TRAMO B: REGLA DE NO DOBLE PRÉSTAMO, VENCIMIENTO Y SMART BUTTON
    # =========================================================================

    def test_prevent_double_active_loan_same_equipment(self):
        """Tramo B: Un equipo no puede tener dos préstamos activos a la vez (interfaz o código)."""
        # Préstamo 1 activo
        loan1 = self.env["equipment.loan"].with_user(self.user_manager).create({
            "equipment_id": self.laptop_1.id,
            "user_id": self.user_regular_1.id,
            "date_start": self.today,
            "date_expected": self.today + timedelta(days=5),
        })
        loan1.action_deliver()
        self.assertEqual(loan1.state, "loaned")

        # Intento de Préstamo 2 para el mismo equipo mientras el 1 sigue activo
        loan2 = self.env["equipment.loan"].with_user(self.user_manager).create({
            "equipment_id": self.laptop_1.id,
            "user_id": self.user_regular_2.id,
            "date_start": self.today,
            "date_expected": self.today + timedelta(days=2),
        })

        # Al intentar entregar debe ser bloqueado por la regla de negocio
        with self.assertRaises(ValidationError):
            loan2.action_deliver()

        # Tampoco debe poder forzarse directamente desde código (write/create en estado 'loaned')
        with self.assertRaises(ValidationError):
            loan2.write({"state": "loaned"})

    def test_overdue_dynamic_calculation_and_search(self):
        """Tramo B: El préstamo vencido se calcula dinámicamente y el filtro en búsqueda funciona."""
        # Préstamo 1: Vencido (fecha prevista ayer)
        loan_overdue = self.env["equipment.loan"].with_user(self.user_manager).create({
            "equipment_id": self.laptop_1.id,
            "user_id": self.user_regular_1.id,
            "date_start": self.today - timedelta(days=5),
            "date_expected": self.today - timedelta(days=1),
        })
        loan_overdue.action_deliver()
        self.assertTrue(loan_overdue.is_overdue)

        # Préstamo 2: Al día (fecha prevista en 3 días)
        loan_ontime = self.env["equipment.loan"].with_user(self.user_manager).create({
            "equipment_id": self.laptop_2.id,
            "user_id": self.user_regular_2.id,
            "date_start": self.today,
            "date_expected": self.today + timedelta(days=3),
        })
        loan_ontime.action_deliver()
        self.assertFalse(loan_ontime.is_overdue)

        # Búsqueda usando el campo search dinámico
        overdue_search = self.env["equipment.loan"].search([("is_overdue", "=", True)])
        self.assertIn(loan_overdue, overdue_search)
        self.assertNotIn(loan_ontime, overdue_search)

    def test_smart_button_loan_count_and_action(self):
        """Tramo B: Smart button muestra la cantidad total de préstamos y abre la vista filtrada."""
        # Crear 2 préstamos para el proyector
        l1 = self.env["equipment.loan"].create({
            "equipment_id": self.projector.id,
            "user_id": self.user_regular_1.id,
            "date_start": self.today,
            "date_expected": self.today + timedelta(days=1),
        })
        l2 = self.env["equipment.loan"].create({
            "equipment_id": self.projector.id,
            "user_id": self.user_regular_2.id,
            "date_start": self.today,
            "date_expected": self.today + timedelta(days=2),
        })

        self.assertEqual(self.projector.loan_count, 2)

        # Comprobar la acción del botón inteligente
        action = self.projector.action_view_loans()
        self.assertEqual(action["res_model"], "equipment.loan")
        self.assertIn(("equipment_id", "=", self.projector.id), action["domain"])

    # =========================================================================
    # TRAMO C: SEGURIDAD, CONCURRENCIA, RENDIMIENTO O(1) Y CRON SIN DUPLICADOS
    # =========================================================================

    def test_security_regular_user_cannot_see_others_nor_deliver(self):
        """Tramo C: Usuario sin grupo Gestor no ve préstamos ajenos ni puede entregar/devolver."""
        loan_user1 = self.env["equipment.loan"].with_user(self.user_regular_1).create({
            "equipment_id": self.laptop_1.id,
            "date_start": self.today,
            "date_expected": self.today + timedelta(days=2),
        })

        # Usuario 2 no debe ver el préstamo de Usuario 1
        loans_seen_by_user2 = self.env["equipment.loan"].with_user(self.user_regular_2).search([])
        self.assertNotIn(loan_user1, loans_seen_by_user2)

        # Usuario 1 no tiene permiso para accionar Entregar ni Devolver
        with self.assertRaises(AccessError):
            loan_user1.with_user(self.user_regular_1).action_deliver()

        # El gestor sí lo puede entregar
        loan_user1.with_user(self.user_manager).action_deliver()

        # Usuario 1 no puede devolver directamente
        with self.assertRaises(AccessError):
            loan_user1.with_user(self.user_regular_1).action_return()

    def test_smart_button_batch_computation_performance(self):
        """Tramo C: El contador del botón inteligente se calcula en lote O(1) con read_group."""
        # Crear 5 equipos adicionales
        equipments = self.env["maintenance.equipment"].create([
            {"name": f"Equipo Batch {i}", "category_id": self.category.id} for i in range(5)
        ])
        for eq in equipments:
            self.env["equipment.loan"].create({
                "equipment_id": eq.id,
                "user_id": self.user_regular_1.id,
                "date_start": self.today,
                "date_expected": self.today + timedelta(days=1),
            })

        # Medir que _compute_loan_count no ejecuta N consultas adicionales
        count0 = self.cr.sql_log_count
        equipments._compute_loan_count()
        query_count = self.cr.sql_log_count - count0

        # Para 5 equipos, un read_group hace exactamente 1 consulta agregada
        self.assertLessEqual(query_count, 5, "El cómputo de préstamos debe ejecutarse en lote con read_group")
        for eq in equipments:
            self.assertEqual(eq.loan_count, 1)

    def test_cron_overdue_loans_does_not_duplicate_activities(self):
        """Tramo C: La acción planificada crea actividades por préstamos vencidos sin duplicarlas."""
        overdue_loan = self.env["equipment.loan"].with_user(self.user_manager).create({
            "equipment_id": self.laptop_2.id,
            "user_id": self.user_regular_1.id,
            "date_start": self.today - timedelta(days=4),
            "date_expected": self.today - timedelta(days=1),
        })
        overdue_loan.action_deliver()

        # Primera ejecución del Cron
        self.env["equipment.loan"]._cron_check_overdue_loans()
        todo_type = self.env.ref("mail.mail_activity_data_todo")
        overdue_loan.invalidate_recordset(["activity_ids"])
        activities_run1 = overdue_loan.activity_ids.filtered(lambda a: a.activity_type_id == todo_type)
        self.assertEqual(len(activities_run1), 1)

        # Segunda ejecución del Cron: NO debe duplicar la actividad
        self.env["equipment.loan"]._cron_check_overdue_loans()
        overdue_loan.invalidate_recordset(["activity_ids"])
        activities_run2 = overdue_loan.activity_ids.filtered(lambda a: a.activity_type_id == todo_type)
        self.assertEqual(len(activities_run2), 1, "La acción planificada no debe duplicar actividades abiertas.")

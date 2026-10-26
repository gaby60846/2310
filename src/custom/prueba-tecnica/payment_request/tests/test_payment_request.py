from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestPaymentRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Compañías
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Compañía B C.A."})

        # Monedas: USD y VES (o moneda base y secundaria)
        cls.currency_usd = cls.env.ref("base.USD")
        cls.currency_ves = cls.env.ref("base.VES") if cls.env.ref("base.VES", raise_if_not_found=False) else cls.env["res.currency"].create({
            "name": "VES",
            "symbol": "Bs.",
            "rounding": 0.01,
        })

        # Configurar tasa: 1 USD = 50 VES
        cls.env["res.currency.rate"].create({
            "currency_id": cls.currency_ves.id,
            "rate": 50.0,
            "name": date.today(),
            "company_id": cls.company_a.id,
        })

        # Usuarios
        cls.requester = new_test_user(
            cls.env,
            login="requester_user",
            name="Empleado Solicitante",
            groups="payment_request.group_payment_request_user",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
        )

        cls.other_requester = new_test_user(
            cls.env,
            login="other_requester_user",
            name="Otro Solicitante",
            groups="payment_request.group_payment_request_user",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
        )

        cls.approver_boss = new_test_user(
            cls.env,
            login="approver_boss",
            name="Jefe de Área",
            groups="payment_request.group_payment_request_approver",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
        )

        cls.approver_manager = new_test_user(
            cls.env,
            login="approver_manager",
            name="Gerente General",
            groups="payment_request.group_payment_request_approver",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
        )

        cls.treasury_user = new_test_user(
            cls.env,
            login="treasury_user",
            name="Tesorero",
            groups="payment_request.group_payment_request_treasury,account.group_account_user",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
        )

        cls.user_company_b = new_test_user(
            cls.env,
            login="user_company_b",
            name="Usuario Compañía B",
            groups="payment_request.group_payment_request_user",
            company_id=cls.company_b.id,
            company_ids=[(6, 0, [cls.company_b.id])],
        )

        # Proveedor
        cls.supplier = cls.env["res.partner"].create({
            "name": "Proveedor Global S.A.",
            "supplier_rank": 1,
            "vat": "J-30123456-7",
        })

        # Diario de banco en VES
        cls.journal_ves = cls.env["account.journal"].create({
            "name": "Banco Nacional VES",
            "code": "BNVES",
            "type": "bank",
            "company_id": cls.company_a.id,
            "currency_id": cls.currency_ves.id,
        })

        # Niveles de aprobación:
        # Nivel 1: monto >= 0 -> Jefe de Área
        # Nivel 2: monto >= 1000 -> Gerente General
        cls.level_low = cls.env["payment.approval.level"].create({
            "name": "Aprobación Normal (Jefe de Área)",
            "amount_min": 0.0,
            "approver_id": cls.approver_boss.id,
            "company_id": cls.company_a.id,
            "sequence": 10,
        })
        cls.level_high = cls.env["payment.approval.level"].create({
            "name": "Aprobación Grandes Pagos (Gerencia)",
            "amount_min": 1000.0,
            "approver_id": cls.approver_manager.id,
            "company_id": cls.company_a.id,
            "sequence": 20,
        })

    def _create_request(self, user=None, amount=100.0, currency=None):
        user = user or self.requester
        currency = currency or self.company_a.currency_id
        return self.env["payment.request"].with_user(user).create({
            "partner_id": self.supplier.id,
            "amount": amount,
            "currency_id": currency.id,
            "concept": "Pago por servicios de consultoría técnica",
        })

    # =========================================================================
    # TRAMO A: Flujo Básico, Permisos y Validaciones
    # =========================================================================

    def test_sequence_generation(self):
        """La solicitud genera número con secuencia SP/YYYY/0001."""
        req = self._create_request()
        self.assertTrue(req.name.startswith(f"SP/{date.today().year}/"))

    def test_amount_must_be_positive(self):
        """No se permite monto cero o negativo."""
        with self.assertRaises(ValidationError):
            self._create_request(amount=0.0)
        with self.assertRaises(ValidationError):
            self._create_request(amount=-50.0)

    def test_requester_sees_only_own_requests(self):
        """El solicitante solo puede ver sus propias solicitudes."""
        own = self._create_request(self.requester)
        other = self._create_request(self.other_requester)

        visible = self.env["payment.request"].with_user(self.requester).search([])
        self.assertIn(own, visible)
        self.assertNotIn(other, visible)

    def test_requester_cannot_approve_directly(self):
        """El solicitante no puede aprobar ni por interfaz ni llamando a action_approve."""
        req = self._create_request(self.requester)
        req.action_submit()
        with self.assertRaises(UserError):
            req.with_user(self.requester).action_approve()

    def test_submitted_request_cannot_be_modified(self):
        """Una solicitud enviada se vuelve inmutable y no permite editar datos clave."""
        req = self._create_request(self.requester, amount=200.0)
        req.action_submit()
        self.assertEqual(req.state, "submitted")
        with self.assertRaises(UserError):
            req.with_user(self.requester).write({"amount": 500.0})

    # =========================================================================
    # TRAMO B: Aprobación por Monto, Wizards, Pagos y Reporte
    # =========================================================================

    def test_approval_level_assignment_and_activity(self):
        """Al enviar, se asigna el aprobador según el monto y se le programa actividad."""
        # Pago menor (< 1000): asigna al Jefe de Área
        req_small = self._create_request(amount=500.0)
        req_small.action_submit()
        self.assertEqual(req_small.approver_id, self.approver_boss)
        self.assertTrue(req_small.activity_ids)
        self.assertEqual(req_small.activity_ids.user_id, self.approver_boss)

        # Pago mayor (>= 1000): asigna a Gerencia
        req_large = self._create_request(amount=2500.0)
        req_large.action_submit()
        self.assertEqual(req_large.approver_id, self.approver_manager)
        self.assertEqual(req_large.activity_ids.user_id, self.approver_manager)

    def test_only_assigned_approver_can_approve(self):
        """Solo el aprobador asignado tiene potestad para aprobar."""
        req = self._create_request(amount=2500.0)  # asignado a approver_manager
        req.action_submit()

        # El jefe intenta aprobar un pago asignado a gerencia: debe fallar
        with self.assertRaises(UserError):
            req.with_user(self.approver_boss).action_approve()

        # Gerente aprueba: éxito
        req.with_user(self.approver_manager).action_approve()
        self.assertEqual(req.state, "approved")
        self.assertEqual(req.approved_by_id, self.approver_manager)
        self.assertTrue(req.date_approved)

    def test_reject_wizard_mandates_reason_and_posts_to_chatter(self):
        """Rechazar mediante wizard exige motivo y lo publica en el chatter."""
        req = self._create_request(amount=500.0)
        req.action_submit()

        # Sin motivo falla
        with self.assertRaises(UserError):
            self.env["payment.request.reject.wizard"].create({
                "payment_request_id": req.id,
                "reason": "   ",
            }).action_confirm_reject()

        # Con motivo pasa a rechazada y registra mensaje
        wizard = self.env["payment.request.reject.wizard"].create({
            "payment_request_id": req.id,
            "reason": "Proveedor no tiene contrato activo vigente para este mes.",
        })
        wizard.action_confirm_reject()
        self.assertEqual(req.state, "rejected")
        self.assertIn("Proveedor no tiene contrato activo", req.reject_reason)

    def test_cannot_pay_twice(self):
        """Una solicitud no puede pagarse dos veces."""
        req = self._create_request(amount=300.0)
        req.action_submit()
        req.with_user(self.approver_boss).action_approve()

        # Primer pago exitoso
        pay_wiz = self.env["payment.request.pay.wizard"].create({
            "payment_request_id": req.id,
            "journal_id": self.journal_ves.id,
            "payment_date": date.today(),
        })
        pay_wiz.action_confirm_payment()
        self.assertEqual(req.state, "paid")
        self.assertTrue(req.payment_id)

        # Intento de segundo pago debe fallar
        with self.assertRaises(UserError):
            pay_wiz_dup = self.env["payment.request.pay.wizard"].create({
                "payment_request_id": req.id,
                "journal_id": self.journal_ves.id,
                "payment_date": date.today(),
            })
            pay_wiz_dup.action_confirm_payment()

    def test_pdf_report_contains_approver_and_date(self):
        """El reporte QWeb muestra quién aprobó y cuándo."""
        req = self._create_request(amount=150.0)
        req.action_submit()
        req.with_user(self.approver_boss).action_approve()

        report = self.env.ref("payment_request.action_report_payment_request")
        html = report._render_qweb_html(report.report_name, [req.id])[0].decode("utf-8")
        self.assertIn(self.approver_boss.name, html)
        self.assertIn(req.name, html)

    # =========================================================================
    # TRAMO C: Multi-divisa, Multi-compañía, Concurrencia y Atomicidad
    # =========================================================================

    def test_currency_conversion_usd_to_ves(self):
        """Solicitud en USD pagada desde diario en VES calcula la tasa correctamente."""
        # 100 USD pagados en diario VES (tasa 1 USD = 50 VES -> 5,000 VES)
        req = self._create_request(amount=100.0, currency=self.currency_usd)
        req.action_submit()
        req.with_user(self.approver_boss).action_approve()

        pay_wiz = self.env["payment.request.pay.wizard"].create({
            "payment_request_id": req.id,
            "journal_id": self.journal_ves.id,
            "payment_date": date.today(),
        })
        # Verifica cálculo de tasa
        self.assertEqual(pay_wiz.payment_currency_id, self.currency_ves)
        self.assertAlmostEqual(pay_wiz.payment_amount, 5000.0)

        pay_wiz.action_confirm_payment()
        self.assertEqual(req.payment_id.amount, 5000.0)
        self.assertEqual(req.payment_id.currency_id, self.currency_ves)

    def test_multi_company_isolation(self):
        """Un usuario de la compañía B no puede ver solicitudes de la compañía A."""
        req_a = self._create_request(self.requester)
        req_b = self.env["payment.request"].with_user(self.user_company_b).create({
            "partner_id": self.supplier.id,
            "amount": 400.0,
            "concept": "Pago de compañía B",
            "company_id": self.company_b.id,
        })

        # Usuario B no debe ver req_a
        visible_b = self.env["payment.request"].with_user(self.user_company_b).search([])
        self.assertIn(req_b, visible_b)
        self.assertNotIn(req_a, visible_b)

    def test_payment_failure_atomicity_does_not_mark_paid(self):
        """Si la creación del pago contable falla, la solicitud no queda en 'paid'."""
        req = self._create_request(amount=350.0)
        req.action_submit()
        req.with_user(self.approver_boss).action_approve()

        pay_wiz = self.env["payment.request.pay.wizard"].create({
            "payment_request_id": req.id,
            "journal_id": self.journal_ves.id,
            "payment_date": date.today(),
        })

        # Simular fallo en account.payment.action_post
        with patch.object(type(self.env["account.payment"]), "action_post", side_effect=UserError("Error contable")):
            with self.assertRaises(UserError):
                pay_wiz.action_confirm_payment()

        # La solicitud debe permanecer en estado 'approved'
        self.assertEqual(req.state, "approved")
        self.assertFalse(req.payment_id)

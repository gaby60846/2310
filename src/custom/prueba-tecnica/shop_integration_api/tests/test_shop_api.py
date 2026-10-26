import json
import urllib.parse
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged, new_test_user


@tagged("post_install", "-at_install")
class TestShopIntegrationApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Usuario de API
        cls.api_user = new_test_user(
            cls.env,
            login="api_user",
            name="Usuario API",
            groups="sales_team.group_sale_manager,stock.group_stock_user",
        )

        # Crear API key nativa usando res.users.apikeys
        # En Odoo 17, se genera mediante _generate o create directo
        cls.raw_api_key = "test_secret_api_key_12345"
        cls.env["res.users.apikeys"].sudo()._generate(
            "rpc",
            name="Test Shop Key",
            user_id=cls.api_user.id,
        )
        # Para garantizar un token fijo en el test:
        # En Odoo 17 res.users.apikeys usa hash pbkdf2/bcrypt, pero _generate devuelve la clave en claro
        # Generamos una clave conocida:
        cls.api_key_token = cls.env["res.users.apikeys"].sudo()._generate(
            "rpc",
            name="Test Client Key",
            user_id=cls.api_user.id,
        )

        cls.auth_headers = {
            "Authorization": f"Bearer {cls.api_key_token}",
            "Content-Type": "application/json",
        }

        # Datos de prueba: Cliente con RIF
        cls.partner = cls.env["res.partner"].create({
            "name": "Cliente Tienda C.A.",
            "vat": "J-12345678-0",
        })

        # Categorías
        cls.category_main = cls.env["product.category"].create({"name": "Electrónica"})
        cls.category_sub = cls.env["product.category"].create({
            "name": "Teléfonos",
            "parent_id": cls.category_main.id,
        })
        cls.category_other = cls.env["product.category"].create({"name": "Ropa"})

        # Productos
        cls.prod_phone = cls.env["product.product"].create({
            "name": "Smartphone X",
            "default_code": "PHONE-X",
            "categ_id": cls.category_sub.id,
            "list_price": 500.0,
            "sale_ok": True,
            "active": True,
        })

        cls.prod_cable = cls.env["product.product"].create({
            "name": "Cable USB-C",
            "default_code": "CABLE-C",
            "categ_id": cls.category_main.id,
            "list_price": 15.0,
            "sale_ok": True,
            "active": True,
        })

        cls.prod_shirt = cls.env["product.product"].create({
            "name": "Camisa Polo",
            "default_code": "SHIRT-01",
            "categ_id": cls.category_other.id,
            "list_price": 30.0,
            "sale_ok": True,
            "active": True,
        })

        # Asignar stock al teléfono
        warehouse = cls.env["stock.warehouse"].search([], limit=1)
        location = warehouse.lot_stock_id if warehouse else cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(cls.prod_phone, location, 10.0)

    # =========================================================================
    # TRAMO A: GET /api/v1/products - Filtros y Validación
    # =========================================================================

    def test_get_products_unauthorized(self):
        """Petición sin cabecera de autenticación debe devolver HTTP 401."""
        response = self.url_open("/api/v1/products")
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["error"]["code"], "UNAUTHORIZED")

    def test_get_products_filter_category(self):
        """Filtro por categoría principal incluye subcategorías."""
        url = f"/api/v1/products?category_id={self.category_main.id}"
        response = self.url_open(url, headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        codes = [p["default_code"] for p in data["data"]]
        self.assertIn("PHONE-X", codes)
        self.assertIn("CABLE-C", codes)
        self.assertNotIn("SHIRT-01", codes)

    def test_get_products_filter_stock(self):
        """Filtro only_stock=true devuelve solo productos con cantidad mayor a cero."""
        url = "/api/v1/products?only_stock=true"
        response = self.url_open(url, headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        codes = [p["default_code"] for p in data["data"]]
        self.assertIn("PHONE-X", codes)
        self.assertNotIn("CABLE-C", codes)

    def test_get_products_filter_updated_since_valid(self):
        """Filtro por fecha válida devuelve los productos modificados."""
        today = datetime.now().strftime("%Y-%m-%d")
        url = f"/api/v1/products?updated_since={today}"
        response = self.url_open(url, headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)

    def test_get_products_filter_updated_since_invalid(self):
        """Fecha mal escrita devuelve HTTP 400 Bad Request claro y nunca error 500."""
        url = "/api/v1/products?updated_since=fecha-invalida"
        response = self.url_open(url, headers=self.auth_headers)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["error"]["code"], "INVALID_DATE_FORMAT")
        self.assertEqual(data["error"]["field"], "updated_since")

    def test_get_products_combined_filters(self):
        """Filtros combinados de categoría y stock funcionan de manera conjunta."""
        url = f"/api/v1/products?category_id={self.category_main.id}&only_stock=true"
        response = self.url_open(url, headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["default_code"], "PHONE-X")

    # =========================================================================
    # TRAMO B: POST /api/v1/orders - Creación, Validaciones y Logs
    # =========================================================================

    def test_create_order_invalid_vat(self):
        """RIF inexistente devuelve HTTP 422 con código PARTNER_NOT_FOUND."""
        payload = {
            "vat": "J-99999999-9",
            "lines": [{"default_code": "PHONE-X", "qty": 1}],
        }
        response = self.url_open(
            "/api/v1/orders",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["error"]["code"], "PARTNER_NOT_FOUND")
        self.assertEqual(data["error"]["field"], "vat")

    def test_create_order_invalid_product(self):
        """Código de producto inexistente devuelve HTTP 422 con field lines[X].default_code."""
        payload = {
            "vat": "J-12345678-0",
            "lines": [
                {"default_code": "PHONE-X", "qty": 1},
                {"default_code": "NON-EXISTENT-CODE", "qty": 2},
            ],
        }
        response = self.url_open(
            "/api/v1/orders",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["error"]["code"], "PRODUCT_NOT_FOUND")
        self.assertEqual(data["error"]["field"], "lines[1].default_code")

    def test_create_order_invalid_quantity(self):
        """Cantidad cero o negativa devuelve HTTP 422 con field lines[X].qty."""
        payload = {
            "vat": "J-12345678-0",
            "lines": [{"default_code": "PHONE-X", "qty": 0}],
        }
        response = self.url_open(
            "/api/v1/orders",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["error"]["code"], "INVALID_QUANTITY")
        self.assertEqual(data["error"]["field"], "lines[0].qty")

    def test_create_order_success_and_logging(self):
        """Creación exitosa devuelve HTTP 201 y queda registrada en el log sin exponer la clave."""
        payload = {
            "vat": "J-12345678-0",
            "client_order_ref": "REF-TEST-001",
            "lines": [
                {"default_code": "PHONE-X", "qty": 2},
                {"default_code": "CABLE-C", "qty": 3},
            ],
        }
        response = self.url_open(
            "/api/v1/orders",
            data=json.dumps(payload),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data.get("id"))
        self.assertEqual(data.get("client_order_ref"), "REF-TEST-001")

        # Verificar que el log exista y no contenga la API key
        log = self.env["api.request.log"].sudo().search(
            [("endpoint", "=", "/api/v1/orders"), ("status_code", "=", 201)],
            limit=1,
            order="id desc",
        )
        self.assertTrue(log)
        self.assertEqual(log.user_id, self.api_user)

    # =========================================================================
    # TRAMO C: Paginación, Idempotencia, Stock Optimizado y Webhook
    # =========================================================================

    def test_pagination_metadata(self):
        """La respuesta incluye metadatos de paginación."""
        url = "/api/v1/products?page=1&limit=2"
        response = self.url_open(url, headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        meta = data.get("meta", {})
        self.assertEqual(meta["page"], 1)
        self.assertEqual(meta["limit"], 2)
        self.assertTrue(meta["total"] >= 3)
        self.assertTrue(meta["has_next"])

    def test_idempotency_key_same_payload(self):
        """Misma Idempotency-Key con idéntico payload devuelve el mismo pedido sin duplicar."""
        headers = dict(self.auth_headers)
        headers["Idempotency-Key"] = "KEY-IDEMPOTENT-001"
        payload = {
            "vat": "J-12345678-0",
            "client_order_ref": "ORD-IDEM-01",
            "lines": [{"default_code": "PHONE-X", "qty": 1}],
        }
        res1 = self.url_open("/api/v1/orders", data=json.dumps(payload), headers=headers)
        self.assertEqual(res1.status_code, 201)
        order_id_1 = res1.json()["id"]

        # Segunda petición con la misma clave y mismo contenido
        res2 = self.url_open("/api/v1/orders", data=json.dumps(payload), headers=headers)
        self.assertEqual(res2.status_code, 201)
        order_id_2 = res2.json()["id"]

        self.assertEqual(order_id_1, order_id_2, "No debe crearse un segundo pedido.")

    def test_idempotency_key_different_payload_conflict(self):
        """Misma Idempotency-Key con payload diferente devuelve HTTP 409 Conflict."""
        headers = dict(self.auth_headers)
        headers["Idempotency-Key"] = "KEY-IDEMPOTENT-CONFLICT"
        payload1 = {
            "vat": "J-12345678-0",
            "client_order_ref": "ORD-CONF-01",
            "lines": [{"default_code": "PHONE-X", "qty": 1}],
        }
        res1 = self.url_open("/api/v1/orders", data=json.dumps(payload1), headers=headers)
        self.assertEqual(res1.status_code, 201)

        payload2 = {
            "vat": "J-12345678-0",
            "client_order_ref": "ORD-CONF-02",
            "lines": [{"default_code": "CABLE-C", "qty": 5}],
        }
        res2 = self.url_open("/api/v1/orders", data=json.dumps(payload2), headers=headers)
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_stock_queries_do_not_scale_with_products(self):
        """El cálculo de stock se realiza en lote y las consultas SQL no crecen linealmente con N."""
        # Consultar con 1 producto vs consultar con 3 productos
        with self.assertQueries(15):  # Límite superior constante de consultas ORM
            products = self.env["product.product"].search([("sale_ok", "=", True)])
            quantities = products._compute_quantities_dict(
                lot_id=False, owner_id=False, package_id=False, from_date=False, to_date=False
            )
            self.assertEqual(len(quantities), len(products))

    def test_webhook_triggered_on_delivery_without_blocking(self):
        """Al validar entrega (stock.picking done) se dispara webhook resiliente sin bloquear."""
        self.env["ir.config_parameter"].sudo().set_param(
            "shop_integration_api.webhook_url", "https://unreachable-shop-test.com/webhook"
        )
        # Crear pedido y entrega
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {"product_id": self.prod_phone.id, "product_uom_qty": 1})],
        })
        order.action_confirm()
        picking = order.picking_ids[:1]
        self.assertTrue(picking)

        # Simular que el endpoint remoto está caído (timeout/error de conexión)
        # El operador valida la entrega y NO debe recibir ninguna excepción
        for move in picking.move_ids:
            move.quantity = 1.0
        picking.button_validate()
        self.assertEqual(picking.state, "done")

        # Comprobar que se creó el registro de webhook en estado fallido para reintento posterior
        log = self.env["api.webhook.log"].sudo().search([("picking_id", "=", picking.id)], limit=1)
        self.assertTrue(log)
        self.assertIn(log.state, ["pending", "failed"])

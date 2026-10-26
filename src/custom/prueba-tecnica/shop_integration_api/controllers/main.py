import hashlib
import json
import logging
import time
from datetime import datetime

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _make_error_response(status_code, code, message, field=None):
    """Genera la estructura de error JSON estándar exigida por la prueba técnica."""
    payload = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if field:
        payload["error"]["field"] = field
    return request.make_json_response(payload, status=status_code)


def _log_api_request(endpoint, user, status_code, start_time):
    """Registra la llamada en api.request.log. NUNCA guarda credenciales o tokens."""
    duration_ms = (time.perf_counter() - start_time) * 1000.0
    try:
        ip = request.httprequest.remote_addr or ""
        request.env["api.request.log"].sudo().create({
            "endpoint": endpoint,
            "method": request.httprequest.method,
            "user_id": user.id if user else False,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "ip_address": ip,
        })
    except Exception as e:
        _logger.warning("No se pudo registrar log de API: %s", e)


def _authenticate_request():
    """Valida la autenticación por token Bearer nativo (res.users.apikeys) o sesión de usuario activa."""
    auth_header = request.httprequest.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            try:
                # Odoo 17 res.users.apikeys nativo
                user_id = request.env["res.users.apikeys"]._check_credentials(scope="rpc", key=token)
                if user_id:
                    user = request.env["res.users"].browse(user_id)
                    if user.exists() and user.active:
                        return user
            except Exception as e:
                _logger.debug("Error validando API Key nativa: %s", e)
        return None

    # Fallback: sesión de usuario autenticada previamente (para auth='user' tradicional)
    if request.session.uid:
        user = request.env.user
        if user and not user._is_public():
            return user

    return None


class ShopIntegrationApiController(http.Controller):

    @http.route("/api/v1/products", type="http", auth="none", methods=["GET"], csrf=False)
    def get_products(self, **params):
        """GET /api/v1/products: Consulta productos activos con filtros, paginación y stock en lote."""
        start_time = time.perf_counter()
        user = _authenticate_request()
        if not user:
            status = 401
            _log_api_request("/api/v1/products", None, status, start_time)
            return _make_error_response(
                status,
                "UNAUTHORIZED",
                "Autenticación requerida. Proporcione la cabecera 'Authorization: Bearer <API_KEY>' o inicie sesión.",
            )

        env = request.env(user=user)

        # Filtro 1: Solo productos activos que se pueden vender
        domain = [("sale_ok", "=", True), ("active", "=", True)]

        # Filtro 2: Categoría opcional
        category_param = params.get("category_id") or params.get("category")
        if category_param:
            try:
                category_id = int(category_param)
                domain.append(("categ_id", "child_of", category_id))
            except ValueError:
                status = 400
                _log_api_request("/api/v1/products", user, status, start_time)
                return _make_error_response(
                    status, "INVALID_PARAMETER", "El parámetro 'category_id' debe ser un número entero.", "category_id"
                )

        # Filtro 3: Modificados desde fecha (updated_since / modified_since)
        date_param = params.get("updated_since") or params.get("modified_since")
        if date_param:
            parsed_date = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed_date = datetime.strptime(date_param, fmt)
                    break
                except ValueError:
                    continue
            if not parsed_date:
                status = 400
                _log_api_request("/api/v1/products", user, status, start_time)
                return _make_error_response(
                    status,
                    "INVALID_DATE_FORMAT",
                    "El formato de la fecha debe ser 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'.",
                    "updated_since",
                )
            domain.append(("write_date", ">=", parsed_date))

        # Paginación
        try:
            page = max(1, int(params.get("page", 1)))
            limit = min(100, max(1, int(params.get("limit", 20))))
        except ValueError:
            page = 1
            limit = 20

        offset = (page - 1) * limit
        Product = env["product.product"]

        # Filtro 4: Solo con stock (in_stock / only_stock)
        only_stock = str(params.get("only_stock", params.get("in_stock", ""))).lower() in ("1", "true", "yes")

        total = Product.search_count(domain)
        products = Product.search(domain, order="id asc", limit=limit if not only_stock else 0, offset=offset if not only_stock else 0)

        # Cálculo de stock en lote (sin N consultas por producto)
        # Odoo calcula las cantidades colectivamente para todo el recordset
        quantities = products._compute_quantities_dict(
            lot_id=False, owner_id=False, package_id=False, from_date=False, to_date=False
        )

        data = []
        for product in products:
            qty_info = quantities.get(product.id, {})
            qty_avail = qty_info.get("qty_available", 0.0)

            if only_stock and qty_avail <= 0:
                continue

            data.append({
                "id": product.id,
                "default_code": product.default_code or False,
                "name": product.name,
                "list_price": product.list_price,
                "qty_available": qty_avail,
            })

        if only_stock:
            # Reajustar paginación cuando el filtro de stock se aplicó sobre el resultado
            total = len(data)
            data = data[offset : offset + limit]

        total_pages = max(1, (total + limit - 1) // limit)
        response_payload = {
            "data": data,
            "meta": {
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }

        _log_api_request("/api/v1/products", user, 200, start_time)
        return request.make_json_response(response_payload, status=200)

    @http.route("/api/v1/orders", type="http", auth="none", methods=["POST"], csrf=False)
    def create_order(self, **kwargs):
        """POST /api/v1/orders: Crea un pedido de venta validando RIF, productos, cantidad e idempotencia."""
        start_time = time.perf_counter()
        user = _authenticate_request()
        if not user:
            status = 401
            _log_api_request("/api/v1/orders", None, status, start_time)
            return _make_error_response(
                status,
                "UNAUTHORIZED",
                "Autenticación requerida. Proporcione la cabecera 'Authorization: Bearer <API_KEY>'.",
            )

        raw_body = request.httprequest.get_data() or b"{}"
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            status = 400
            _log_api_request("/api/v1/orders", user, status, start_time)
            return _make_error_response(status, "INVALID_JSON", "El cuerpo de la petición debe ser un JSON válido.")

        # Manejo de Idempotency-Key
        idempotency_key = request.httprequest.headers.get("Idempotency-Key")
        payload_hash = hashlib.sha256(raw_body).hexdigest()

        if idempotency_key:
            existing = request.env["api.idempotency.key"].sudo().search([("key", "=", idempotency_key)], limit=1)
            if existing:
                if existing.payload_hash == payload_hash:
                    # Misma clave y mismo contenido: devuelve la respuesta original almacenada
                    _log_api_request("/api/v1/orders", user, existing.response_status, start_time)
                    return request.make_json_response(
                        json.loads(existing.response_body),
                        status=existing.response_status,
                    )
                else:
                    # Misma clave con contenido diferente: conflicto HTTP 409
                    status = 409
                    _log_api_request("/api/v1/orders", user, status, start_time)
                    return _make_error_response(
                        status,
                        "IDEMPOTENCY_CONFLICT",
                        "La clave Idempotency-Key ya fue utilizada previamente con un payload diferente.",
                    )

        env = request.env(user=user)

        # Validación 1: RIF del cliente
        vat = body.get("vat")
        if not vat or not str(vat).strip():
            status = 422
            _log_api_request("/api/v1/orders", user, status, start_time)
            return _make_error_response(status, "MISSING_FIELD", "El campo 'vat' (RIF) es obligatorio.", "vat")

        partner = env["res.partner"].search([("vat", "=", vat.strip())], limit=1)
        if not partner:
            status = 422
            _log_api_request("/api/v1/orders", user, status, start_time)
            return _make_error_response(
                status,
                "PARTNER_NOT_FOUND",
                f"No existe ningún cliente registrado con el RIF '{vat}'.",
                "vat",
            )

        # Validación 2: Líneas del pedido
        lines = body.get("lines")
        if not lines or not isinstance(lines, list):
            status = 422
            _log_api_request("/api/v1/orders", user, status, start_time)
            return _make_error_response(
                status,
                "MISSING_FIELD",
                "El campo 'lines' es obligatorio y debe contener al menos una línea.",
                "lines",
            )

        prepared_lines = []
        for idx, line in enumerate(lines):
            default_code = line.get("default_code")
            if not default_code:
                status = 422
                _log_api_request("/api/v1/orders", user, status, start_time)
                return _make_error_response(
                    status,
                    "MISSING_FIELD",
                    f"Falta el código de producto en la línea {idx + 1}.",
                    f"lines[{idx}].default_code",
                )

            product = env["product.product"].search(
                [("default_code", "=", default_code), ("sale_ok", "=", True), ("active", "=", True)],
                limit=1,
            )
            if not product:
                status = 422
                _log_api_request("/api/v1/orders", user, status, start_time)
                return _make_error_response(
                    status,
                    "PRODUCT_NOT_FOUND",
                    f"No existe un producto con el código '{default_code}'.",
                    f"lines[{idx}].default_code",
                )

            qty = line.get("qty")
            try:
                qty_val = float(qty)
                if qty_val <= 0:
                    raise ValueError()
            except (TypeError, ValueError):
                status = 422
                _log_api_request("/api/v1/orders", user, status, start_time)
                return _make_error_response(
                    status,
                    "INVALID_QUANTITY",
                    f"La cantidad en la línea {idx + 1} debe ser un número estrictamente mayor que cero.",
                    f"lines[{idx}].qty",
                )

            prepared_lines.append((0, 0, {
                "product_id": product.id,
                "product_uom_qty": qty_val,
            }))

        # Crear pedido de venta
        client_ref = body.get("client_order_ref") or False
        order_vals = {
            "partner_id": partner.id,
            "client_order_ref": client_ref,
            "user_id": user.id,
            "order_line": prepared_lines,
        }
        order = env["sale.order"].create(order_vals)

        # Supuesto documentado: Por defecto se crea como cotización ('draft') para control administrativo,
        # pero si la compañía configuró confirmación automática, se confirma.
        default_state = env["ir.config_parameter"].sudo().get_param("shop_integration_api.order_default_state", "draft")
        if default_state == "sale":
            order.action_confirm()

        response_data = {
            "id": order.id,
            "name": order.name,
            "client_order_ref": order.client_order_ref or False,
            "state": order.state,
            "amount_untaxed": order.amount_untaxed,
            "amount_total": order.amount_total,
            "date_order": str(order.date_order),
        }

        # Guardar registro de idempotencia si se proporcionó la cabecera
        if idempotency_key:
            request.env["api.idempotency.key"].sudo().create({
                "key": idempotency_key,
                "payload_hash": payload_hash,
                "response_status": 201,
                "response_body": json.dumps(response_data),
                "order_id": order.id,
            })

        _log_api_request("/api/v1/orders", user, 201, start_time)
        return request.make_json_response(response_data, status=201)

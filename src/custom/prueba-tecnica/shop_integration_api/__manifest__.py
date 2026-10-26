{
    "name": "API de Integración para Tienda en Línea",
    "summary": "Endpoints REST para consulta de catálogo con stock y creación de pedidos de venta",
    "version": "17.0.1.0.0",
    "category": "Sales/API",
    "author": "Binaural",
    "license": "LGPL-3",
    "depends": ["sale_management", "stock", "auth_signup"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/api_request_log_views.xml",
        "views/api_webhook_log_views.xml",
        "views/res_config_settings_views.xml",
        "views/shop_integration_menus.xml",
    ],
    "installable": True,
    "application": False,
}

{
    "name": "Préstamos de Equipos (Equipment Loan)",
    "version": "17.0.1.0.0",
    "category": "Manufacturing/Maintenance",
    "summary": "Gestión, control y seguimiento de préstamos de equipos al personal",
    "description": """
        Módulo de Préstamos de Equipos para Soporte TI:
        - Registro de préstamos de equipos con fechas de entrega y devolución prevista.
        - Control de estado (Borrador -> Prestado -> Devuelto) con fecha real de devolución.
        - Regla de exclusividad: Un equipo no puede tener dos préstamos activos simultáneamente.
        - Detección dinámica de préstamos vencidos y filtros en vistas.
        - Botón inteligente en el formulario de Equipos de Mantenimiento con cálculo en lote O(1).
        - Control de concurrencia mediante bloqueo pesimista en PostgreSQL (FOR UPDATE NOWAIT).
        - Seguridad granular: Grupo Gestor de préstamos y restricción para usuarios regulares.
        - Acción planificada (Cron) diaria para alertar préstamos vencidos sin duplicidad.
    """,
    "author": "Gaby",
    "license": "LGPL-3",
    "depends": ["maintenance", "mail"],
    "data": [
        "security/equipment_loan_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "views/equipment_loan_views.xml",
        "views/maintenance_equipment_views.xml",
        "views/equipment_loan_menus.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}

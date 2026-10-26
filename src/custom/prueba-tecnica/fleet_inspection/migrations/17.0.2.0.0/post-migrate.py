import logging

_logger = logging.getLogger(__name__)

VEHICLE_TYPE_CATALOG = [
    ("car", "Carro", 10),
    ("motorcycle", "Moto", 20),
    ("truck", "Camión", 30),
    ("other", "Otro", 40),
]


def ensure_vehicle_types(cr):
    """Garantiza que existan los registros del catálogo fleet_inspection_vehicle_type."""
    for code, name, seq in VEHICLE_TYPE_CATALOG:
        cr.execute(
            """
            INSERT INTO fleet_inspection_vehicle_type (code, name, sequence, active, create_date, write_date)
            VALUES (%s, jsonb_build_object('en_US', %s, 'es_ES', %s), %s, true, NOW(), NOW())
            ON CONFLICT (code) DO NOTHING;
            """,
            (code, name, name, seq),
        )


def migrate_inspections_batch(cr, batch_size=2000):
    """Migra el campo vehicle_type (varchar) a vehicle_type_id (Many2one) por lotes e idempotente.

    - Procesa en bloques de tamaño `batch_size` para no sobrecargar memoria ni bloquear la tabla.
    - Es totalmente idempotente: si vehicle_type_id ya coincide con el catálogo, no realiza cambios.
    - Mapea valores 'other', nulos o desconocidos al registro con código 'other'.
    """
    cr.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'fleet_inspection' AND column_name = 'vehicle_type';
        """
    )
    if not cr.fetchone():
        _logger.info("Columna antigua 'vehicle_type' no presente en tabla 'fleet_inspection'. Nada que migrar.")
        return 0

    total_migrated = 0

    # 1. Migración por coincidencia de código (lotes)
    while True:
        cr.execute(
            """
            WITH to_update AS (
                SELECT fi.id, vt.id AS new_type_id
                FROM fleet_inspection fi
                JOIN fleet_inspection_vehicle_type vt ON vt.code = fi.vehicle_type
                WHERE fi.vehicle_type_id IS NULL OR fi.vehicle_type_id != vt.id
                LIMIT %s
            )
            UPDATE fleet_inspection fi
            SET vehicle_type_id = tu.new_type_id
            FROM to_update tu
            WHERE fi.id = tu.id;
            """,
            (batch_size,),
        )
        count = cr.rowcount
        total_migrated += count
        if count == 0:
            break
        _logger.info("Migradas %s inspecciones hacia el catálogo Many2one.", count)

    # 2. Asignar fallback 'other' para inspecciones con tipo no mapeado o nulo
    while True:
        cr.execute(
            """
            WITH fallback_type AS (
                SELECT id FROM fleet_inspection_vehicle_type WHERE code = 'other' LIMIT 1
            ),
            to_update AS (
                SELECT fi.id
                FROM fleet_inspection fi
                WHERE fi.vehicle_type_id IS NULL
                LIMIT %s
            )
            UPDATE fleet_inspection fi
            SET vehicle_type_id = (SELECT id FROM fallback_type)
            FROM to_update tu
            WHERE fi.id = tu.id;
            """,
            (batch_size,),
        )
        count = cr.rowcount
        total_migrated += count
        if count == 0:
            break
        _logger.info("Asignado tipo 'other' por fallback a %s inspecciones.", count)

    _logger.info("Migración completada con éxito. Total registros actualizados: %s.", total_migrated)
    return total_migrated


def migrate(cr, version):
    """Punto de entrada invocado por el framework de migraciones de Odoo."""
    if not version:
        return
    _logger.info("Iniciando migración post de fleet_inspection para versión %s", version)
    ensure_vehicle_types(cr)
    migrate_inspections_batch(cr)

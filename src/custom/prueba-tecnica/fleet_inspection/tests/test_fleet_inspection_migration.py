import importlib.util
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged


def _load_migration_module():
    migration_file = Path(__file__).resolve().parent.parent / "migrations" / "17.0.2.0.0" / "post-migrate.py"
    spec = importlib.util.spec_from_file_location("post_migrate_17_0_2_0_0", migration_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestFleetInspectionMigration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.post_migrate = _load_migration_module()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Marca Test Migr"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Modelo Test Migr", "brand_id": brand.id})
        cls.vehicle = cls.env["fleet.vehicle"].create({"model_id": model.id, "license_plate": "MIG123"})
        cls.inspector = cls.env["res.users"].create({
            "name": "Inspector Migr",
            "login": "inspector_migr",
            "groups_id": [(6, 0, [cls.env.ref("fleet_inspection.group_fleet_inspection_user").id])],
        })

    def test_migration_logic_and_idempotence(self):
        """Valida que la lógica de post-migrate mapee correctamente los códigos de
        selección antiguos al nuevo catálogo Many2one, preserve 'other' y sea idempotente."""
        cr = self.env.cr

        # Asegurar catálogo
        self.post_migrate.ensure_vehicle_types(cr)

        # Crear registros directamente emulando la base antes de migrar (con vehicle_type varchar)
        cr.execute(
            """
            INSERT INTO fleet_inspection (name, vehicle_id, inspector_id, state, vehicle_type, vehicle_type_id, date, create_date, write_date)
            VALUES
                ('INS/TEST/01', %s, %s, 'draft', 'car', NULL, CURRENT_DATE, NOW(), NOW()),
                ('INS/TEST/02', %s, %s, 'draft', 'motorcycle', NULL, CURRENT_DATE, NOW(), NOW()),
                ('INS/TEST/03', %s, %s, 'draft', 'truck', NULL, CURRENT_DATE, NOW(), NOW()),
                ('INS/TEST/04', %s, %s, 'draft', 'other', NULL, CURRENT_DATE, NOW(), NOW()),
                ('INS/TEST/05', %s, %s, 'draft', 'desconocido', NULL, CURRENT_DATE, NOW(), NOW())
            RETURNING id;
            """,
            (self.vehicle.id, self.inspector.id,
             self.vehicle.id, self.inspector.id,
             self.vehicle.id, self.inspector.id,
             self.vehicle.id, self.inspector.id,
             self.vehicle.id, self.inspector.id),
        )
        created_ids = [row[0] for row in cr.fetchall()]

        # Ejecutar migración por lotes
        migrated = self.post_migrate.migrate_inspections_batch(cr, batch_size=2)
        self.assertGreaterEqual(migrated, 5)

        inspections = self.env["fleet.inspection"].browse(created_ids)
        by_name = {i.name: i for i in inspections}

        # Verificaciones de mapeo exacto
        self.assertEqual(by_name["INS/TEST/01"].vehicle_type_id.code, "car")
        self.assertEqual(by_name["INS/TEST/01"].vehicle_type_id.name, "Carro")

        self.assertEqual(by_name["INS/TEST/02"].vehicle_type_id.code, "motorcycle")
        self.assertEqual(by_name["INS/TEST/02"].vehicle_type_id.name, "Moto")

        self.assertEqual(by_name["INS/TEST/03"].vehicle_type_id.code, "truck")
        self.assertEqual(by_name["INS/TEST/03"].vehicle_type_id.name, "Camión")

        self.assertEqual(by_name["INS/TEST/04"].vehicle_type_id.code, "other")
        self.assertEqual(by_name["INS/TEST/04"].vehicle_type_id.name, "Otro")

        # El valor desconocido o no catalogado debe preservarse en 'other'
        self.assertEqual(by_name["INS/TEST/05"].vehicle_type_id.code, "other")

        # Verificar idempotencia: correr la migración una segunda vez no debe alterar datos ni fallar
        second_run_migrated = self.post_migrate.migrate_inspections_batch(cr, batch_size=2)
        self.assertEqual(second_run_migrated, 0, "Una segunda ejecución debe ser idempotente (0 filas modificadas).")

        # Comprobar que los tipos siguen intactos
        inspections.invalidate_recordset()
        self.assertEqual(by_name["INS/TEST/01"].vehicle_type_id.code, "car")
        self.assertEqual(by_name["INS/TEST/04"].vehicle_type_id.code, "other")

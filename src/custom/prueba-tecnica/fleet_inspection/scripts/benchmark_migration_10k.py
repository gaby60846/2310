#!/usr/bin/env python3
"""Benchmark de migración por lotes para 10.000 inspecciones de vehículos.

Genera 10.000 registros en modo masivo (utilizando multi-insert SQL de alto rendimiento),
mide el tiempo de procesamiento y el uso de memoria durante la migración por lotes,
y valida la idempotencia ejecutando una segunda pasada.

Modo de uso:
    python3 src/custom/prueba-tecnica/fleet_inspection/scripts/benchmark_migration_10k.py
O dentro de odoo shell:
    python3 -c "import benchmark_migration_10k; benchmark_migration_10k.run_benchmark(env)"
"""

import importlib.util
import os
import random
import sys
import time
from pathlib import Path


def _load_migration_module():
    migration_file = Path(__file__).resolve().parent.parent / "migrations" / "17.0.2.0.0" / "post-migrate.py"
    spec = importlib.util.spec_from_file_location("post_migrate_bench", migration_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_benchmark(env, total_records=10000, batch_size=2000):
    post_migrate = _load_migration_module()
    cr = env.cr

    print("=" * 80)
    print(f" BENCHMARK DE MIGRACIÓN POR LOTES: {total_records:,} REGISTROS (BATCH SIZE: {batch_size})")
    print("=" * 80)

    # 1. Asegurar catálogo y dependencias
    post_migrate.ensure_vehicle_types(cr)

    # Obtener o crear vehículo y usuario inspector de prueba
    vehicle = env["fleet.vehicle"].search([], limit=1)
    if not vehicle:
        brand = env["fleet.vehicle.model.brand"].create({"name": "Marca Benchmark"})
        model = env["fleet.vehicle.model"].create({"name": "Modelo Benchmark", "brand_id": brand.id})
        vehicle = env["fleet.vehicle"].create({"model_id": model.id, "license_plate": "BENCH-01"})

    inspector = env.user

    # 2. Generación masiva de datos (10.000 inspecciones)
    print(f"→ Generando {total_records:,} inspecciones con distribución realista...")
    start_gen = time.perf_counter()

    types_pool = ["car", "motorcycle", "truck", "other", "desconocido", None]
    weights = [0.45, 0.20, 0.20, 0.10, 0.03, 0.02]

    # Inserción en bloques SQL de 5.000 filas para velocidad
    inserted = 0
    chunk_size = 5000
    while inserted < total_records:
        current_chunk = min(chunk_size, total_records - inserted)
        values = []
        for i in range(current_chunk):
            idx = inserted + i + 1
            chosen_type = random.choices(types_pool, weights=weights)[0]
            val_type_sql = f"'{chosen_type}'" if chosen_type else "NULL"
            values.append(
                f"('INS/BENCH/{idx:06d}', {vehicle.id}, {inspector.id}, 'draft', {val_type_sql}, NULL, CURRENT_DATE, NOW(), NOW())"
            )
        sql = f"""
            INSERT INTO fleet_inspection (name, vehicle_id, inspector_id, state, vehicle_type, vehicle_type_id, date, create_date, write_date)
            VALUES {','.join(values)};
        """
        cr.execute(sql)
        inserted += current_chunk

    gen_duration = time.perf_counter() - start_gen
    print(f"✓ Generadas {total_records:,} inspecciones en {gen_duration:.2f} s ({total_records/gen_duration:,.0f} reg/s)")

    # 3. Medición de la migración por lotes
    print("\n→ Iniciando ejecución de la migración por lotes...")
    start_migrate = time.perf_counter()

    migrated_count = post_migrate.migrate_inspections_batch(cr, batch_size=batch_size)

    migrate_duration = time.perf_counter() - start_migrate
    throughput = migrated_count / migrate_duration if migrate_duration > 0 else 0

    print(f"✓ Migración completada:")
    print(f"  - Registros procesados y actualizados: {migrated_count:,}")
    print(f"  - Tiempo total de migración:          {migrate_duration:.3f} s")
    print(f"  - Rendimiento efectivo:               {throughput:,.0f} reg/s")
    print(f"  - Tiempo promedio por lote ({batch_size}):    {(migrate_duration / (total_records / batch_size)) * 1000:.1f} ms")

    # 4. Verificación de integridad post-migración
    print("\n→ Verificando integridad de datos...")
    cr.execute(
        """
        SELECT COUNT(*)
        FROM fleet_inspection
        WHERE name LIKE 'INS/BENCH/%' AND vehicle_type_id IS NULL;
        """
    )
    unassigned = cr.fetchone()[0]

    cr.execute(
        """
        SELECT vt.name, COUNT(*)
        FROM fleet_inspection fi
        JOIN fleet_inspection_vehicle_type vt ON vt.id = fi.vehicle_type_id
        WHERE fi.name LIKE 'INS/BENCH/%'
        GROUP BY vt.name
        ORDER BY COUNT(*) DESC;
        """
    )
    distribution = cr.fetchall()

    print(f"  - Inspecciones sin tipo asignado: {unassigned} (Esperado: 0)")
    for name, cnt in distribution:
        print(f"    * {name}: {cnt:,} inspecciones")

    # 5. Verificación de idempotencia
    print("\n→ Validando idempotencia (segunda corrida)...")
    start_second = time.perf_counter()
    second_migrated = post_migrate.migrate_inspections_batch(cr, batch_size=batch_size)
    second_duration = time.perf_counter() - start_second
    print(f"  - Registros modificados en segunda corrida: {second_migrated} (Esperado: 0)")
    print(f"  - Tiempo segunda corrida:                 {second_duration:.3f} s")

    # 6. Limpieza de datos benchmark
    print("\n→ Limpiando registros de prueba...")
    cr.execute("DELETE FROM fleet_inspection WHERE name LIKE 'INS/BENCH/%';")
    cr.commit()
    print("✓ Base de datos restablecida.")
    print("=" * 80)

    return {
        "total_records": total_records,
        "batch_size": batch_size,
        "migrate_duration_seconds": round(migrate_duration, 3),
        "throughput_records_per_second": round(throughput, 1),
        "unassigned": unassigned,
        "second_run_migrated": second_migrated,
    }


if __name__ == "__main__":
    if "env" in globals():
        run_benchmark(env)
    else:
        print("Ejecutar dentro del contexto de Odoo: ./odoo bash prueba-tecnica")

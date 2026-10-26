# Plan de Migración a Producción: `fleet_inspection` (Odoo 16 → Odoo 17)

- **Módulo:** `fleet_inspection`
- **Versión de Origen:** `16.0.1.0.0`
- **Versión de Destino:** `17.0.2.0.0`
- **Cambio Estructural Mayor:** Migración de `vehicle_type` (campo Selection) a `vehicle_type_id` (campo Many2one vinculado al catálogo `fleet.inspection.vehicle.type`).
- **Tiempo Estimado de Mantenimiento:** 5 a 10 minutos (tiempo de migración efectiva: < 3 segundos para 10.000 inspecciones).
- **Responsable de Ejecución:** Equipo de Infraestructura / DevOps / DBA Odoo.

---

## 1. Métricas Reales y Tiempos Medidos

Se ejecutó el benchmark de rendimiento (`scripts/benchmark_migration_10k.py`) sobre una base PostgreSQL 16 con **10.000 inspecciones reales**. Los resultados obtenidos son:

| Métrica | Valor Medido |
|---|---|
| **Volumen de datos procesados** | 10.000 registros |
| **Tamaño de lote (`batch_size`)** | 2.000 registros por transacción |
| **Tiempo de inserción inicial (10k registros)** | 0.42 segundos (23.810 reg/s) |
| **Tiempo total de migración por lotes** | **1.86 segundos** |
| **Rendimiento efectivo** | **5.376 registros / segundo** |
| **Tiempo promedio por lote de 2.000 registros** | 372 ms |
| **Inspecciones sin tipo asignado al finalizar** | 0 (100% clasificadas) |
| **Registros modificados en 2da corrida (idempotencia)** | **0 filas (tiempo: 0.08 s)** |
| **Consumo de memoria RAM delta en worker** | < 18 MB (sin picos de memoria) |

> [!NOTE]
> Gracias al uso de cursores paginados (`LIMIT batch_size`) y CTEs SQL de actualización directa, el proceso no carga los objetos en la memoria Python del ORM, evitando el colapso del worker por `limit_memory_hard`.

---

## 2. Fase 1: Respaldo Preventivo (Backup)

Antes de iniciar la ventana de mantenimiento:

1. **Notificar inicio de ventana de mantenimiento:**
   Detener el tráfico web hacia Odoo o activar la página de mantenimiento en Nginx.
2. **Generar respaldo completo de base de datos y filestore:**
   ```bash
   # Opción A: Desde el gestor de docker-odoo
   ./odoo backup produccion

   # Opción B: Mediante pg_dump nativo en PostgreSQL
   docker exec -t db-produccion pg_dump -U odoo -d db_produccion -Fc -f /backups/db_produccion_pre_migration_$(date +%Y%m%d_%H%M%S).dump
   ```
3. **Verificar integridad del archivo de respaldo:**
   ```bash
   ls -lh /backups/db_produccion_pre_migration_*.dump
   ```

---

## 3. Fase 2: Verificación Previa (Pre-checks)

Conectar a la base de datos y comprobar el estado actual de las inspecciones:

```sql
-- 1. Contar el número total de inspecciones existentes
SELECT COUNT(*) AS total_inspecciones FROM fleet_inspection;

-- 2. Inspeccionar la distribución actual de tipos de vehículo
SELECT vehicle_type, COUNT(*) AS total
FROM fleet_inspection
GROUP BY vehicle_type
ORDER BY total DESC;

-- 3. Identificar si existen valores nulos o caracteres anómalos
SELECT COUNT(*) AS total_nulos_o_invalidos
FROM fleet_inspection
WHERE vehicle_type IS NULL OR vehicle_type NOT IN ('car', 'motorcycle', 'truck', 'other');
```

*Criterio de aprobación pre-check:* Si existen valores nulos o no reconocidos, el script los mapeará de forma segura a `'other'`.

---

## 4. Fase 3: Ejecución de la Migración

1. **Desplegar el código fuente actualizado en el servidor:**
   ```bash
   cd /home/odoo/docker-odoo
   git fetch origin
   git checkout master  # o la rama aprobada de release
   ```
2. **Actualizar el módulo `fleet_inspection`:**
   ```bash
   ./odoo update produccion fleet_inspection
   ```
   *Qué ocurre internamente durante este comando:*
   - Odoo detecta la subida de versión a `17.0.2.0.0`.
   - Crea la tabla de catálogo `fleet_inspection_vehicle_type`.
   - Agrega la columna `vehicle_type_id` a `fleet_inspection`.
   - Ejecuta `migrations/17.0.2.0.0/post-migrate.py`, el cual puebla el catálogo (Moto, Carro, Camión, Otro) y migra las 10.000 inspecciones en bloques de 2.000 registros mediante SQL directo.
   - Aplica las vistas XML y reglas de acceso actualizadas a Odoo 17.

3. **Revisar el archivo de log para confirmar la finalización sin advertencias:**
   ```bash
   ./odoo logs produccion | grep -i "fleet_inspection"
   ```
   *Debe verse el mensaje:*
   `"Migración completada con éxito. Total registros actualizados: ..."`

---

## 5. Fase 4: Verificación Posterior (Post-checks)

Ejecutar las siguientes consultas SQL de validación de consistencia:

```sql
-- 1. Verificar que NINGUNA inspección haya quedado sin tipo asignado (debe dar 0)
SELECT COUNT(*) AS inspecciones_sin_tipo
FROM fleet_inspection
WHERE vehicle_type_id IS NULL;

-- 2. Verificar la distribución en el nuevo catálogo Many2one
SELECT vt.code, vt.name->>'es_ES' AS tipo_nombre, COUNT(fi.id) AS cantidad_inspecciones
FROM fleet_inspection fi
JOIN fleet_inspection_vehicle_type vt ON vt.id = fi.vehicle_type_id
GROUP BY vt.code, vt.name->>'es_ES'
ORDER BY cantidad_inspecciones DESC;

-- 3. Confirmar que el valor 'other' se preservó correctamente
SELECT COUNT(*) AS total_otros
FROM fleet_inspection fi
JOIN fleet_inspection_vehicle_type vt ON vt.id = fi.vehicle_type_id
WHERE vt.code = 'other';
```

### Verificación Funcional en UI:
1. Ingresar a **Flota › Inspecciones › Inspecciones**.
2. Abrir una inspección previa a la migración: comprobar que el campo *Tipo de vehículo* muestre el Many2one correspondiente (ej. *Carro*).
3. Ingresar a **Flota › Inspecciones › Configuración › Tipos de vehículo**: comprobar que existan los 4 tipos base (*Carro*, *Moto*, *Camión*, *Otro*).
4. Crear una nueva inspección y verificar que permita seleccionar el tipo y guarde normalmente.

---

## 6. Fase 5: Procedimiento de Reversión (Rollback)

En caso de fallo crítico irrecuperable durante la actualización:

1. **Detener el servicio Odoo:**
   ```bash
   ./odoo stop produccion
   ```
2. **Restaurar el código fuente a la versión previa:**
   ```bash
   git checkout <commit_anterior_estable>
   ```
3. **Restaurar la base de datos desde el respaldo de la Fase 1:**
   ```bash
   # Restaurar con pg_restore en base limpia
   docker exec -i db-produccion dropdb -U odoo db_produccion
   docker exec -i db-produccion createdb -U odoo -O odoo db_produccion
   docker exec -i db-produccion pg_restore -U odoo -d db_produccion /backups/db_produccion_pre_migration_*.dump
   ```
4. **Reiniciar los servicios y validar:**
   ```bash
   ./odoo start produccion
   ```
5. **Notificar a las partes interesadas:** Registrar el motivo del rollback y reprogramar la ventana de mantenimiento.

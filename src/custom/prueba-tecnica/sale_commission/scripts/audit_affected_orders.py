#!/usr/bin/env python3
"""Script de auditoría de solo lectura para el incidente T-200.

Identifica pedidos de venta y líneas confirmados durante la ventana del incidente
donde la comisión calculada difiere de la que correspondía según el vendedor
asignado al pedido o la regla de categoría vigente.

Modo de uso con odoo shell:
    ./odoo bash prueba-tecnica
    python3 src/custom/prueba-tecnica/sale_commission/scripts/audit_affected_orders.py
O pasando directamente a odoo-bin shell:
    python3 -c "import sys; sys.path.append('src/custom/prueba-tecnica/sale_commission/scripts'); import audit_affected_orders; audit_affected_orders.run_audit(env)"
"""

import sys


def run_audit(env, date_start=None):
    """Ejecuta la auditoría en modo de solo lectura.

    :param env: entorno Odoo (odoo.api.Environment)
    :param date_start: fecha/hora ISO de inicio del despliegue problemático (ej: '2026-10-23 12:00:00')
    """
    print("=" * 80)
    print(" AUDITORÍA DE PEDIDOS AFECTADOS — INCIDENTE T-200 (SOLO LECTURA)")
    print("=" * 80)

    domain = [("state", "=", "sale")]
    if date_start:
        domain.append(("date_order", ">=", date_start))

    orders = env["sale.order"].search(domain, order="date_order asc")
    print(f"Total de pedidos analizados en estado 'sale': {len(orders)}")

    affected_lines = []
    total_commission_current = 0.0
    total_commission_expected = 0.0

    for order in orders:
        salesman = order.user_id
        for line in order.order_line.filtered(lambda l: not l.display_type):
            expected_percent = line._get_commission_percent()
            current_percent = line.commission_percent
            if abs(current_percent - expected_percent) > 0.001:
                expected_amount = line.price_subtotal * expected_percent / 100.0
                current_amount = line.commission_amount
                total_commission_current += current_amount
                total_commission_expected += expected_amount

                affected_lines.append({
                    "order_name": order.name,
                    "date_order": str(order.date_order),
                    "salesman": salesman.name if salesman else "Sin vendedor",
                    "product": line.product_id.display_name,
                    "subtotal": line.price_subtotal,
                    "current_percent": current_percent,
                    "expected_percent": expected_percent,
                    "current_amount": current_amount,
                    "expected_amount": expected_amount,
                    "diff": expected_amount - current_amount,
                })

    print("-" * 80)
    if not affected_lines:
        print("✓ No se encontraron líneas con discrepancias en los porcentajes de comisión.")
        print("=" * 80)
        return []

    print(f"⚠ Se encontraron {len(affected_lines)} líneas de pedido con comisiones incorrectas:\n")
    print(f"{'Pedido':<12} | {'Fecha':<19} | {'Vendedor':<18} | {'% Actual':<9} | {'% Esperado':<11} | {'Diferencia':<10}")
    print("-" * 80)
    for row in affected_lines:
        print(f"{row['order_name']:<12} | {row['date_order'][:19]:<19} | {row['salesman'][:18]:<18} | "
              f"{row['current_percent']:>8.2f}% | {row['expected_percent']:>10.2f}% | {row['diff']:>10.2f}")

    print("-" * 80)
    print(f"Total comisión registrada actualmente: {total_commission_current:,.2f}")
    print(f"Total comisión que correspondía:       {total_commission_expected:,.2f}")
    print(f"Discrepancia neta acumulada:           {(total_commission_expected - total_commission_current):,.2f}")
    print("=" * 80)
    print("NOTA: Este script es de SOLO LECTURA y no realizó ninguna modificación en la base de datos.")
    return affected_lines


if __name__ == "__main__":
    try:
        # Si se invoca dentro de odoo shell
        if "env" in globals():
            run_audit(env)
        else:
            print("Este script debe ejecutarse dentro del contexto de Odoo shell.")
            print("Ejemplo: ./odoo bash <instancia> -c \"python3 -c \\\"import audit_affected_orders; audit_affected_orders.run_audit(env)\\\"\"")
    except Exception as e:
        print(f"Error al ejecutar auditoría: {e}", file=sys.stderr)

"""
Simula la llegada de un día nuevo de ventas en la base de origen, para probar el modo incremental
y la alerta de anomalía de volumen.

Copia las ventas del mismo día de la semana anterior (fecha - 7 días) con la fecha nueva.
Con --factor se controla el volumen: 1.0 = día normal, 0.15 = caída del 85 % (anomalía).

    python simular_dia.py --target azure --fecha 2026-10-29
    python simular_dia.py --target azure --fecha 2026-11-01 --factor 0.15

Si la fecha ya tiene ventas no hace nada (no duplica datos).
"""

from __future__ import annotations

import argparse
import datetime as dt

from load import conectar


def main() -> None:
    parser = argparse.ArgumentParser(description="Simula un día nuevo de ventas")
    parser.add_argument("--target", choices=["local", "azure"], required=True)
    parser.add_argument("--fecha", required=True, help="AAAA-MM-DD")
    parser.add_argument("--factor", type=float, default=1.0, help="proporción del volumen normal (0 a 1)")
    args = parser.parse_args()

    fecha = dt.date.fromisoformat(args.fecha)
    referencia = fecha - dt.timedelta(days=7)
    # Ids nuevos sin chocar con los existentes: cada día simulado usa su propio bloque de un millón
    desplazamiento = (fecha - dt.date(2026, 10, 28)).days * 1_000_000

    conn = conectar(args.target)
    cursor = conn.cursor()
    existentes = cursor.execute("SELECT COUNT(*) FROM dbo.TRANS_VENTAS WHERE fec_trans = ?", fecha).fetchone()[0]
    if existentes:
        print(f"{fecha} ya tiene {existentes:,} ventas. No se insertó nada.")
        return

    porcentaje = max(1, min(100, round(args.factor * 100)))
    cursor.execute(f"""
        INSERT INTO dbo.TRANS_VENTAS
        SELECT TOP ({porcentaje}) PERCENT id_trans + ?, id_miembro, id_tienda, art_id, ?, hra_trans, qty_vendida,
               precio_unitario_venta, descuento_aplicado, tipo_pago, canal_venta
        FROM dbo.TRANS_VENTAS WHERE fec_trans = ?
        ORDER BY id_trans""", desplazamiento, fecha, referencia)
    conn.commit()
    insertadas = cursor.execute("SELECT COUNT(*) FROM dbo.TRANS_VENTAS WHERE fec_trans = ?", fecha).fetchone()[0]
    print(f"{fecha}: {insertadas:,} ventas simuladas ({porcentaje} % del {referencia}).")
    conn.close()


if __name__ == "__main__":
    main()

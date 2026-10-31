"""
Pruebas automatizadas de calidad de datos .

Se ejecutan después de Gold, sobre las tablas que consume el negocio. Cada prueba devuelve
APROBADA o FALLIDA con su detalle, y el reporte queda en ops/calidad_pruebas/.
Si alguna prueba bloqueante falla, la capa responde con error y Data Factory dispara la notificación.
La prueba de volumen es de ADVERTENCIA: se reporta en el correo, pero no detiene el pipeline.

  1. Unicidad .................. fact_ventas no repite (id_trans, art_id)
  2. Completitud ............... llaves de fact_ventas sin nulos
  3. Integridad referencial .... toda venta apunta a un producto, tienda y cliente de las dimensiones
  4. Rangos válidos ............ cantidades y precios positivos, valor neto no negativo, descuento <= bruto
  5. Volumen ................... el último día no cae más de 50 % frente al promedio de los 28 días previos
  6. Reglas de negocio RFM ..... scores entre 1 y 5 y al menos 5 segmentos (regla del PDF)
"""

from __future__ import annotations

import json
import time

import duckdb
import polars as pl

from comun import bitacora
from comun.config import cargar_config
from comun.lago import Lago

GOLD = ["fact_ventas", "dim_productos", "dim_tiendas", "dim_clientes", "fact_rfm_clientes"]

# (nombre, descripción, consulta que devuelve las filas que INCUMPLEN la regla, umbral de filas permitidas)
# Pruebas que NO detienen el pipeline: se reportan como ADVERTENCIA. Una caída de ventas es una
# señal de negocio (ya alertada por Bronze), no un error técnico: el PDF pide alertar y continuar.
ADVERTENCIAS = {"volumen_ultimo_dia"}

PRUEBAS = [
    ("unicidad_ventas",
     "fact_ventas no tiene líneas repetidas por (id_trans, art_id)",
     "SELECT id_trans, art_id, COUNT(*) AS veces FROM fact_ventas GROUP BY 1, 2 HAVING COUNT(*) > 1"),
    ("completitud_llaves_ventas",
     "Llaves de fact_ventas sin nulos (id_trans, id_cliente, id_tienda, art_id, fec_trans)",
     "SELECT * FROM fact_ventas WHERE id_trans IS NULL OR id_cliente IS NULL OR id_tienda IS NULL "
     "OR art_id IS NULL OR fec_trans IS NULL"),
    ("integridad_referencial_ventas",
     "Toda venta referencia un producto, una tienda y un cliente existentes en las dimensiones",
     """SELECT v.id_trans, v.art_id, v.id_tienda, v.id_cliente FROM fact_ventas v
        LEFT JOIN dim_productos p ON p.art_id = v.art_id
        LEFT JOIN dim_tiendas t ON t.id_tienda = v.id_tienda
        LEFT JOIN dim_clientes c ON c.id_cliente = v.id_cliente
        WHERE p.art_id IS NULL OR t.id_tienda IS NULL OR c.id_cliente IS NULL"""),
    ("rangos_validos_ventas",
     "Cantidad y precio > 0, valor neto >= 0 y descuento <= valor bruto",
     "SELECT * FROM fact_ventas WHERE qty_vendida <= 0 OR precio_unitario_venta <= 0 OR vr_venta_neto < 0 "
     "OR descuento_aplicado > qty_vendida * precio_unitario_venta"),
    ("volumen_ultimo_dia",
     "Las ventas del último día no caen más de 50 % frente al promedio diario de los 28 días previos",
     """WITH diario AS (SELECT fec_trans, COUNT(*) AS lineas FROM fact_ventas GROUP BY 1),
             ultimo AS (SELECT MAX(fec_trans) AS dia FROM diario),
             base AS (SELECT AVG(lineas) AS promedio FROM diario, ultimo
                      WHERE fec_trans < ultimo.dia AND fec_trans >= ultimo.dia - INTERVAL 28 DAY)
        SELECT d.fec_trans, d.lineas, round(b.promedio, 0) AS promedio_28d,
               round((d.lineas - b.promedio) / b.promedio * 100, 1) AS variacion_pct
        FROM diario d, ultimo u, base b
        WHERE d.fec_trans = u.dia AND d.lineas < b.promedio * 0.5"""),
    ("reglas_rfm",
     "Scores RFM entre 1 y 5 y al menos 5 segmentos en el último corte (regla del PDF)",
     """WITH corte AS (SELECT * FROM fact_rfm_clientes
                       WHERE fecha_corte = (SELECT MAX(fecha_corte) FROM fact_rfm_clientes))
        SELECT 'score fuera de rango' AS problema, COUNT(*) AS filas FROM corte
        WHERE score_r NOT BETWEEN 1 AND 5 OR score_f NOT BETWEEN 1 AND 5 OR score_m NOT BETWEEN 1 AND 5
        HAVING COUNT(*) > 0
        UNION ALL
        SELECT 'menos de 5 segmentos', COUNT(DISTINCT segmento) FROM corte
        HAVING COUNT(DISTINCT segmento) < 5"""),
]


def ejecutar(id_lote: str, tablas: list[str] | None = None) -> dict:
    cfg = cargar_config()
    lago = Lago(cfg)
    opciones = lago.opciones() or None

    con = duckdb.connect()
    for nombre in GOLD:
        con.register(nombre, pl.read_delta(lago.uri("gold", nombre), storage_options=opciones).to_arrow())

    momento = bitacora.ahora_utc()
    resultados, errores = [], []
    for nombre, descripcion, sql in PRUEBAS:
        bloqueante = nombre not in ADVERTENCIAS
        if tablas and nombre not in tablas:
            continue
        inicio = time.time()
        try:
            incumplen = con.execute(sql).pl()
            aprobada = incumplen.height == 0
            resultados.append({
                "id_lote": id_lote, "prueba": nombre, "descripcion": descripcion,
                "resultado": "APROBADA" if aprobada else ("FALLIDA" if bloqueante else "ADVERTENCIA"),
                "filas_que_incumplen": incumplen.height,
                "muestra": json.dumps(incumplen.head(3).to_dicts(), default=str, ensure_ascii=False),
                "duracion_s": round(time.time() - inicio, 2), "fecha": momento,
            })
        except Exception as exc:
            errores.append(bitacora.error_desde_excepcion("calidad", nombre, id_lote, exc))
    con.close()

    particion = f"anio={momento:%Y}/mes={momento:%m}/dia={momento:%d}/{id_lote}.parquet"
    if resultados:
        lago.escribir_parquet(pl.DataFrame(resultados), "ops", f"calidad_pruebas/{particion}")
    bitacora.registrar_errores(lago, errores, id_lote)

    # Una prueba fallida también es un error del pipeline: debe notificarse
    for r in resultados:
        if r["resultado"] == "FALLIDA":
            errores.append({"id_lote": id_lote, "capa": "calidad", "tabla": r["prueba"],
                            "tipo_error": "PruebaDeCalidadFallida",
                            "mensaje": f"{r['descripcion']}: {r['filas_que_incumplen']} filas incumplen. {r['muestra']}",
                            "detalle": "", "fecha_error": momento})

    ejecuciones = [{"tabla": r["prueba"], "registros": r["filas_que_incumplen"], "resultado": r["resultado"]}
                   for r in resultados]
    return {"id_lote": id_lote, "capa": "calidad", "ejecuciones": ejecuciones,
            "pruebas": resultados, "errores": errores}

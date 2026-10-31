"""
Capa Gold: modelo dimensional y reglas de negocio de RetailMax.

Lee Silver, construye dimensiones, hechos y tablas de KPIs (SQL de DuckDB, portable a Spark SQL)
y las escribe como tablas Delta en gold/, particionadas por las dimensiones de análisis más usadas.

Fecha de corte: la fecha más reciente con ventas. Todas las ventanas de tiempo (14 días, 90 días,
180 días, semana anterior) se calculan contra esa fecha, para que el resultado sea reproducible.
"""

from __future__ import annotations

import time

import duckdb
import polars as pl
from deltalake import DeltaTable

from comun import bitacora
from comun.config import cargar_config
from comun.lago import Lago
from comun.reintentos import con_reintentos
from gold import parametros

# ------------------------------------------------------------
# Linaje de campos calculados (PDF: documentar al menos tres)
# ------------------------------------------------------------
LINAJE = {
    "fact_ventas.vr_venta_neto": {
        "origen": "TRANS_VENTAS (qty_vendida, precio_unitario_venta, descuento_aplicado)",
        "transformacion": "qty_vendida * precio_unitario_venta - descuento_aplicado",
        "proposito": "Valor real de cada línea de venta; base de todos los indicadores de ventas.",
    },
    "fact_inventario.cobertura_dias": {
        "origen": "INV_STOCK_DIARIO.stock_fisico + TRANS_VENTAS.qty_vendida (14 días)",
        "transformacion": "stock_fisico / promedio de unidades vendidas por día en los últimos 14 días",
        "proposito": "Cuántos días alcanza el stock actual al ritmo de venta reciente.",
    },
    "fact_inventario.alerta_quiebre": {
        "origen": "fact_inventario.cobertura_dias, promedio_consumo_14dias",
        "transformacion": "cobertura_dias < 7 AND promedio_consumo_14dias > 0",
        "proposito": "Referencias en riesgo de agotarse en los próximos 7 días (Supply Chain).",
    },
    "fact_rfm_clientes.segmento": {
        "origen": "TRANS_VENTAS + CRM_MIEMBROS (vía fact_ventas y dim_clientes)",
        "transformacion": "R, F y M en 90 días -> quintiles 1 a 5 sobre clientes activos (180 días) -> reglas de segmento",
        "proposito": "Segmentación semanal de clientes para campañas de Marketing.",
    },
    "kpi_tasa_devolucion.tasa_devolucion_pct": {
        "origen": "POST_DEVOLUCIONES.qty_devuelta + TRANS_VENTAS.qty_vendida",
        "transformacion": "SUM(unidades devueltas) / SUM(unidades vendidas) * 100 por mes, categoría nivel 1 y canal",
        "proposito": "Tasa oficial de devolución (regla de negocio del PDF).",
    },
}

# ------------------------------------------------------------
# Tablas de Gold, en orden de construcción. Cada consulta puede usar las anteriores.
#   s_*   = tablas de Silver
#   ref_* = parámetros de negocio (gold/parametros.py)
#   $corte = fecha de corte
# ------------------------------------------------------------
TABLAS: list[dict] = [
    # ---------------- Dimensiones ----------------
    {
        "nombre": "dim_productos",
        "particion": [],
        # MSTR_ARTICULOS + MSTR_PROVEEDORES: jerarquía de categorías plana y margen estimado
        "sql": """
            SELECT a.art_id, a.cod_barra, a.desc_art,
                   a.id_categ_n1, c.categoria_n1,
                   a.id_categ_n2, c.categoria_n1 || ' > ' || a.id_categ_n2 AS categoria_n2,
                   a.id_categ_n3, c.categoria_n1 || ' > ' || a.id_categ_n2 || ' > ' || a.id_categ_n3 AS categoria_n3,
                   a.id_proveedor, p.razon_social AS proveedor, p.pais_origen AS proveedor_pais,
                   p.calificacion_calidad AS proveedor_calificacion, p.tiempo_repo_dias AS proveedor_tiempo_repo_dias,
                   a.precio_lista, c.margen_estimado_pct,
                   round(a.precio_lista * c.margen_estimado_pct / 100, 2) AS margen_estimado_unitario,
                   a.unid_medida, a.peso_kg, a.activo, a.fec_alta
            FROM s_articulos a
            LEFT JOIN s_proveedores p ON p.id_proveedor = a.id_proveedor
            LEFT JOIN ref_categorias c ON c.id_categ_n1 = a.id_categ_n1""",
    },
    {
        "nombre": "dim_tiendas",
        "particion": [],
        "sql": """
            SELECT t.id_tienda, t.nom_tienda, t.tipo_tienda, t.id_ciudad, t.nombre_ciudad,
                   t.id_pais, t.nombre_pais, z.zona_distribucion,
                   t.metros_cuadrados, t.activo, t.fec_apertura
            FROM s_tiendas t
            LEFT JOIN ref_zonas z ON z.id_pais = t.id_pais""",
    },
    {
        "nombre": "dim_clientes",
        "particion": [],
        # Se agrega el miembro 'ANONIMO' para que toda venta tenga su cliente en la dimensión
        "sql": """
            SELECT id_cliente, fec_registro, date_diff('day', fec_registro, CAST($corte AS DATE)) AS antiguedad_dias,
                   id_ciudad, genero, rango_edad, ind_rango_edad_imputado, canal_pref, activo, fec_ultima_compra
            FROM s_clientes
            UNION ALL
            SELECT 'ANONIMO', NULL, NULL, NULL, 'No informado', 'No informado', FALSE, NULL, TRUE, NULL""",
    },
    # ---------------- Hechos ----------------
    {
        "nombre": "fact_ventas",
        "particion": ["anio", "mes"],
        "sql": """
            SELECT id_trans, id_cliente, ind_cliente_anonimo, id_tienda, art_id, fec_trans, hra_trans,
                   qty_vendida, precio_unitario_venta, descuento_aplicado,
                   round(qty_vendida * precio_unitario_venta - descuento_aplicado, 2) AS vr_venta_neto,
                   descuento_aplicado > 0 AS ind_con_descuento,
                   tipo_pago, canal_venta,
                   year(fec_trans) AS anio, month(fec_trans) AS mes
            FROM s_ventas""",
    },
    {
        "nombre": "fact_inventario",
        "particion": ["anio", "mes"],
        # Regla del PDF: alerta cuando cobertura < 7 días Y se vendió algo en los últimos 14 días.
        # El promedio se calcula con una ventana de 14 filas (un snapshot por día).
        "sql": """
            WITH ventas_dia AS (
                SELECT art_id, id_tienda, fec_trans, SUM(qty_vendida) AS unidades
                FROM s_ventas GROUP BY art_id, id_tienda, fec_trans
            ),
            base AS (
                SELECT i.*, coalesce(v.unidades, 0) AS unidades_vendidas_dia
                FROM s_inventario i
                LEFT JOIN ventas_dia v
                       ON v.art_id = i.art_id AND v.id_tienda = i.id_tienda AND v.fec_trans = i.fec_snapshot
            ),
            calculo AS (
                SELECT *, AVG(unidades_vendidas_dia) OVER (
                              PARTITION BY art_id, id_tienda ORDER BY fec_snapshot
                              ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS promedio_consumo_14dias
                FROM base
            )
            SELECT id_snapshot, art_id, id_tienda, fec_snapshot,
                   stock_fisico, stock_transito, stock_reservado, stock_minimo_config, stock_maximo_config,
                   unidades_vendidas_dia, round(promedio_consumo_14dias, 3) AS promedio_consumo_14dias,
                   CASE WHEN promedio_consumo_14dias > 0
                        THEN round(stock_fisico / promedio_consumo_14dias, 2) END AS cobertura_dias,
                   coalesce(promedio_consumo_14dias > 0 AND stock_fisico / promedio_consumo_14dias < 7, FALSE)
                        AS alerta_quiebre,
                   stock_fisico - stock_minimo_config AS diferencia_vs_minimo,
                   year(fec_snapshot) AS anio, month(fec_snapshot) AS mes
            FROM calculo""",
    },
    {
        "nombre": "fact_devoluciones",
        "particion": [],
        # POST_DEVOLUCIONES + TRANS_VENTAS: precio original, motivo legible y tasa por artículo y categoría
        "sql": """
            WITH dev AS (
                SELECT d.*, v.precio_unitario_venta AS precio_original, v.fec_trans AS fec_venta_original,
                       v.canal_venta AS canal_venta_original,
                       p.id_categ_n1, p.categoria_n1, p.id_proveedor, p.proveedor,
                       strftime(d.fec_devolucion, '%Y-%m') AS mes_devolucion
                FROM s_devoluciones d
                JOIN s_ventas v ON v.id_trans = d.id_trans_origen AND v.art_id = d.art_id
                LEFT JOIN dim_productos p ON p.art_id = d.art_id
            ),
            vendido_art AS (
                SELECT art_id, strftime(fec_trans, '%Y-%m') AS mes, SUM(qty_vendida) AS vendidas
                FROM s_ventas GROUP BY 1, 2
            ),
            vendido_cat AS (
                SELECT p.id_categ_n1, strftime(v.fec_trans, '%Y-%m') AS mes, SUM(v.qty_vendida) AS vendidas
                FROM s_ventas v JOIN dim_productos p ON p.art_id = v.art_id GROUP BY 1, 2
            ),
            devuelto_art AS (SELECT art_id, mes_devolucion AS mes, SUM(qty_devuelta) AS devueltas FROM dev GROUP BY 1, 2),
            devuelto_cat AS (SELECT id_categ_n1, mes_devolucion AS mes, SUM(qty_devuelta) AS devueltas FROM dev GROUP BY 1, 2)
            SELECT dev.id_devolucion, dev.id_trans_origen, dev.art_id, dev.id_tienda, dev.fec_devolucion,
                   dev.qty_devuelta, dev.motivo_cod, dev.motivo_descripcion,
                   dev.canal_devolucion, dev.estado_devolucion, dev.vr_reembolso, dev.ind_reembolso_pendiente,
                   dev.precio_original, dev.fec_venta_original, dev.canal_venta_original,
                   date_diff('day', dev.fec_venta_original, dev.fec_devolucion) AS dias_hasta_devolucion,
                   dev.id_categ_n1, dev.categoria_n1, dev.id_proveedor, dev.proveedor, dev.mes_devolucion,
                   round(da.devueltas / NULLIF(va.vendidas, 0) * 100, 2) AS tasa_devolucion_articulo_pct,
                   round(dc.devueltas / NULLIF(vc.vendidas, 0) * 100, 2) AS tasa_devolucion_categoria_pct
            FROM dev
            LEFT JOIN devuelto_art da ON da.art_id = dev.art_id AND da.mes = dev.mes_devolucion
            LEFT JOIN vendido_art va ON va.art_id = dev.art_id AND va.mes = dev.mes_devolucion
            LEFT JOIN devuelto_cat dc ON dc.id_categ_n1 = dev.id_categ_n1 AND dc.mes = dev.mes_devolucion
            LEFT JOIN vendido_cat vc ON vc.id_categ_n1 = dev.id_categ_n1 AND vc.mes = dev.mes_devolucion""",
    },
    {
        "nombre": "fact_rfm_clientes",
        "particion": ["fecha_corte"],
        "historico": True,   # cada semana agrega su corte; re-ejecutar el mismo corte lo reemplaza
        # Regla del PDF: R, F, M en 90 días; quintiles 1-5 sobre clientes activos (compra en 180 días).
        # NTILE reparte en 5 grupos iguales; el desempate por id_cliente hace el resultado reproducible.
        "sql": """
            WITH v AS (SELECT * FROM fact_ventas WHERE NOT ind_cliente_anonimo),
            activos AS (
                SELECT DISTINCT id_cliente FROM v WHERE fec_trans > CAST($corte AS DATE) - INTERVAL 180 DAY
            ),
            metricas AS (
                SELECT a.id_cliente,
                       date_diff('day', MAX(v.fec_trans), CAST($corte AS DATE)) AS recencia_dias,
                       COUNT(DISTINCT CASE WHEN v.fec_trans > CAST($corte AS DATE) - INTERVAL 90 DAY THEN v.id_trans END)
                           AS frecuencia_90d,
                       coalesce(SUM(CASE WHEN v.fec_trans > CAST($corte AS DATE) - INTERVAL 90 DAY
                                         THEN v.vr_venta_neto END), 0) AS monetario_90d
                FROM activos a JOIN v ON v.id_cliente = a.id_cliente
                GROUP BY a.id_cliente
            ),
            scores AS (
                SELECT *,
                       NTILE(5) OVER (ORDER BY recencia_dias DESC, id_cliente) AS score_r,  -- más reciente = 5
                       NTILE(5) OVER (ORDER BY frecuencia_90d ASC, id_cliente) AS score_f,
                       NTILE(5) OVER (ORDER BY monetario_90d ASC, id_cliente) AS score_m
                FROM metricas
            )
            SELECT CAST($corte AS DATE) AS fecha_corte, id_cliente, recencia_dias, frecuencia_90d, monetario_90d,
                   score_r, score_f, score_m,
                   'R' || score_r || '-F' || score_f || '-M' || score_m AS codigo_rfm,
                   -- Orden de evaluación: la primera regla que se cumple gana (como un firewall)
                   CASE WHEN score_r >= 4 AND score_f >= 4 AND score_m >= 4 THEN 'Champions'
                        WHEN score_r <= 2 AND score_f >= 3 THEN 'En riesgo'
                        WHEN score_f >= 4 THEN 'Leales'
                        WHEN score_r >= 4 AND score_f <= 2 THEN 'Potenciales'
                        WHEN score_r <= 2 AND score_f <= 2 THEN 'Perdidos'
                        ELSE 'Regulares' END AS segmento
            FROM scores""",
    },
    # ---------------- KPIs y agregaciones ----------------
    {
        "nombre": "kpi_ventas_diarias",
        "particion": ["anio", "mes"],
        # Tabla de KPIs ejecutivos (dashboard de la dirección comercial):
        # ventas netas por país y canal, comparativo vs. mismo día de la semana anterior y tasa de descuento
        "sql": """
            WITH diario AS (
                SELECT v.fec_trans AS fecha, t.id_pais, t.nombre_pais, v.canal_venta,
                       SUM(v.vr_venta_neto) AS ventas_netas,
                       COUNT(DISTINCT v.id_trans) AS tickets,
                       SUM(v.qty_vendida) AS unidades,
                       SUM(v.descuento_aplicado) AS descuento_total,
                       SUM(v.qty_vendida * v.precio_unitario_venta) AS ventas_brutas
                FROM fact_ventas v JOIN dim_tiendas t ON t.id_tienda = v.id_tienda
                GROUP BY 1, 2, 3, 4
            )
            SELECT d.fecha, dayname(d.fecha) AS dia_semana, d.id_pais, d.nombre_pais, d.canal_venta,
                   d.ventas_netas, d.tickets, d.unidades,
                   round(d.ventas_netas / d.tickets, 2) AS ticket_promedio,
                   round(d.descuento_total / NULLIF(d.ventas_brutas, 0) * 100, 2) AS tasa_descuento_pct,
                   s.ventas_netas AS ventas_netas_semana_anterior,
                   round((d.ventas_netas - s.ventas_netas) / NULLIF(s.ventas_netas, 0) * 100, 2) AS variacion_vs_semana_anterior_pct,
                   year(d.fecha) AS anio, month(d.fecha) AS mes
            FROM diario d
            LEFT JOIN diario s ON s.fecha = d.fecha - INTERVAL 7 DAY
                              AND s.id_pais = d.id_pais AND s.canal_venta = d.canal_venta""",
    },
    {
        "nombre": "kpi_top_articulos",
        "particion": [],
        # Top 10 de artículos por categoría y día (parte del dashboard ejecutivo)
        "sql": """
            WITH ventas AS (
                SELECT v.fec_trans AS fecha, p.categoria_n1, v.art_id, p.desc_art,
                       SUM(v.vr_venta_neto) AS ventas_netas, SUM(v.qty_vendida) AS unidades
                FROM fact_ventas v JOIN dim_productos p ON p.art_id = v.art_id
                GROUP BY 1, 2, 3, 4
            )
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY fecha, categoria_n1
                                             ORDER BY ventas_netas DESC, art_id) AS posicion
                FROM ventas
            ) WHERE posicion <= 10""",
    },
    {
        "nombre": "kpi_tasa_devolucion",
        "particion": [],
        # Regla del PDF: unidades devueltas / vendidas del mismo periodo, en %, por categoría nivel 1 y canal
        "sql": """
            WITH vendido AS (
                SELECT strftime(v.fec_trans, '%Y-%m') AS mes, p.id_categ_n1, p.categoria_n1, v.canal_venta,
                       SUM(v.qty_vendida) AS unidades_vendidas
                FROM fact_ventas v JOIN dim_productos p ON p.art_id = v.art_id
                GROUP BY 1, 2, 3, 4
            ),
            devuelto AS (
                SELECT mes_devolucion AS mes, id_categ_n1, canal_venta_original AS canal_venta,
                       SUM(qty_devuelta) AS unidades_devueltas
                FROM fact_devoluciones GROUP BY 1, 2, 3
            )
            SELECT v.mes, v.id_categ_n1, v.categoria_n1, v.canal_venta, v.unidades_vendidas,
                   coalesce(d.unidades_devueltas, 0) AS unidades_devueltas,
                   round(coalesce(d.unidades_devueltas, 0) / v.unidades_vendidas * 100, 2) AS tasa_devolucion_pct
            FROM vendido v
            LEFT JOIN devuelto d ON d.mes = v.mes AND d.id_categ_n1 = v.id_categ_n1 AND d.canal_venta = v.canal_venta""",
    },
    {
        "nombre": "kpi_conversion_canal",
        "particion": [],
        # Conversión = compras / visitas. Por canal (categoria = 'TODAS') y por canal y categoría
        # (tickets que incluyen al menos un artículo de la categoría / visitas del canal).
        "sql": """
            WITH visitas AS (
                SELECT strftime(fec_visita, '%Y-%m') AS mes, canal, SUM(num_visitas) AS visitas
                FROM s_visitas GROUP BY 1, 2
            ),
            por_canal AS (
                SELECT strftime(fec_trans, '%Y-%m') AS mes, canal_venta AS canal, 'TODAS' AS categoria,
                       COUNT(DISTINCT id_trans) AS tickets, SUM(vr_venta_neto) AS ventas_netas
                FROM fact_ventas GROUP BY 1, 2
            ),
            por_categoria AS (
                SELECT strftime(v.fec_trans, '%Y-%m') AS mes, v.canal_venta AS canal, p.categoria_n1 AS categoria,
                       COUNT(DISTINCT v.id_trans) AS tickets, SUM(v.vr_venta_neto) AS ventas_netas
                FROM fact_ventas v JOIN dim_productos p ON p.art_id = v.art_id GROUP BY 1, 2, 3
            ),
            todo AS (SELECT * FROM por_canal UNION ALL SELECT * FROM por_categoria)
            SELECT t.mes, t.canal, t.categoria, t.tickets, vi.visitas,
                   round(t.tickets / NULLIF(vi.visitas, 0) * 100, 2) AS tasa_conversion_pct,
                   round(t.ventas_netas / t.tickets, 2) AS ticket_promedio
            FROM todo t LEFT JOIN visitas vi ON vi.mes = t.mes AND vi.canal = t.canal""",
    },
]

SILVER = ["proveedores", "articulos", "tiendas", "clientes", "ventas", "inventario", "devoluciones", "visitas"]


def escribir_tabla(lago: Lago, df: pl.DataFrame, tabla: dict, corte: str) -> None:
    uri = lago.uri("gold", tabla["nombre"])
    opciones = lago.opciones() or None
    escritura = {"partition_by": tabla["particion"]} if tabla["particion"] else {}

    if tabla.get("historico") and DeltaTable.is_deltatable(uri, storage_options=opciones):
        # Solo reemplaza la partición del corte actual: los cortes anteriores se conservan
        escritura["predicate"] = f"fecha_corte = '{corte}'"
    else:
        escritura["schema_mode"] = "overwrite"
    df.write_delta(uri, mode="overwrite", storage_options=opciones, delta_write_options=escritura)


def ejecutar(id_lote: str, tablas: list[str] | None = None) -> dict:
    cfg = cargar_config()
    lago = Lago(cfg)
    opciones = lago.opciones() or None

    con = duckdb.connect()
    for nombre in SILVER:
        con.register(f"s_{nombre}", pl.read_delta(lago.uri("silver", nombre), storage_options=opciones).to_arrow())
    con.register("ref_categorias", parametros.CATEGORIAS.to_arrow())
    con.register("ref_zonas", parametros.ZONAS_DISTRIBUCION.to_arrow())

    corte = str(con.execute("SELECT MAX(fec_trans) FROM s_ventas").fetchone()[0])
    ejecuciones, errores = [], []
    try:
        for tabla in TABLAS:
            if tablas and tabla["nombre"] not in tablas:
                continue
            inicio, momento = time.time(), bitacora.ahora_utc()
            try:
                parametros_sql = {"corte": corte} if "$corte" in tabla["sql"] else {}
                df = con.execute(tabla["sql"], parametros_sql).pl()
                if tabla["nombre"] == "fact_rfm_clientes":
                    df = df.with_columns(pl.col("segmento").replace_strict(parametros.ORDEN_SEGMENTOS)
                                         .alias("orden_segmento"))
                con_reintentos(lambda: escribir_tabla(lago, df, tabla, corte), f"Gold {tabla['nombre']}")
                con.register(tabla["nombre"], df.to_arrow())   # disponible para las tablas siguientes
                ejecuciones.append({
                    "id_lote": id_lote, "capa": "gold", "tabla": tabla["nombre"], "modo": f"corte {corte}",
                    "registros": df.height, "bytes": int(df.estimated_size()),
                    "duracion_s": round(time.time() - inicio, 2), "archivo": f"gold/{tabla['nombre']}",
                    "marca_agua_anterior": None, "marca_agua_nueva": None, "estado": "ok", "fecha_inicio": momento,
                })
            except Exception as exc:  # una tabla con error no detiene las independientes
                errores.append(bitacora.error_desde_excepcion("gold", tabla["nombre"], id_lote, exc))
    finally:
        con.close()
        bitacora.registrar_ejecuciones(lago, ejecuciones, id_lote)
        bitacora.registrar_errores(lago, errores, id_lote)

    return {"id_lote": id_lote, "capa": "gold", "ejecuciones": ejecuciones, "errores": errores}

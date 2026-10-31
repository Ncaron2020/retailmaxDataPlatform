"""
Capa Silver: datos limpios, tipados, sin duplicados y con relaciones validadas.

Lee Bronze, aplica las reglas de cada tabla (en SQL de DuckDB, portable a Spark SQL)
y escribe tablas Delta en silver/. Se recalcula completa desde Bronze en cada ejecución,
así que es idempotente: ejecutarla varias veces da siempre el mismo resultado.

Requisitos del PDF y dónde se cumplen:
  - Duplicados exactos ................... SELECT DISTINCT sobre las columnas de origen
  - Obligatorios nulos o corruptos ....... motivo_rechazo -> ops/rechazos
  - Estandarizar tipos ................... CAST / TRIM / UPPER en cada consulta
  - Integridad referencial ............... LEFT JOIN contra los maestros -> ops/rechazos con el motivo
  - Estrategia de nulos por columna ...... ver ESTRATEGIA_NULOS (documentada y aplicada)
  - Hash de datos personales (PII) ....... id_miembro -> id_cliente = SHA-256(salt + id), salt en Key Vault
  - Reporte de calidad por ejecución ..... ops/calidad_silver: % nulos, rechazados, % conformes
"""

from __future__ import annotations

import json
import time

import duckdb
import polars as pl

from comun import bitacora
from comun.config import cargar_config, obtener_salt_pii
from comun.lago import Lago
from comun.reintentos import con_reintentos
from silver import referencias

# Estrategia de nulos por columna (PDF: imputar con valor por defecto, excluir o marcar con indicador)
ESTRATEGIA_NULOS = {
    "TRANS_VENTAS": {
        "id_trans, id_tienda, art_id, fec_trans, qty_vendida, precio_unitario_venta": "excluir (obligatorios)",
        "id_miembro": "imputar 'ANONIMO' (venta sin cliente registrado) + ind_cliente_anonimo",
        "hra_trans": "marcar con ind_hora_nula (la venta es válida sin hora)",
        "tipo_pago": "imputar 'no_informado'",
        "descuento_aplicado": "imputar 0",
    },
    "CRM_MIEMBROS": {
        "id_miembro": "excluir (obligatorio)",
        "rango_edad": "imputar con la mediana del canal preferido + ind_rango_edad_imputado (regla del PDF)",
        "genero": "imputar 'No informado'",
        "fec_ultima_compra": "conservar nulo: el cliente nunca ha comprado",
    },
    "INV_STOCK_DIARIO": {
        "art_id, id_tienda, fec_snapshot, stock_fisico": "excluir (obligatorios)",
        "stock_transito, stock_reservado": "imputar 0 + ind_stock_imputado",
    },
    "POST_DEVOLUCIONES": {
        "id_devolucion, id_trans_origen, art_id, fec_devolucion, qty_devuelta": "excluir (obligatorios)",
        "motivo_cod": "imputar 'NI' (No informado)",
        "vr_reembolso": "marcar con ind_reembolso_pendiente (devolución en revisión)",
    },
    "TRAF_VISITAS": {"fec_visita, id_tienda, canal, num_visitas": "excluir (obligatorios)"},
    "MSTR_*": {"llave primaria": "excluir; el resto de columnas se conserva como llega"},
}

# Nombre de la tabla en Silver
DESTINO = {
    "MSTR_PROVEEDORES": "proveedores", "MSTR_ARTICULOS": "articulos", "MSTR_TIENDAS": "tiendas",
    "CRM_MIEMBROS": "clientes", "TRANS_VENTAS": "ventas", "INV_STOCK_DIARIO": "inventario",
    "POST_DEVOLUCIONES": "devoluciones", "TRAF_VISITAS": "visitas",
}

COLUMNAS_AUDITORIA = ["_fecha_ingesta", "_sistema_fuente", "_id_lote"]

# ------------------------------------------------------------
# Reglas por tabla. Cada una devuelve dos consultas sobre la vista "marcado":
#   - los registros válidos ya transformados
#   - los rechazados, con su motivo
# "marcado" = registros sin duplicados + columna motivo_rechazo (NULL si el registro es válido)
# ------------------------------------------------------------

REGLAS: dict[str, dict[str, str]] = {
    "MSTR_PROVEEDORES": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN id_proveedor IS NULL THEN 'Campo obligatorio nulo: id_proveedor' END AS motivo_rechazo
            FROM base b""",
        "validos": """
            SELECT id_proveedor, trim(razon_social) AS razon_social, trim(pais_origen) AS pais_origen,
                   tiempo_repo_dias, calificacion_calidad, CAST(activo AS BOOLEAN) AS activo
            FROM marcado WHERE motivo_rechazo IS NULL""",
    },
    "MSTR_ARTICULOS": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN art_id IS NULL THEN 'Campo obligatorio nulo: art_id'
                        WHEN precio_lista IS NULL OR precio_lista <= 0 THEN 'Precio de lista nulo o no positivo'
                   END AS motivo_rechazo
            FROM base b""",
        "validos": """
            SELECT art_id, CAST(cod_barra AS VARCHAR) AS cod_barra, trim(desc_art) AS desc_art,
                   id_categ_n1, id_categ_n2, id_categ_n3, id_proveedor, precio_lista, peso_kg,
                   upper(trim(unid_medida)) AS unid_medida, CAST(activo AS BOOLEAN) AS activo, fec_alta
            FROM marcado WHERE motivo_rechazo IS NULL""",
    },
    "MSTR_TIENDAS": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN id_tienda IS NULL THEN 'Campo obligatorio nulo: id_tienda' END AS motivo_rechazo
            FROM base b""",
        # tipo_tienda llega "sucio" ("hiper", "SUPERMERCADO", "Express"...): se lleva a un catálogo controlado
        "validos": """
            SELECT m.id_tienda, trim(m.nom_tienda) AS nom_tienda,
                   CASE WHEN lower(trim(m.tipo_tienda)) LIKE '%hiper%' THEN 'Hipermercado'
                        WHEN lower(trim(m.tipo_tienda)) LIKE '%super%' THEN 'Supermercado'
                        WHEN lower(trim(m.tipo_tienda)) LIKE '%conveni%'
                          OR lower(trim(m.tipo_tienda)) = 'express' THEN 'Conveniencia'
                        ELSE 'No clasificado' END AS tipo_tienda,
                   m.id_ciudad, c.nombre_ciudad, upper(trim(m.id_pais)) AS id_pais, p.nombre_pais,
                   m.metros_cuadrados, CAST(m.activo AS BOOLEAN) AS activo, m.fec_apertura
            FROM marcado m
            LEFT JOIN ref_ciudades c ON c.id_ciudad = m.id_ciudad
            LEFT JOIN ref_paises p ON p.codigo_pais = upper(trim(m.id_pais))
            WHERE m.motivo_rechazo IS NULL""",
    },
    "CRM_MIEMBROS": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN id_miembro IS NULL THEN 'Campo obligatorio nulo: id_miembro' END AS motivo_rechazo
            FROM base b""",
        # PII: id_miembro se reemplaza por su hash. El id original no pasa a Silver.
        # rango_edad nulo: mediana del canal preferido (regla del PDF), sobre el orden de los rangos.
        "validos": """
            WITH c AS (
                SELECT *, CASE rango_edad WHEN '18-24' THEN 1 WHEN '25-34' THEN 2 WHEN '35-44' THEN 3
                                          WHEN '45-54' THEN 4 WHEN '55-64' THEN 5 WHEN '65+' THEN 6 END AS orden
                FROM marcado WHERE motivo_rechazo IS NULL
            ),
            mediana AS (
                SELECT canal_pref, quantile_disc(orden, 0.5) AS orden_mediana
                FROM c WHERE orden IS NOT NULL GROUP BY canal_pref
            )
            SELECT sha256($salt || CAST(c.id_miembro AS VARCHAR)) AS id_cliente,
                   c.fec_registro, c.id_ciudad,
                   CASE WHEN upper(trim(c.genero)) IN ('M', 'MASCULINO', 'MASC') THEN 'M'
                        WHEN upper(trim(c.genero)) IN ('F', 'FEMENINO', 'FEM') THEN 'F'
                        ELSE 'No informado' END AS genero,
                   coalesce(c.rango_edad,
                            CASE mediana.orden_mediana WHEN 1 THEN '18-24' WHEN 2 THEN '25-34' WHEN 3 THEN '35-44'
                                 WHEN 4 THEN '45-54' WHEN 5 THEN '55-64' WHEN 6 THEN '65+' END) AS rango_edad,
                   c.rango_edad IS NULL AS ind_rango_edad_imputado,
                   lower(trim(c.canal_pref)) AS canal_pref, CAST(c.activo AS BOOLEAN) AS activo,
                   c.fec_ultima_compra
            FROM c LEFT JOIN mediana ON mediana.canal_pref = c.canal_pref""",
    },
    "TRANS_VENTAS": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN b.id_trans IS NULL OR b.id_tienda IS NULL OR b.art_id IS NULL OR b.fec_trans IS NULL
                             OR b.qty_vendida IS NULL OR b.precio_unitario_venta IS NULL
                             THEN 'Campo obligatorio nulo'
                        WHEN b.qty_vendida <= 0 THEN 'Cantidad vendida cero o negativa'
                        WHEN b.precio_unitario_venta <= 0 THEN 'Precio unitario cero o negativo'
                        WHEN a.art_id IS NULL THEN 'Integridad referencial: art_id no existe en MSTR_ARTICULOS'
                        WHEN t.id_tienda IS NULL THEN 'Integridad referencial: id_tienda no existe en MSTR_TIENDAS'
                   END AS motivo_rechazo,
                   k.id_miembro IS NOT NULL AS miembro_existe
            FROM base b
            LEFT JOIN s_articulos a ON a.art_id = b.art_id
            LEFT JOIN s_tiendas t ON t.id_tienda = b.id_tienda
            LEFT JOIN ids_miembros k ON k.id_miembro = b.id_miembro""",
        # Cliente inexistente o vacío -> 'ANONIMO' (regla del PDF: "validar id_miembro o asignar cliente anónimo")
        "validos": """
            SELECT id_trans,
                   CASE WHEN miembro_existe THEN sha256($salt || CAST(id_miembro AS VARCHAR)) ELSE 'ANONIMO' END AS id_cliente,
                   NOT miembro_existe AS ind_cliente_anonimo,
                   id_tienda, art_id, fec_trans,
                   CAST(hra_trans AS VARCHAR) AS hra_trans, hra_trans IS NULL AS ind_hora_nula,
                   qty_vendida, precio_unitario_venta,
                   coalesce(descuento_aplicado, 0) AS descuento_aplicado,
                   coalesce(lower(trim(tipo_pago)), 'no_informado') AS tipo_pago,
                   lower(trim(canal_venta)) AS canal_venta
            FROM marcado WHERE motivo_rechazo IS NULL""",
    },
    "INV_STOCK_DIARIO": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN b.art_id IS NULL OR b.id_tienda IS NULL OR b.fec_snapshot IS NULL OR b.stock_fisico IS NULL
                             THEN 'Campo obligatorio nulo'
                        WHEN b.stock_fisico < 0 THEN 'Stock físico negativo'
                        WHEN a.art_id IS NULL THEN 'Integridad referencial: art_id no existe en MSTR_ARTICULOS'
                        WHEN t.id_tienda IS NULL THEN 'Integridad referencial: id_tienda no existe en MSTR_TIENDAS'
                   END AS motivo_rechazo
            FROM base b
            LEFT JOIN s_articulos a ON a.art_id = b.art_id
            LEFT JOIN s_tiendas t ON t.id_tienda = b.id_tienda""",
        "validos": """
            SELECT id_snapshot, art_id, id_tienda, fec_snapshot, stock_fisico,
                   coalesce(stock_transito, 0) AS stock_transito,
                   coalesce(stock_reservado, 0) AS stock_reservado,
                   (stock_transito IS NULL OR stock_reservado IS NULL) AS ind_stock_imputado,
                   stock_minimo_config, stock_maximo_config
            FROM marcado WHERE motivo_rechazo IS NULL""",
    },
    "POST_DEVOLUCIONES": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN b.id_devolucion IS NULL OR b.id_trans_origen IS NULL OR b.art_id IS NULL
                             OR b.fec_devolucion IS NULL OR b.qty_devuelta IS NULL
                             THEN 'Campo obligatorio nulo'
                        WHEN b.qty_devuelta <= 0 THEN 'Cantidad devuelta cero o negativa'
                        WHEN v.id_trans IS NULL THEN 'Integridad referencial: la venta de origen no existe en TRANS_VENTAS'
                        WHEN b.qty_devuelta > v.qty_vendida THEN 'Devolución mayor a la cantidad vendida'
                   END AS motivo_rechazo
            FROM base b
            LEFT JOIN s_ventas v ON v.id_trans = b.id_trans_origen AND v.art_id = b.art_id""",
        # motivo_cod llega "sucio" ("def", " DEF"): se normaliza y se traduce a descripción legible
        "validos": """
            SELECT m.id_devolucion, m.id_trans_origen, m.art_id, m.id_tienda, m.fec_devolucion, m.qty_devuelta,
                   coalesce(upper(trim(m.motivo_cod)), 'NI') AS motivo_cod,
                   coalesce(r.motivo_descripcion, 'No informado') AS motivo_descripcion,
                   lower(trim(m.canal_devolucion)) AS canal_devolucion,
                   lower(trim(m.estado_devolucion)) AS estado_devolucion,
                   m.vr_reembolso, m.vr_reembolso IS NULL AS ind_reembolso_pendiente
            FROM marcado m
            LEFT JOIN ref_motivos r ON r.motivo_cod = coalesce(upper(trim(m.motivo_cod)), 'NI')
            WHERE m.motivo_rechazo IS NULL""",
    },
    "TRAF_VISITAS": {
        "marcado": """
            SELECT b.*, to_json(b) AS registro,
                   CASE WHEN b.fec_visita IS NULL OR b.id_tienda IS NULL OR b.canal IS NULL OR b.num_visitas IS NULL
                             THEN 'Campo obligatorio nulo'
                        WHEN b.num_visitas < 0 THEN 'Número de visitas negativo'
                        WHEN t.id_tienda IS NULL THEN 'Integridad referencial: id_tienda no existe en MSTR_TIENDAS'
                   END AS motivo_rechazo
            FROM base b
            LEFT JOIN s_tiendas t ON t.id_tienda = b.id_tienda""",
        "validos": """
            SELECT id_visita, fec_visita, id_tienda, lower(trim(canal)) AS canal, num_visitas
            FROM marcado WHERE motivo_rechazo IS NULL""",
    },
}

MAESTROS = ["MSTR_PROVEEDORES", "MSTR_ARTICULOS", "MSTR_TIENDAS", "CRM_MIEMBROS"]
# Orden: primero maestros (las transaccionales se validan contra ellos); devoluciones después de ventas
ORDEN = MAESTROS + ["TRANS_VENTAS", "INV_STOCK_DIARIO", "TRAF_VISITAS", "POST_DEVOLUCIONES"]


def leer_bronze(lago: Lago, tabla: str) -> pl.DataFrame:
    df = lago.leer_parquet_carpeta("bronze", tabla)
    if tabla in MAESTROS:
        # Maestros: Bronze guarda un snapshot por ejecución; Silver usa el más reciente
        df = df.filter(pl.col("_fecha_ingesta") == pl.col("_fecha_ingesta").max())
    return df.drop(COLUMNAS_AUDITORIA)


def porcentaje_nulos(df: pl.DataFrame) -> dict:
    if df.height == 0:
        return {}
    return {c: round(n / df.height * 100, 2) for c, n in zip(df.columns, df.null_count().row(0)) if n}


def procesar_tabla(con: duckdb.DuckDBPyConnection, lago: Lago, tabla: str, salt: str, id_lote: str):
    inicio, momento = time.time(), bitacora.ahora_utc()
    bronze = leer_bronze(lago, tabla)
    con.register("bronze_actual", bronze.to_arrow())

    # Duplicados exactos: se quedan fuera con DISTINCT (se cuentan para el reporte)
    con.execute("CREATE OR REPLACE TEMP VIEW base AS SELECT DISTINCT * FROM bronze_actual")
    con.execute(f"CREATE OR REPLACE TEMP VIEW marcado AS {REGLAS[tabla]['marcado']}")

    parametros = {"salt": salt} if "$salt" in REGLAS[tabla]["validos"] else {}
    validos = con.execute(REGLAS[tabla]["validos"], parametros).pl()
    rechazos = con.execute("SELECT motivo_rechazo, CAST(registro AS VARCHAR) AS registro "
                           "FROM marcado WHERE motivo_rechazo IS NOT NULL").pl()
    sin_duplicados = con.execute("SELECT COUNT(*) FROM base").fetchone()[0]

    # Escritura en Silver como tabla Delta (sobrescribe: el resultado es siempre el mismo)
    destino = DESTINO[tabla]
    validos.write_delta(lago.uri("silver", destino), mode="overwrite",
                        storage_options=lago.opciones() or None,
                        delta_write_options={"schema_mode": "overwrite"})

    # Las vistas s_* quedan disponibles para validar las tablas siguientes
    con.register(f"s_{destino}", validos.to_arrow())
    if tabla == "CRM_MIEMBROS":
        con.register("ids_miembros", bronze.select("id_miembro").to_arrow())

    rechazos = rechazos.with_columns(
        pl.lit(id_lote).alias("id_lote"), pl.lit("silver").alias("capa"),
        pl.lit(tabla).alias("tabla"), pl.lit(momento).alias("fecha_rechazo"))

    calidad = {
        "id_lote": id_lote,
        "tabla": tabla,
        "tabla_silver": destino,
        "registros_entrada": bronze.height,
        "duplicados_eliminados": bronze.height - sin_duplicados,
        "rechazados": rechazos.height,
        "conformes": validos.height,
        "pct_conformes": round(validos.height / bronze.height * 100, 2) if bronze.height else 0.0,
        "pct_nulos_por_columna": json.dumps(porcentaje_nulos(validos), ensure_ascii=False),
        "rechazos_por_motivo": json.dumps(dict(rechazos.group_by("motivo_rechazo").len().iter_rows()),
                                          ensure_ascii=False),
        "fecha": momento,
    }
    ejecucion = {
        "id_lote": id_lote, "capa": "silver", "tabla": tabla, "modo": "recalculo",
        "registros": validos.height, "bytes": int(validos.estimated_size()),
        "duracion_s": round(time.time() - inicio, 2), "archivo": f"silver/{destino}",
        "marca_agua_anterior": None, "marca_agua_nueva": None, "estado": "ok", "fecha_inicio": momento,
    }
    return ejecucion, calidad, rechazos


def ejecutar(id_lote: str, tablas: list[str] | None = None) -> dict:
    cfg = cargar_config()
    lago = Lago(cfg)
    salt = obtener_salt_pii(cfg)

    con = duckdb.connect()
    con.register("ref_ciudades", referencias.CIUDADES.to_arrow())
    con.register("ref_paises", referencias.PAISES.to_arrow())
    con.register("ref_motivos", referencias.MOTIVOS_DEVOLUCION.to_arrow())

    ejecuciones, calidades, rechazos, errores = [], [], [], []
    try:
        for tabla in [t for t in ORDEN if not tablas or t in tablas]:
            try:
                ejecucion, calidad, rech = con_reintentos(
                    lambda: procesar_tabla(con, lago, tabla, salt, id_lote), f"Silver {tabla}")
                ejecuciones.append(ejecucion)
                calidades.append(calidad)
                if rech.height:
                    rechazos.append(rech)
            except Exception as exc:  # una tabla con error no detiene las demás
                errores.append(bitacora.error_desde_excepcion("silver", tabla, id_lote, exc))
    finally:
        con.close()
        bitacora.registrar_ejecuciones(lago, ejecuciones, id_lote)
        bitacora.registrar_errores(lago, errores, id_lote)
        momento = bitacora.ahora_utc()
        particion = f"anio={momento:%Y}/mes={momento:%m}/dia={momento:%d}/{id_lote}.parquet"
        if calidades:
            lago.escribir_parquet(pl.DataFrame(calidades), "ops", f"calidad_silver/{particion}")
        if rechazos:
            lago.escribir_parquet(pl.concat(rechazos, how="diagonal_relaxed"), "ops", f"rechazos/{particion}")

    return {"id_lote": id_lote, "capa": "silver", "ejecuciones": ejecuciones,
            "calidad": calidades, "errores": errores}

"""
Generador de datos sintéticos de RetailMax (escenario B).

Lee config.yaml y produce las tablas de origen en generacion-datos/output/:
  - CSV:     MSTR_PROVEEDORES, MSTR_ARTICULOS, MSTR_TIENDAS, CRM_MIEMBROS, POST_DEVOLUCIONES
  - Parquet: TRANS_VENTAS, INV_STOCK_DIARIO, TRAF_VISITAS
y un resumen_generacion.json con los conteos y las anomalías plantadas.

Uso:
    python generate.py                     # usa config.yaml de esta carpeta
    python generate.py --config otro.yaml

Con la misma semilla, el resultado es siempre idéntico (reproducible).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np
import polars as pl
import yaml
from faker import Faker

CARPETA = Path(__file__).resolve().parent

# Volúmenes mínimos exigidos por la prueba (escenario B)
MINIMOS = {
    "MSTR_ARTICULOS": 5_000,
    "MSTR_PROVEEDORES": 800,
    "MSTR_TIENDAS": 150,
    "CRM_MIEMBROS": 50_000,
    "TRANS_VENTAS": 1_000_000,
    "INV_STOCK_DIARIO": 750_000,
    "POST_DEVOLUCIONES": 50_000,
}

# ------------------------------------------------------------
# Catálogos de referencia (datos fijos del negocio)
# ------------------------------------------------------------

# Ciudades por país: (id_ciudad, nombre). El origen solo guarda el id;
# Silver usa este mismo catálogo para enriquecer con el nombre.
CIUDADES = {
    "CO": [(101, "Bogotá"), (102, "Medellín"), (103, "Cali"), (104, "Barranquilla"), (105, "Bucaramanga")],
    "MX": [(201, "Ciudad de México"), (202, "Guadalajara"), (203, "Monterrey"), (204, "Puebla")],
    "CL": [(301, "Santiago"), (302, "Valparaíso"), (303, "Concepción")],
    "PE": [(401, "Lima"), (402, "Arequipa"), (403, "Trujillo")],
    "EC": [(501, "Quito"), (502, "Guayaquil"), (503, "Cuenca")],
}
PESO_PAIS = {"CO": 0.35, "MX": 0.30, "CL": 0.15, "PE": 0.12, "EC": 0.08}

# Seis macro categorías del PDF: nombre, rango de precio (USD), rango de peso (kg),
# productos típicos y unidades de medida posibles.
CATEGORIAS = {
    1: ("Alimentos y bebidas", (1.5, 40), (0.2, 5),
        ["Arroz", "Aceite", "Leche", "Café", "Galletas", "Jugo", "Pasta", "Atún", "Azúcar", "Gaseosa"],
        ["UND", "KG", "LT", "PAQ"]),
    2: ("Cuidado personal e higiene", (2, 35), (0.1, 1.5),
        ["Shampoo", "Jabón", "Crema dental", "Desodorante", "Acondicionador", "Toallas higiénicas"],
        ["UND", "PAQ"]),
    3: ("Hogar y limpieza", (2, 60), (0.3, 6),
        ["Detergente", "Suavizante", "Limpiador", "Papel higiénico", "Esponja", "Bolsas de basura"],
        ["UND", "LT", "PAQ"]),
    4: ("Electrónica y tecnología", (15, 900), (0.1, 8),
        ["Audífonos", "Cargador", "Mouse", "Teclado", "Parlante", "Memoria USB", "Smartwatch"],
        ["UND"]),
    5: ("Ropa y calzado básico", (6, 80), (0.1, 1.2),
        ["Camiseta", "Medias", "Jean", "Pantaloneta", "Buzo", "Tenis"],
        ["UND", "PAQ"]),
    6: ("Bebés y maternidad", (3, 120), (0.2, 4),
        ["Pañales", "Biberón", "Fórmula infantil", "Pañitos húmedos", "Chupo", "Crema antipañalitis"],
        ["UND", "PAQ"]),
}
PESO_CATEGORIA = [0.35, 0.15, 0.15, 0.10, 0.15, 0.10]
MARCAS = ["Marca Propia", "Andina", "Sol", "Prisma", "Nova", "Vital", "Kora", "Delta"]
PRESENTACIONES = {
    1: ["250 g", "500 g", "1 kg", "500 ml", "1 L", "2 L", "x6"],
    2: ["200 ml", "400 ml", "x3", "x10"],
    3: ["500 ml", "1 L", "2 L", "x4", "x12"],
    4: ["Negro", "Blanco", "Azul", "Gris"],
    5: ["Talla S", "Talla M", "Talla L", "Talla XL"],
    6: ["Etapa 1", "Etapa 2", "x30", "x50", "400 g"],
}

# Tipo de tienda "real" y las formas "sucias" en que el sistema legado lo guarda.
# Silver debe estandarizarlas a un catálogo controlado.
TIPOS_TIENDA = {
    "Hipermercado": (0.20, (4000, 12000), ["Hipermercado", "HIPERMERCADO", "hiper", " Hipermercado "]),
    "Supermercado": (0.50, (800, 2500), ["Supermercado", "SUPERMERCADO", "super de barrio", "Supermercado barrio"]),
    "Conveniencia": (0.30, (80, 300), ["Conveniencia", "CONVENIENCIA", "tienda conveniencia", "Express"]),
}

# Género "real" y sus variantes sucias. Silver lo estandariza a M, F o No informado.
GENEROS = {
    "M": (0.48, ["M", "Masculino", "masc", "m"]),
    "F": (0.50, ["F", "Femenino", "fem", "f"]),
    "X": (0.02, ["Otro", "X"]),
}
RANGOS_EDAD = (["18-24", "25-34", "35-44", "45-54", "55-64", "65+"],
               [0.12, 0.28, 0.25, 0.18, 0.11, 0.06])

PAISES_PROVEEDOR = (["Colombia", "México", "Chile", "Perú", "Ecuador", "China", "Estados Unidos", "Brasil"],
                    [0.30, 0.20, 0.10, 0.08, 0.05, 0.15, 0.08, 0.04])


# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

def cargar_config(ruta: Path) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def a_fecha(texto: str) -> np.datetime64:
    return np.datetime64(texto, "D")


def fechas_aleatorias(rng, n, desde: np.datetime64, hasta: np.datetime64) -> np.ndarray:
    """n fechas uniformes entre desde y hasta (incluidas)."""
    dias = (hasta - desde).astype(int)
    return desde + rng.integers(0, dias + 1, n).astype("timedelta64[D]")


def elegir_por_pesos(rng, opciones: dict, n) -> np.ndarray:
    """Elige n valores de un diccionario {valor: probabilidad}."""
    valores = list(opciones.keys())
    pesos = np.array(list(opciones.values()), dtype=float)
    return rng.choice(valores, n, p=pesos / pesos.sum())


def poner_nulos(df: pl.DataFrame, columnas: list[str], pct: float, rng) -> pl.DataFrame:
    """Reemplaza ~pct de los valores de cada columna por NULL (suciedad del sistema legado)."""
    for col in columnas:
        mascara = pl.Series(rng.random(df.height) < pct)
        df = df.with_columns(pl.when(mascara).then(None).otherwise(pl.col(col)).alias(col))
    return df


def segundos_a_hora(segundos: np.ndarray) -> pl.Series:
    """Convierte segundos desde medianoche a tipo Time de polars."""
    return pl.Series(segundos.astype(np.int64) * 1_000_000_000).cast(pl.Time)


# ------------------------------------------------------------
# Maestros
# ------------------------------------------------------------

def generar_proveedores(cfg, rng, fake) -> pl.DataFrame:
    n = cfg["maestros"]["proveedores"]
    paises, pesos = PAISES_PROVEEDOR
    pais = rng.choice(paises, n, p=pesos)
    es_local = np.isin(pais, paises[:5])
    # Proveedores locales reponen en días; los importados, en semanas
    tiempo = np.where(es_local, rng.integers(2, 11, n), rng.integers(15, 46, n))
    return pl.DataFrame({
        "id_proveedor": np.arange(1, n + 1),
        "razon_social": [fake.company() for _ in range(n)],
        "pais_origen": pais,
        "tiempo_repo_dias": tiempo,
        "calificacion_calidad": np.round(np.clip(rng.normal(3.8, 0.6, n), 1, 5), 2),
        "activo": (rng.random(n) < 0.95).astype(np.int8),
    })


def generar_articulos(cfg, rng, proveedores: pl.DataFrame) -> tuple[pl.DataFrame, np.ndarray]:
    n = cfg["maestros"]["articulos"]
    inicio = a_fecha(cfg["periodo"]["fecha_inicio"])

    n1 = rng.choice(list(CATEGORIAS.keys()), n, p=PESO_CATEGORIA)
    n2 = n1 * 100 + rng.integers(1, 5, n)          # 4 subcategorías por categoría
    n3 = n2 * 100 + rng.integers(1, 4, n)          # 3 sub-subcategorías por subcategoría

    precio, peso, unidad, descripcion = [], [], [], []
    for cat in n1:
        _, (p_min, p_max), (k_min, k_max), productos, unidades = CATEGORIAS[cat]
        # Distribución log-uniforme: muchos productos baratos, pocos caros
        precio.append(round(float(np.exp(rng.uniform(np.log(p_min), np.log(p_max)))), 2))
        peso.append(round(float(rng.uniform(k_min, k_max)), 3))
        unidad.append(rng.choice(unidades))
        descripcion.append(f"{rng.choice(productos)} {rng.choice(MARCAS)} {rng.choice(PRESENTACIONES[cat])}")

    articulos = pl.DataFrame({
        "art_id": np.arange(100_001, 100_001 + n),
        "cod_barra": [f"770{x}" for x in rng.integers(10**9, 10**10, n)],
        "desc_art": descripcion,
        "id_categ_n1": n1,
        "id_categ_n2": n2,
        "id_categ_n3": n3,
        "id_proveedor": rng.choice(proveedores["id_proveedor"].to_numpy(), n),
        "precio_lista": precio,
        "peso_kg": peso,
        "unid_medida": unidad,
        "activo": (rng.random(n) < 0.92).astype(np.int8),
        # Todos los artículos existen antes del período, para que ninguna venta sea anterior a su alta
        "fec_alta": fechas_aleatorias(rng, n, a_fecha("2015-01-01"), inicio - np.timedelta64(1, "D")),
    })

    # Popularidad: pocos artículos venden mucho y muchos venden poco (ley de potencia).
    popularidad = np.empty(n)
    popularidad[rng.permutation(n)] = 1.0 / np.arange(1, n + 1) ** 0.8
    return articulos, popularidad / popularidad.sum()


def generar_tiendas(cfg, rng) -> pl.DataFrame:
    n = cfg["maestros"]["tiendas"]
    paises = cfg["maestros"]["paises"]
    pesos = np.array([PESO_PAIS[p] for p in paises])
    pais = rng.choice(paises, n, p=pesos / pesos.sum())

    tipos = list(TIPOS_TIENDA.keys())
    tipo_real = rng.choice(tipos, n, p=[TIPOS_TIENDA[t][0] for t in tipos])

    id_ciudad, nombre, tipo_sucio, metros = [], [], [], []
    for i in range(n):
        ciudad_id, ciudad_nombre = CIUDADES[pais[i]][rng.integers(len(CIUDADES[pais[i]]))]
        _, (m_min, m_max), variantes = TIPOS_TIENDA[tipo_real[i]]
        id_ciudad.append(ciudad_id)
        nombre.append(f"RetailMax {tipo_real[i]} {ciudad_nombre} {i + 1:03d}")
        tipo_sucio.append(rng.choice(variantes))
        metros.append(round(float(rng.uniform(m_min, m_max)), 2))

    return pl.DataFrame({
        "id_tienda": np.arange(1, n + 1),
        "nom_tienda": nombre,
        "tipo_tienda": tipo_sucio,
        "id_ciudad": id_ciudad,
        "id_pais": pais,
        "metros_cuadrados": metros,
        "activo": (rng.random(n) < 0.97).astype(np.int8),
        "fec_apertura": fechas_aleatorias(rng, n, a_fecha("1998-01-01"), a_fecha("2024-12-31")),
    })


def generar_miembros(cfg, rng) -> tuple[pl.DataFrame, np.ndarray]:
    n = cfg["maestros"]["miembros"]
    fin = a_fecha(cfg["periodo"]["fecha_fin"])
    canales = list(cfg["ventas"]["canales"].keys())

    todas_ciudades = [c for p in cfg["maestros"]["paises"] for c, _ in CIUDADES[p]]

    generos = list(GENEROS.keys())
    genero_real = rng.choice(generos, n, p=[GENEROS[g][0] for g in generos])
    genero_sucio = np.array([rng.choice(GENEROS[g][1]) for g in genero_real], dtype=object)

    miembros = pl.DataFrame({
        "id_miembro": np.arange(1, n + 1),
        # fec_registro se ajusta después para que nadie compre antes de registrarse
        "fec_registro": fechas_aleatorias(rng, n, a_fecha("2015-01-01"), fin),
        "id_ciudad": rng.choice(todas_ciudades, n),
        "genero": genero_sucio,
        "rango_edad": rng.choice(RANGOS_EDAD[0], n, p=RANGOS_EDAD[1]),
        "canal_pref": rng.choice(canales, n, p=[0.55, 0.25, 0.20]),
        "activo": (rng.random(n) < 0.90).astype(np.int8),
    })

    # Propensión a comprar: pocos clientes compran mucho (útil para que el RFM tenga contraste).
    propension = rng.pareto(1.5, n) + 1
    propension[miembros["activo"].to_numpy() == 0] *= 0.2
    return miembros, propension / propension.sum()


# ------------------------------------------------------------
# Ventas
# ------------------------------------------------------------

def pesos_por_dia(cfg, dias: np.ndarray) -> np.ndarray:
    """Peso relativo de ventas de cada día: estacionalidad, fines de semana y el día anómalo."""
    v = cfg["ventas"]
    meses = (dias.astype("datetime64[M]").astype(int) % 12) + 1
    pesos = np.array([v["estacionalidad"].get(int(m), 1.0) for m in meses], dtype=float)
    # 1970-01-01 fue jueves: (días + 3) % 7 da 0 = lunes ... 5 = sábado, 6 = domingo
    dia_semana = (dias.astype(int) + 3) % 7
    pesos[dia_semana >= 5] *= v["fin_de_semana"]
    anomalo = cfg["anomalias"]["dia_volumen_anomalo"]
    pesos[dias == a_fecha(anomalo["fecha"])] *= anomalo["factor"]
    return pesos / pesos.sum()


def generar_ventas(cfg, rng, articulos, popularidad, tiendas, miembros, propension):
    """Devuelve (ventas_limpias, tickets). Las anomalías se agregan aparte."""
    v = cfg["ventas"]
    inicio, fin = a_fecha(cfg["periodo"]["fecha_inicio"]), a_fecha(cfg["periodo"]["fecha_fin"])
    dias = np.arange(inicio, fin + np.timedelta64(1, "D"))
    n = v["transacciones"]

    # --- Nivel ticket ---
    dia_idx = rng.choice(len(dias), n, p=pesos_por_dia(cfg, dias))
    es_miembro = rng.random(n) >= v["pct_anonimas"]
    id_miembro = np.where(es_miembro, rng.choice(miembros["id_miembro"].to_numpy(), n, p=propension), 0)

    canal = elegir_por_pesos(rng, v["canales"], n)
    # El 60% de las veces, un miembro compra por su canal preferido
    canal_pref = miembros["canal_pref"].to_numpy()
    usa_pref = es_miembro & (rng.random(n) < 0.6)
    canal[usa_pref] = canal_pref[id_miembro[usa_pref] - 1]

    # Tiendas grandes reciben más tickets. En web/app, la tienda es la que despacha el pedido.
    peso_tienda = np.sqrt(tiendas["metros_cuadrados"].to_numpy())
    id_tienda = rng.choice(tiendas["id_tienda"].to_numpy(), n, p=peso_tienda / peso_tienda.sum())

    # Hora: tiendas físicas de 7 a 21 h con pico en la tarde; web/app más tarde y en la noche
    fisica = canal == "tienda_fisica"
    horas = np.where(fisica, np.clip(rng.normal(15, 3.5, n), 7, 21.9), rng.normal(20, 4, n) % 24)
    segundos = (horas * 3600).astype(int)

    tipo_pago = elegir_por_pesos(rng, v["tipos_pago"], n)
    tipo_pago[(~fisica) & (tipo_pago == "efectivo")] = "tarjeta_credito"   # no hay efectivo en línea

    # Ordenar tickets por fecha y hora para que id_trans sea creciente en el tiempo
    orden = np.lexsort((segundos, dia_idx))
    dia_idx, id_miembro, canal, id_tienda, segundos, tipo_pago = (
        x[orden] for x in (dia_idx, id_miembro, canal, id_tienda, segundos, tipo_pago))
    id_trans = np.arange(10_000_001, 10_000_001 + n)

    tickets = pl.DataFrame({
        "id_trans": id_trans,
        "fec_trans": dias[dia_idx],
        "id_tienda": id_tienda,
        "canal_venta": canal,
    })

    # --- Nivel línea: cada ticket se expande en varios artículos ---
    lo, hi = v["lineas_por_transaccion"]
    lineas = rng.integers(lo, hi + 1, n)
    t = np.repeat(np.arange(n), lineas)
    art_pos = rng.choice(articulos.height, len(t), p=popularidad)

    ventas = pl.DataFrame({"_t": t, "_art": art_pos}).unique(["_t", "_art"], keep="first", maintain_order=True)
    t, art_pos = ventas["_t"].to_numpy(), ventas["_art"].to_numpy()
    m = len(t)

    qty = rng.geometric(0.55, m)                                   # 1 la mayoría de las veces
    precio_lista = articulos["precio_lista"].to_numpy()[art_pos]
    precio = np.round(precio_lista * rng.uniform(0.97, 1.03, m), 2)  # el precio de venta varía un poco
    con_desc = rng.random(m) < v["pct_con_descuento"]
    descuento = np.where(con_desc, np.round(precio * qty * rng.uniform(0.05, v["descuento_max_pct"], m), 2), 0.0)

    ventas = pl.DataFrame({
        "id_trans": id_trans[t],
        "id_miembro": pl.Series(id_miembro[t]).replace(0, None),   # 0 = anónimo -> NULL
        "id_tienda": id_tienda[t],
        "art_id": articulos["art_id"].to_numpy()[art_pos],
        "fec_trans": dias[dia_idx[t]],
        "hra_trans": segundos_a_hora(segundos[t]),
        "qty_vendida": qty,
        "precio_unitario_venta": precio,
        "descuento_aplicado": descuento,
        "tipo_pago": tipo_pago[t],
        "canal_venta": canal[t],
    })
    ventas = poner_nulos(ventas, ["hra_trans", "tipo_pago"], cfg["calidad"]["pct_nulos"], rng)
    return ventas, tickets


def plantar_anomalias_ventas(cfg, rng, ventas: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    a = cfg["anomalias"]
    n = ventas.height
    resumen = {}

    # 1. Cantidad 0 o negativa
    idx = rng.choice(n, int(n * a["ventas_qty_invalida"]), replace=False)
    qty = ventas["qty_vendida"].to_numpy().copy()
    qty[idx] = rng.choice([0, -1, -2, -3], len(idx))
    resumen["ventas_qty_invalida"] = len(idx)

    # 2. Artículo huérfano: art_id que no existe en el maestro
    idx = rng.choice(n, int(n * a["ventas_articulo_huerfano"]), replace=False)
    art = ventas["art_id"].to_numpy().copy()
    art[idx] = rng.integers(900_001, 999_999, len(idx))
    resumen["ventas_articulo_huerfano"] = len(idx)

    ventas = ventas.with_columns(pl.Series("qty_vendida", qty), pl.Series("art_id", art))

    # 3. Duplicados exactos: la misma línea cargada dos veces
    idx = rng.choice(n, int(n * a["ventas_duplicadas"]), replace=False)
    ventas = pl.concat([ventas, ventas[idx]]).sort(["id_trans", "art_id"])
    resumen["ventas_duplicadas"] = len(idx)

    resumen["dia_volumen_anomalo"] = a["dia_volumen_anomalo"]["fecha"]
    return ventas, resumen


def ajustar_miembros(miembros: pl.DataFrame, ventas: pl.DataFrame, rng) -> pl.DataFrame:
    """fec_registro antes de la primera compra y fec_ultima_compra = última compra real."""
    compras = (ventas.filter(pl.col("id_miembro").is_not_null())
               .group_by("id_miembro")
               .agg(pl.col("fec_trans").min().alias("_primera"), pl.col("fec_trans").max().alias("fec_ultima_compra")))
    miembros = miembros.join(compras, on="id_miembro", how="left")
    antes = pl.Series(rng.integers(1, 366, miembros.height)).cast(pl.Duration("ms")) * 86_400_000
    return (miembros
            .with_columns(
                pl.when(pl.col("_primera").is_not_null() & (pl.col("fec_registro") > pl.col("_primera")))
                .then((pl.col("_primera").cast(pl.Datetime("ms")) - antes).cast(pl.Date))
                .otherwise(pl.col("fec_registro"))
                .alias("fec_registro"))
            .drop("_primera"))


# ------------------------------------------------------------
# Devoluciones
# ------------------------------------------------------------

def generar_devoluciones(cfg, rng, ventas_limpias: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    d = cfg["devoluciones"]
    fin = a_fecha(cfg["periodo"]["fecha_fin"])
    n_dev = int(np.ceil(ventas_limpias.height * d["pct_lineas_devueltas"]))

    base = ventas_limpias[rng.choice(ventas_limpias.height, n_dev, replace=False)]
    qty = base["qty_vendida"].to_numpy()
    fec = base["fec_trans"].to_numpy().astype("datetime64[D]") + \
        rng.integers(0, d["dias_max_despues_venta"] + 1, n_dev).astype("timedelta64[D]")
    dentro = fec <= fin                       # devoluciones futuras todavía no existen
    base, qty, fec = base.filter(pl.Series(dentro)), qty[dentro], fec[dentro]
    n_dev = base.height

    qty_dev = rng.integers(1, qty + 1)        # entre 1 y lo comprado
    # Anomalía: devolver más unidades de las que se compraron
    idx = rng.choice(n_dev, int(n_dev * cfg["anomalias"]["devolucion_mayor_a_venta"]), replace=False)
    qty_dev[idx] = qty[idx] + rng.integers(1, 4, len(idx))

    motivos = np.array(list(d["motivos"].keys()))
    motivo = rng.choice(motivos, n_dev, p=[0.30, 0.20, 0.25, 0.15, 0.10]).astype(object)
    sucio = rng.random(n_dev) < 0.04          # códigos mal digitados: "def", " DEF"
    motivo[sucio] = [rng.choice([m.lower(), f" {m}"]) for m in motivo[sucio]]

    canal = base["canal_venta"].to_numpy().copy()
    canal[rng.random(n_dev) < 0.15] = "tienda_fisica"   # muchas compras en línea se devuelven en tienda

    estado = rng.choice(d["estados"], n_dev, p=[0.75, 0.10, 0.15])
    precio = base["precio_unitario_venta"].to_numpy()
    desc_unit = base["descuento_aplicado"].to_numpy() / np.maximum(qty, 1)
    reembolso = np.round(qty_dev * (precio - desc_unit), 2)

    orden = np.argsort(fec, kind="stable")
    devoluciones = pl.DataFrame({
        "id_devolucion": np.arange(1, n_dev + 1),
        "id_trans_origen": base["id_trans"].to_numpy()[orden],
        "art_id": base["art_id"].to_numpy()[orden],
        "id_tienda": base["id_tienda"].to_numpy()[orden],
        "fec_devolucion": fec[orden],
        "qty_devuelta": qty_dev[orden],
        "motivo_cod": motivo[orden],
        "canal_devolucion": canal[orden],
        "estado_devolucion": estado[orden],
        "vr_reembolso": reembolso[orden],
    })
    # Rechazadas no se reembolsan; en revisión todavía no tienen valor
    devoluciones = devoluciones.with_columns(
        pl.when(pl.col("estado_devolucion") == "rechazada").then(0.0)
        .when(pl.col("estado_devolucion") == "en_revision").then(None)
        .otherwise(pl.col("vr_reembolso")).alias("vr_reembolso"))
    devoluciones = poner_nulos(devoluciones, ["motivo_cod"], cfg["calidad"]["pct_nulos"], rng)
    return devoluciones, {"devolucion_mayor_a_venta": len(idx), "motivo_cod_mal_digitado": int(sucio.sum())}


# ------------------------------------------------------------
# Inventario diario
# ------------------------------------------------------------

def generar_inventario(cfg, rng, articulos, popularidad, tiendas, ventas_limpias) -> pl.DataFrame:
    """
    Simula día a día el stock de una muestra de artículos en todas las tiendas:
    las ventas reales consumen stock y, cuando baja del mínimo, se pide reposición
    que llega en 1 a 3 días (a veces con retrasos del proveedor, que generan quiebres).
    """
    inicio, fin = a_fecha(cfg["periodo"]["fecha_inicio"]), a_fecha(cfg["periodo"]["fecha_fin"])
    dias = np.arange(inicio, fin + np.timedelta64(1, "D"))
    n_muestra = cfg["inventario"]["articulos_muestra"]

    # Muestra: 3/4 de alta rotación (los que de verdad se agotan) y 1/4 al azar
    top = np.argsort(-popularidad)[: int(n_muestra * 0.75)]
    resto = rng.choice(np.setdiff1d(np.arange(articulos.height), top), n_muestra - len(top), replace=False)
    art_ids = articulos["art_id"].to_numpy()[np.concatenate([top, resto])]
    tienda_ids = tiendas["id_tienda"].to_numpy()

    # Demanda real: unidades vendidas por artículo, tienda y día (matriz series x días)
    pos_art = {a: i for i, a in enumerate(art_ids)}
    pos_tienda = {t: i for i, t in enumerate(tienda_ids)}
    vendidas = (ventas_limpias.filter(pl.col("art_id").is_in(art_ids.tolist()))
                .group_by("art_id", "id_tienda", "fec_trans").agg(pl.col("qty_vendida").sum()))
    S, D = len(art_ids) * len(tienda_ids), len(dias)
    demanda = np.zeros((S, D), dtype=np.int64)
    if vendidas.height:
        fila = (vendidas["art_id"].replace_strict(pos_art).to_numpy() * len(tienda_ids)
                + vendidas["id_tienda"].replace_strict(pos_tienda).to_numpy())
        col = (vendidas["fec_trans"].to_numpy().astype("datetime64[D]") - inicio).astype(int)
        np.add.at(demanda, (fila, col), vendidas["qty_vendida"].to_numpy())

    # Configuración de mínimo y máximo según el consumo promedio de cada serie
    promedio = demanda.mean(axis=1)
    minimo = np.ceil(promedio * 4).astype(np.int64) + 1
    maximo = np.ceil(promedio * 14).astype(np.int64) + 5

    stock = rng.integers(minimo, maximo + 1)
    transito = np.zeros(S, dtype=np.int64)
    llegadas = np.zeros((S, D + 20), dtype=np.int64)
    hist_stock = np.empty((S, D), dtype=np.int64)
    hist_transito = np.empty((S, D), dtype=np.int64)
    hist_reservado = np.empty((S, D), dtype=np.int64)

    for d in range(D):
        # 1. Llega la reposición programada para hoy
        stock += llegadas[:, d]
        transito -= llegadas[:, d]
        # 2. Se vende lo que haya (si no hay stock, la venta se pierde)
        stock -= np.minimum(stock, demanda[:, d])
        # 3. Si stock + tránsito baja del mínimo, se pide hasta el máximo
        pedido = np.where(stock + transito < minimo, maximo - stock - transito, 0)
        con_pedido = np.nonzero(pedido)[0]
        if len(con_pedido):
            demora = rng.integers(1, 4, len(con_pedido))                     # despacho del CD: 1 a 3 días
            retraso = rng.random(len(con_pedido)) < 0.03                    # 3%: el proveedor se atrasa
            demora[retraso] += rng.integers(3, 11, retraso.sum())
            np.add.at(llegadas, (con_pedido, d + demora), pedido[con_pedido])
            transito += pedido
        # 4. Foto de fin de día
        hist_stock[:, d] = stock
        hist_transito[:, d] = transito
        hist_reservado[:, d] = rng.integers(0, stock // 8 + 1)              # apartado para pedidos en línea

    serie_art = np.repeat(art_ids, len(tienda_ids))
    serie_tienda = np.tile(tienda_ids, len(art_ids))
    inventario = pl.DataFrame({
        "art_id": np.repeat(serie_art, D),
        "id_tienda": np.repeat(serie_tienda, D),
        "fec_snapshot": np.tile(dias, S),
        "stock_fisico": hist_stock.ravel(),
        "stock_transito": hist_transito.ravel(),
        "stock_reservado": hist_reservado.ravel(),
        "stock_minimo_config": np.repeat(minimo, D),
        "stock_maximo_config": np.repeat(maximo, D),
    }).sort(["fec_snapshot", "id_tienda", "art_id"])
    inventario = inventario.with_columns(pl.int_range(1, inventario.height + 1, dtype=pl.Int64).alias("id_snapshot"))
    inventario = inventario.select("id_snapshot", pl.exclude("id_snapshot"))
    return poner_nulos(inventario, ["stock_transito", "stock_reservado"], cfg["calidad"]["pct_nulos"], rng)


# ------------------------------------------------------------
# Visitas (tabla adicional)
# ------------------------------------------------------------

def generar_visitas(cfg, rng, tickets: pl.DataFrame, tiendas: pl.DataFrame) -> pl.DataFrame:
    """visitas = tickets / tasa_conversion (con ruido). Las tiendas físicas tienen tráfico todos los días."""
    vis = cfg["visitas"]
    inicio, fin = a_fecha(cfg["periodo"]["fecha_inicio"]), a_fecha(cfg["periodo"]["fecha_fin"])
    dias = np.arange(inicio, fin + np.timedelta64(1, "D"))

    conteo = tickets.group_by("fec_trans", "id_tienda", "canal_venta").agg(pl.len().alias("tickets"))
    # Grilla completa de tienda física: hay gente que entra aunque nadie compre
    grilla = pl.DataFrame({
        "fec_trans": np.repeat(dias, tiendas.height),
        "id_tienda": np.tile(tiendas["id_tienda"].to_numpy(), len(dias)),
        "canal_venta": "tienda_fisica",
    })
    base = (grilla.join(conteo, on=["fec_trans", "id_tienda", "canal_venta"], how="left")
            .vstack(conteo.filter(pl.col("canal_venta") != "tienda_fisica").select(grilla.columns + ["tickets"]))
            .with_columns(pl.col("tickets").fill_null(0))
            # group_by no garantiza orden: se ordena antes de aplicar el ruido aleatorio,
            # para que con la misma semilla el resultado sea idéntico
            .sort(["fec_trans", "id_tienda", "canal_venta"]))

    tasa = base["canal_venta"].replace_strict(vis["tasa_conversion"]).to_numpy()
    tasa = tasa * (1 + rng.uniform(-vis["ruido_pct"], vis["ruido_pct"], base.height))
    tickets_n = base["tickets"].to_numpy()
    visitas = np.where(tickets_n > 0, np.ceil(tickets_n / tasa), rng.poisson(3, base.height)).astype(np.int64)
    visitas = np.maximum(visitas, tickets_n)   # nunca menos visitas que compras

    resultado = pl.DataFrame({
        "fec_visita": base["fec_trans"],
        "id_tienda": base["id_tienda"],
        "canal": base["canal_venta"],
        "num_visitas": visitas,
    }).sort(["fec_visita", "id_tienda", "canal"])
    return resultado.with_columns(pl.int_range(1, resultado.height + 1, dtype=pl.Int64).alias("id_visita")) \
                    .select("id_visita", "fec_visita", "id_tienda", "canal", "num_visitas")


# ------------------------------------------------------------
# Principal
# ------------------------------------------------------------

def guardar(tablas: dict[str, pl.DataFrame], cfg: dict, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, df in tablas.items():
        if nombre in cfg["salida"]["csv"]:
            df.write_csv(carpeta / f"{nombre}.csv")
        elif nombre in cfg["salida"]["parquet"]:
            df.write_parquet(carpeta / f"{nombre}.parquet")
        else:
            raise ValueError(f"La tabla {nombre} no tiene formato de salida en config.yaml")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera los datos sintéticos de RetailMax")
    parser.add_argument("--config", type=Path, default=CARPETA / "config.yaml")
    args = parser.parse_args()

    cfg = cargar_config(args.config)
    rng = np.random.default_rng(cfg["semilla"])
    Faker.seed(cfg["semilla"])
    fake = Faker("es_CO")
    t0 = time.time()

    print("Generando maestros...")
    proveedores = generar_proveedores(cfg, rng, fake)
    articulos, popularidad = generar_articulos(cfg, rng, proveedores)
    tiendas = generar_tiendas(cfg, rng)
    miembros, propension = generar_miembros(cfg, rng)

    print("Generando ventas...")
    ventas_limpias, tickets = generar_ventas(cfg, rng, articulos, popularidad, tiendas, miembros, propension)
    ventas, anomalias = plantar_anomalias_ventas(cfg, rng, ventas_limpias)
    miembros = ajustar_miembros(miembros, ventas_limpias, rng)
    miembros = poner_nulos(miembros, ["rango_edad"], cfg["calidad"]["pct_nulos"], rng)

    print("Generando devoluciones...")
    devoluciones, anomalias_dev = generar_devoluciones(cfg, rng, ventas_limpias)
    anomalias.update(anomalias_dev)

    print("Simulando inventario diario...")
    inventario = generar_inventario(cfg, rng, articulos, popularidad, tiendas, ventas_limpias)

    print("Generando visitas...")
    visitas = generar_visitas(cfg, rng, tickets, tiendas)

    tablas = {
        "MSTR_PROVEEDORES": proveedores,
        "MSTR_ARTICULOS": articulos,
        "MSTR_TIENDAS": tiendas,
        "CRM_MIEMBROS": miembros,
        "TRANS_VENTAS": ventas,
        "INV_STOCK_DIARIO": inventario,
        "POST_DEVOLUCIONES": devoluciones,
        "TRAF_VISITAS": visitas,
    }
    carpeta = CARPETA / cfg["salida"]["carpeta"]
    guardar(tablas, cfg, carpeta)

    conteos = {nombre: df.height for nombre, df in tablas.items()}
    resumen = {
        "generado": dt.datetime.now().isoformat(timespec="seconds"),
        "semilla": cfg["semilla"],
        "periodo": cfg["periodo"],
        "conteos": conteos,
        "anomalias_plantadas": anomalias,
    }
    (carpeta / "resumen_generacion.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nListo en {time.time() - t0:.0f} s. Archivos en {carpeta}\n")
    for nombre, filas in conteos.items():
        minimo = MINIMOS.get(nombre)
        estado = "" if minimo is None else ("OK" if filas >= minimo else f"POR DEBAJO DEL MÍNIMO ({minimo:,})")
        print(f"  {nombre:<20} {filas:>12,}  {estado}")
    print("\nAnomalías plantadas:")
    for clave, valor in anomalias.items():
        print(f"  {clave:<28} {valor}")


if __name__ == "__main__":
    main()

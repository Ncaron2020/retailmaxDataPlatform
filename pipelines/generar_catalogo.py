"""
Genera docs/catalogo_datos.md: cada tabla de Silver y Gold con sus campos, tipo, origen,
descripción y si contiene información sensible (PDF fase 5).

Los tipos y columnas se leen de las tablas reales del lago (así el catálogo no se desactualiza);
las descripciones vienen de los diccionarios de abajo.

    python pipelines/generar_catalogo.py            # usa el lago local
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import polars as pl  # noqa: E402

from comun.config import RAIZ_REPO, cargar_config  # noqa: E402
from comun.lago import Lago  # noqa: E402
from gold.modelo import LINAJE  # noqa: E402

TABLAS = {
    "silver": {
        "proveedores": ("MSTR_PROVEEDORES", "Proveedores (snapshot más reciente), texto normalizado."),
        "articulos": ("MSTR_ARTICULOS", "Catálogo de artículos con precio de lista y jerarquía de categorías."),
        "tiendas": ("MSTR_TIENDAS", "Tiendas con tipo estandarizado y nombre de ciudad y país."),
        "clientes": ("CRM_MIEMBROS", "Miembros del programa de fidelización; id cifrado, género y edad estandarizados."),
        "ventas": ("TRANS_VENTAS", "Líneas de venta sin duplicados, validadas contra artículos y tiendas."),
        "inventario": ("INV_STOCK_DIARIO", "Snapshot diario de stock por artículo y tienda."),
        "devoluciones": ("POST_DEVOLUCIONES", "Devoluciones válidas con motivo legible."),
        "visitas": ("TRAF_VISITAS", "Tráfico diario por tienda y canal (tabla adicional)."),
    },
    "gold": {
        "dim_productos": ("silver.articulos + silver.proveedores", "Dimensión de productos con proveedor, categorías planas y margen estimado."),
        "dim_tiendas": ("silver.tiendas", "Dimensión de tiendas con zona de distribución."),
        "dim_clientes": ("silver.clientes", "Dimensión de clientes con antigüedad; incluye el miembro ANONIMO."),
        "fact_ventas": ("silver.ventas", "Hecho de ventas con valor neto. Particionado por año y mes."),
        "fact_inventario": ("silver.inventario + silver.ventas", "Hecho de inventario con cobertura y alerta de quiebre. Particionado por año y mes."),
        "fact_devoluciones": ("silver.devoluciones + silver.ventas + dim_productos", "Hecho de devoluciones con precio original y tasas."),
        "fact_rfm_clientes": ("fact_ventas", "Score RFM semanal y segmento por cliente activo. Particionado por fecha de corte."),
        "kpi_ventas_diarias": ("fact_ventas + dim_tiendas", "KPIs ejecutivos: ventas netas por país y canal vs. semana anterior. Particionado por año y mes."),
        "kpi_top_articulos": ("fact_ventas + dim_productos", "Top 10 de artículos por categoría y día."),
        "kpi_tasa_devolucion": ("fact_ventas + fact_devoluciones", "Tasa de devolución por mes, categoría nivel 1 y canal."),
        "kpi_conversion_canal": ("fact_ventas + silver.visitas", "Conversión (compras / visitas) y ticket promedio por mes, canal y categoría."),
    },
}

# Columnas con información personal o derivada de ella
SENSIBLES = {
    "id_cliente": "Sí: identificador del cliente cifrado con SHA-256 + salt (seudonimizado)",
    "genero": "Cuasi-identificador",
    "rango_edad": "Cuasi-identificador",
    "id_ciudad": "Cuasi-identificador",
    "fec_registro": "Cuasi-identificador",
}

DESCRIPCIONES = {
    "id_proveedor": "Identificador del proveedor", "razon_social": "Nombre de la empresa proveedora",
    "pais_origen": "País del proveedor", "tiempo_repo_dias": "Días que tarda el proveedor en reponer",
    "calificacion_calidad": "Calificación de calidad del proveedor (1 a 5)", "activo": "Registro activo",
    "art_id": "Identificador del artículo", "cod_barra": "Código de barras", "desc_art": "Descripción del artículo",
    "id_categ_n1": "Categoría nivel 1 (macro categoría)", "id_categ_n2": "Categoría nivel 2", "id_categ_n3": "Categoría nivel 3",
    "categoria_n1": "Nombre de la categoría nivel 1", "categoria_n2": "Ruta de categoría nivel 2",
    "categoria_n3": "Ruta de categoría nivel 3", "precio_lista": "Precio de lista (USD)", "peso_kg": "Peso en kilogramos",
    "unid_medida": "Unidad de medida", "fec_alta": "Fecha de alta del artículo",
    "proveedor": "Razón social del proveedor", "proveedor_pais": "País del proveedor",
    "proveedor_calificacion": "Calificación de calidad del proveedor", "proveedor_tiempo_repo_dias": "Tiempo de reposición del proveedor",
    "margen_estimado_pct": "Margen estimado de la categoría (supuesto, ver gold/parametros.py)",
    "margen_estimado_unitario": "Margen estimado por unidad = precio_lista * margen_estimado_pct / 100",
    "id_tienda": "Identificador de la tienda", "nom_tienda": "Nombre de la tienda",
    "tipo_tienda": "Tipo de tienda estandarizado (Hipermercado, Supermercado, Conveniencia)",
    "id_ciudad": "Código de ciudad", "nombre_ciudad": "Nombre de la ciudad", "id_pais": "Código ISO del país",
    "nombre_pais": "Nombre del país", "metros_cuadrados": "Área de la tienda", "fec_apertura": "Fecha de apertura",
    "zona_distribucion": "Centro de distribución que abastece la tienda (supuesto por cercanía)",
    "id_cliente": "Cliente: hash SHA-256 del id_miembro con salt de Key Vault, o 'ANONIMO'",
    "fec_registro": "Fecha de registro en el programa", "genero": "Género estandarizado (M, F, No informado)",
    "rango_edad": "Rango de edad (nulos imputados con la mediana del canal preferido)",
    "ind_rango_edad_imputado": "Indica si el rango de edad fue imputado", "canal_pref": "Canal preferido del cliente",
    "fec_ultima_compra": "Fecha de la última compra (nulo = nunca ha comprado)",
    "antiguedad_dias": "Días desde el registro hasta la fecha de corte",
    "id_trans": "Identificador del ticket", "ind_cliente_anonimo": "Venta sin cliente registrado",
    "fec_trans": "Fecha de la venta", "hra_trans": "Hora de la venta (HH:MM:SS)", "ind_hora_nula": "La hora no fue registrada",
    "qty_vendida": "Unidades vendidas", "precio_unitario_venta": "Precio unitario cobrado (USD)",
    "descuento_aplicado": "Descuento en valor monetario (nulos imputados con 0)",
    "vr_venta_neto": "Valor neto = qty_vendida * precio_unitario_venta - descuento_aplicado",
    "ind_con_descuento": "La línea tuvo descuento", "tipo_pago": "Medio de pago (nulos = no_informado)",
    "canal_venta": "Canal de venta (tienda_fisica, web, app)", "anio": "Año (columna de partición)", "mes": "Mes (columna de partición)",
    "id_snapshot": "Identificador del snapshot", "fec_snapshot": "Fecha del snapshot", "stock_fisico": "Unidades en tienda",
    "stock_transito": "Unidades en camino (nulos imputados con 0)", "stock_reservado": "Unidades reservadas (nulos imputados con 0)",
    "ind_stock_imputado": "Algún valor de stock fue imputado", "stock_minimo_config": "Stock mínimo configurado",
    "stock_maximo_config": "Stock máximo configurado", "unidades_vendidas_dia": "Unidades vendidas ese día",
    "promedio_consumo_14dias": "Promedio de unidades vendidas por día en los últimos 14 días",
    "cobertura_dias": "Días que alcanza el stock = stock_fisico / promedio_consumo_14dias",
    "alerta_quiebre": "Riesgo de quiebre: cobertura < 7 días y ventas en los últimos 14 días",
    "diferencia_vs_minimo": "stock_fisico - stock_minimo_config",
    "id_devolucion": "Identificador de la devolución", "id_trans_origen": "Ticket de la venta devuelta",
    "fec_devolucion": "Fecha de la devolución", "qty_devuelta": "Unidades devueltas", "motivo_cod": "Código de motivo normalizado",
    "motivo_descripcion": "Motivo legible", "canal_devolucion": "Canal de la devolución", "estado_devolucion": "Estado de la devolución",
    "vr_reembolso": "Valor reembolsado (nulo = en revisión)", "ind_reembolso_pendiente": "Reembolso aún no definido",
    "precio_original": "Precio unitario de la venta original", "fec_venta_original": "Fecha de la venta original",
    "canal_venta_original": "Canal de la venta original", "dias_hasta_devolucion": "Días entre la venta y la devolución",
    "mes_devolucion": "Mes de la devolución (AAAA-MM)",
    "tasa_devolucion_articulo_pct": "Unidades devueltas / vendidas del artículo en el mes (%)",
    "tasa_devolucion_categoria_pct": "Unidades devueltas / vendidas de la categoría en el mes (%)",
    "fecha_corte": "Fecha de corte del cálculo (partición)", "recencia_dias": "Días desde la última compra",
    "frecuencia_90d": "Tickets en los últimos 90 días", "monetario_90d": "Valor neto comprado en los últimos 90 días",
    "score_r": "Quintil de recencia (5 = más reciente)", "score_f": "Quintil de frecuencia", "score_m": "Quintil monetario",
    "codigo_rfm": "Código R-F-M", "segmento": "Segmento de negocio (Champions, En riesgo, Leales...)",
    "orden_segmento": "Orden de presentación del segmento (1 = Champions)",
    "fecha": "Fecha", "dia_semana": "Día de la semana", "ventas_netas": "Suma de vr_venta_neto", "tickets": "Número de tickets",
    "unidades": "Unidades vendidas", "ticket_promedio": "ventas_netas / tickets",
    "tasa_descuento_pct": "Descuento total / ventas brutas (%)", "ventas_netas_semana_anterior": "Ventas netas del mismo día de la semana anterior",
    "variacion_vs_semana_anterior_pct": "Variación vs. el mismo día de la semana anterior (%)",
    "posicion": "Posición en el top 10 de la categoría", "unidades_vendidas": "Unidades vendidas en el periodo",
    "unidades_devueltas": "Unidades devueltas en el periodo", "tasa_devolucion_pct": "unidades_devueltas / unidades_vendidas (%)",
    "canal": "Canal (tienda_fisica, web, app)", "categoria": "Categoría nivel 1 o 'TODAS'", "visitas": "Visitas o sesiones",
    "tasa_conversion_pct": "tickets / visitas (%)", "id_visita": "Identificador del registro de tráfico",
    "fec_visita": "Fecha del tráfico", "num_visitas": "Personas (tienda) o sesiones (web/app)",
}


def main() -> None:
    lago = Lago(cargar_config())
    lineas = [
        "# Catálogo de datos — RetailMax",
        "",
        "Tablas de las capas **Silver** y **Gold** del lago (formato Delta). Generado con "
        "`python pipelines/generar_catalogo.py` a partir de las tablas reales.",
        "",
        "**Sensible:** columnas con información personal o cuasi-identificadores. El único identificador "
        "personal (`id_miembro`) se reemplaza en Silver por `id_cliente`, un hash SHA-256 con salt guardado en "
        "Key Vault. El id original solo existe en Bronze, al que el rol Analista no tiene acceso.",
        "",
    ]
    for capa, tablas in TABLAS.items():
        lineas += [f"## Capa {capa.capitalize()}", ""]
        for nombre, (origen, descripcion) in tablas.items():
            esquema = pl.read_delta(lago.uri(capa, nombre)).schema
            lineas += [f"### `{capa}.{nombre}`", "", f"{descripcion}  ", f"**Origen:** {origen}", "",
                       "| Campo | Tipo | Descripción | Sensible |", "|---|---|---|---|"]
            for campo, tipo in esquema.items():
                lineas.append(f"| `{campo}` | {tipo} | {DESCRIPCIONES.get(campo, '')} | {SENSIBLES.get(campo, 'No')} |")
            lineas.append("")

    lineas += ["## Linaje de campos calculados (Gold)", "",
               "| Campo | Origen | Transformación | Propósito |", "|---|---|---|---|"]
    for campo, info in LINAJE.items():
        lineas.append(f"| `{campo}` | {info['origen']} | {info['transformacion']} | {info['proposito']} |")

    destino = RAIZ_REPO / "docs" / "catalogo_datos.md"
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"Catálogo generado: {destino}")


if __name__ == "__main__":
    main()

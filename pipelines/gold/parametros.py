"""
Parámetros de negocio de Gold que NO vienen en los datos de origen.
Son supuestos documentados: si el negocio entrega los valores reales, se cambian aquí
sin tocar la lógica del modelo.
"""

import polars as pl

# Categorías de nivel 1 (las seis macro categorías del PDF) y margen estimado.
# SUPUESTO: el origen no trae costos, así que el margen se estima con un porcentaje
# de referencia por categoría (valores típicos de retail). En producción los define Finanzas.
CATEGORIAS = pl.DataFrame({
    "id_categ_n1": [1, 2, 3, 4, 5, 6],
    "categoria_n1": ["Alimentos y bebidas", "Cuidado personal e higiene", "Hogar y limpieza",
                     "Electrónica y tecnología", "Ropa y calzado básico", "Bebés y maternidad"],
    "margen_estimado_pct": [20.0, 35.0, 30.0, 15.0, 45.0, 30.0],
})

# Zona de distribución: qué centro de distribución (CD) abastece a las tiendas de cada país.
# SUPUESTO: el PDF nombra tres CD (Bogotá, Ciudad de México, Santiago); se asigna el más cercano.
ZONAS_DISTRIBUCION = pl.DataFrame({
    "id_pais": ["CO", "EC", "PE", "MX", "CL"],
    "zona_distribucion": ["CD Bogotá", "CD Bogotá", "CD Bogotá", "CD Ciudad de México", "CD Santiago"],
})

# Segmentos RFM. Orden de presentación (ranking de valor) para los reportes.
ORDEN_SEGMENTOS = {"Champions": 1, "Leales": 2, "Regulares": 3, "Potenciales": 4, "En riesgo": 5, "Perdidos": 6}

"""
Catálogos de referencia que Silver usa para estandarizar y enriquecer.
Son datos del negocio que el sistema de origen no guarda (solo guarda códigos).
"""

import polars as pl

# id_ciudad -> nombre de ciudad y país (el origen solo guarda el id)
CIUDADES = pl.DataFrame({
    "id_ciudad": [101, 102, 103, 104, 105, 201, 202, 203, 204, 301, 302, 303, 401, 402, 403, 501, 502, 503],
    "nombre_ciudad": ["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga",
                      "Ciudad de México", "Guadalajara", "Monterrey", "Puebla",
                      "Santiago", "Valparaíso", "Concepción",
                      "Lima", "Arequipa", "Trujillo",
                      "Quito", "Guayaquil", "Cuenca"],
    "codigo_pais": ["CO"] * 5 + ["MX"] * 4 + ["CL"] * 3 + ["PE"] * 3 + ["EC"] * 3,
})

PAISES = pl.DataFrame({
    "codigo_pais": ["CO", "MX", "CL", "PE", "EC"],
    "nombre_pais": ["Colombia", "México", "Chile", "Perú", "Ecuador"],
})

# Código de motivo de devolución -> descripción legible (PDF: "estandarizar motivo_cod")
MOTIVOS_DEVOLUCION = pl.DataFrame({
    "motivo_cod": ["DEF", "TAL", "ARR", "ERR", "DAN", "NI"],
    "motivo_descripcion": ["Producto defectuoso", "Talla o medida incorrecta", "Arrepentimiento",
                           "Error en el pedido", "Dañado en el envío", "No informado"],
})

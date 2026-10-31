# Catálogo de datos — RetailMax

Tablas de las capas **Silver** y **Gold** del lago (formato Delta). Generado con `python pipelines/generar_catalogo.py` a partir de las tablas reales.

**Sensible:** columnas con información personal o cuasi-identificadores. El único identificador personal (`id_miembro`) se reemplaza en Silver por `id_cliente`, un hash SHA-256 con salt guardado en Key Vault. El id original solo existe en Bronze, al que el rol Analista no tiene acceso.

## Capa Silver

### `silver.proveedores`

Proveedores (snapshot más reciente), texto normalizado.  
**Origen:** MSTR_PROVEEDORES

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_proveedor` | Int64 | Identificador del proveedor | No |
| `razon_social` | String | Nombre de la empresa proveedora | No |
| `pais_origen` | String | País del proveedor | No |
| `tiempo_repo_dias` | Int64 | Días que tarda el proveedor en reponer | No |
| `calificacion_calidad` | Decimal(precision=3, scale=2) | Calificación de calidad del proveedor (1 a 5) | No |
| `activo` | Boolean | Registro activo | No |

### `silver.articulos`

Catálogo de artículos con precio de lista y jerarquía de categorías.  
**Origen:** MSTR_ARTICULOS

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `art_id` | Int64 | Identificador del artículo | No |
| `cod_barra` | String | Código de barras | No |
| `desc_art` | String | Descripción del artículo | No |
| `id_categ_n1` | Int64 | Categoría nivel 1 (macro categoría) | No |
| `id_categ_n2` | Int64 | Categoría nivel 2 | No |
| `id_categ_n3` | Int64 | Categoría nivel 3 | No |
| `id_proveedor` | Int64 | Identificador del proveedor | No |
| `precio_lista` | Decimal(precision=12, scale=2) | Precio de lista (USD) | No |
| `peso_kg` | Decimal(precision=8, scale=3) | Peso en kilogramos | No |
| `unid_medida` | String | Unidad de medida | No |
| `activo` | Boolean | Registro activo | No |
| `fec_alta` | Date | Fecha de alta del artículo | No |

### `silver.tiendas`

Tiendas con tipo estandarizado y nombre de ciudad y país.  
**Origen:** MSTR_TIENDAS

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `nom_tienda` | String | Nombre de la tienda | No |
| `tipo_tienda` | String | Tipo de tienda estandarizado (Hipermercado, Supermercado, Conveniencia) | No |
| `id_ciudad` | Int64 | Código de ciudad | Cuasi-identificador |
| `nombre_ciudad` | String | Nombre de la ciudad | No |
| `id_pais` | String | Código ISO del país | No |
| `nombre_pais` | String | Nombre del país | No |
| `metros_cuadrados` | Decimal(precision=10, scale=2) | Área de la tienda | No |
| `activo` | Boolean | Registro activo | No |
| `fec_apertura` | Date | Fecha de apertura | No |

### `silver.clientes`

Miembros del programa de fidelización; id cifrado, género y edad estandarizados.  
**Origen:** CRM_MIEMBROS

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_cliente` | String | Cliente: hash SHA-256 del id_miembro con salt de Key Vault, o 'ANONIMO' | Sí: identificador del cliente cifrado con SHA-256 + salt (seudonimizado) |
| `fec_registro` | Date | Fecha de registro en el programa | Cuasi-identificador |
| `id_ciudad` | Int64 | Código de ciudad | Cuasi-identificador |
| `genero` | String | Género estandarizado (M, F, No informado) | Cuasi-identificador |
| `rango_edad` | String | Rango de edad (nulos imputados con la mediana del canal preferido) | Cuasi-identificador |
| `ind_rango_edad_imputado` | Boolean | Indica si el rango de edad fue imputado | No |
| `canal_pref` | String | Canal preferido del cliente | No |
| `activo` | Boolean | Registro activo | No |
| `fec_ultima_compra` | Date | Fecha de la última compra (nulo = nunca ha comprado) | No |

### `silver.ventas`

Líneas de venta sin duplicados, validadas contra artículos y tiendas.  
**Origen:** TRANS_VENTAS

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_trans` | Int64 | Identificador del ticket | No |
| `id_cliente` | String | Cliente: hash SHA-256 del id_miembro con salt de Key Vault, o 'ANONIMO' | Sí: identificador del cliente cifrado con SHA-256 + salt (seudonimizado) |
| `ind_cliente_anonimo` | Boolean | Venta sin cliente registrado | No |
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `art_id` | Int64 | Identificador del artículo | No |
| `fec_trans` | Date | Fecha de la venta | No |
| `hra_trans` | String | Hora de la venta (HH:MM:SS) | No |
| `ind_hora_nula` | Boolean | La hora no fue registrada | No |
| `qty_vendida` | Int64 | Unidades vendidas | No |
| `precio_unitario_venta` | Decimal(precision=12, scale=2) | Precio unitario cobrado (USD) | No |
| `descuento_aplicado` | Decimal(precision=12, scale=2) | Descuento en valor monetario (nulos imputados con 0) | No |
| `tipo_pago` | String | Medio de pago (nulos = no_informado) | No |
| `canal_venta` | String | Canal de venta (tienda_fisica, web, app) | No |

### `silver.inventario`

Snapshot diario de stock por artículo y tienda.  
**Origen:** INV_STOCK_DIARIO

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_snapshot` | Int64 | Identificador del snapshot | No |
| `art_id` | Int64 | Identificador del artículo | No |
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `fec_snapshot` | Date | Fecha del snapshot | No |
| `stock_fisico` | Int64 | Unidades en tienda | No |
| `stock_transito` | Int64 | Unidades en camino (nulos imputados con 0) | No |
| `stock_reservado` | Int64 | Unidades reservadas (nulos imputados con 0) | No |
| `ind_stock_imputado` | Boolean | Algún valor de stock fue imputado | No |
| `stock_minimo_config` | Int64 | Stock mínimo configurado | No |
| `stock_maximo_config` | Int64 | Stock máximo configurado | No |

### `silver.devoluciones`

Devoluciones válidas con motivo legible.  
**Origen:** POST_DEVOLUCIONES

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_devolucion` | Int64 | Identificador de la devolución | No |
| `id_trans_origen` | Int64 | Ticket de la venta devuelta | No |
| `art_id` | Int64 | Identificador del artículo | No |
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `fec_devolucion` | Date | Fecha de la devolución | No |
| `qty_devuelta` | Int64 | Unidades devueltas | No |
| `motivo_cod` | String | Código de motivo normalizado | No |
| `motivo_descripcion` | String | Motivo legible | No |
| `canal_devolucion` | String | Canal de la devolución | No |
| `estado_devolucion` | String | Estado de la devolución | No |
| `vr_reembolso` | Decimal(precision=12, scale=2) | Valor reembolsado (nulo = en revisión) | No |
| `ind_reembolso_pendiente` | Boolean | Reembolso aún no definido | No |

### `silver.visitas`

Tráfico diario por tienda y canal (tabla adicional).  
**Origen:** TRAF_VISITAS

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_visita` | Int64 | Identificador del registro de tráfico | No |
| `fec_visita` | Date | Fecha del tráfico | No |
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `canal` | String | Canal (tienda_fisica, web, app) | No |
| `num_visitas` | Int64 | Personas (tienda) o sesiones (web/app) | No |

## Capa Gold

### `gold.dim_productos`

Dimensión de productos con proveedor, categorías planas y margen estimado.  
**Origen:** silver.articulos + silver.proveedores

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `art_id` | Int64 | Identificador del artículo | No |
| `cod_barra` | String | Código de barras | No |
| `desc_art` | String | Descripción del artículo | No |
| `id_categ_n1` | Int64 | Categoría nivel 1 (macro categoría) | No |
| `categoria_n1` | String | Nombre de la categoría nivel 1 | No |
| `id_categ_n2` | Int64 | Categoría nivel 2 | No |
| `categoria_n2` | String | Ruta de categoría nivel 2 | No |
| `id_categ_n3` | Int64 | Categoría nivel 3 | No |
| `categoria_n3` | String | Ruta de categoría nivel 3 | No |
| `id_proveedor` | Int64 | Identificador del proveedor | No |
| `proveedor` | String | Razón social del proveedor | No |
| `proveedor_pais` | String | País del proveedor | No |
| `proveedor_calificacion` | Decimal(precision=3, scale=2) | Calificación de calidad del proveedor | No |
| `proveedor_tiempo_repo_dias` | Int64 | Tiempo de reposición del proveedor | No |
| `precio_lista` | Decimal(precision=12, scale=2) | Precio de lista (USD) | No |
| `margen_estimado_pct` | Float64 | Margen estimado de la categoría (supuesto, ver gold/parametros.py) | No |
| `margen_estimado_unitario` | Float64 | Margen estimado por unidad = precio_lista * margen_estimado_pct / 100 | No |
| `unid_medida` | String | Unidad de medida | No |
| `peso_kg` | Decimal(precision=8, scale=3) | Peso en kilogramos | No |
| `activo` | Boolean | Registro activo | No |
| `fec_alta` | Date | Fecha de alta del artículo | No |

### `gold.dim_tiendas`

Dimensión de tiendas con zona de distribución.  
**Origen:** silver.tiendas

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `nom_tienda` | String | Nombre de la tienda | No |
| `tipo_tienda` | String | Tipo de tienda estandarizado (Hipermercado, Supermercado, Conveniencia) | No |
| `id_ciudad` | Int64 | Código de ciudad | Cuasi-identificador |
| `nombre_ciudad` | String | Nombre de la ciudad | No |
| `id_pais` | String | Código ISO del país | No |
| `nombre_pais` | String | Nombre del país | No |
| `zona_distribucion` | String | Centro de distribución que abastece la tienda (supuesto por cercanía) | No |
| `metros_cuadrados` | Decimal(precision=10, scale=2) | Área de la tienda | No |
| `activo` | Boolean | Registro activo | No |
| `fec_apertura` | Date | Fecha de apertura | No |

### `gold.dim_clientes`

Dimensión de clientes con antigüedad; incluye el miembro ANONIMO.  
**Origen:** silver.clientes

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_cliente` | String | Cliente: hash SHA-256 del id_miembro con salt de Key Vault, o 'ANONIMO' | Sí: identificador del cliente cifrado con SHA-256 + salt (seudonimizado) |
| `fec_registro` | Date | Fecha de registro en el programa | Cuasi-identificador |
| `antiguedad_dias` | Int64 | Días desde el registro hasta la fecha de corte | No |
| `id_ciudad` | Int64 | Código de ciudad | Cuasi-identificador |
| `genero` | String | Género estandarizado (M, F, No informado) | Cuasi-identificador |
| `rango_edad` | String | Rango de edad (nulos imputados con la mediana del canal preferido) | Cuasi-identificador |
| `ind_rango_edad_imputado` | Boolean | Indica si el rango de edad fue imputado | No |
| `canal_pref` | String | Canal preferido del cliente | No |
| `activo` | Boolean | Registro activo | No |
| `fec_ultima_compra` | Date | Fecha de la última compra (nulo = nunca ha comprado) | No |

### `gold.fact_ventas`

Hecho de ventas con valor neto. Particionado por año y mes.  
**Origen:** silver.ventas

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_trans` | Int64 | Identificador del ticket | No |
| `id_cliente` | String | Cliente: hash SHA-256 del id_miembro con salt de Key Vault, o 'ANONIMO' | Sí: identificador del cliente cifrado con SHA-256 + salt (seudonimizado) |
| `ind_cliente_anonimo` | Boolean | Venta sin cliente registrado | No |
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `art_id` | Int64 | Identificador del artículo | No |
| `fec_trans` | Date | Fecha de la venta | No |
| `hra_trans` | String | Hora de la venta (HH:MM:SS) | No |
| `qty_vendida` | Int64 | Unidades vendidas | No |
| `precio_unitario_venta` | Decimal(precision=12, scale=2) | Precio unitario cobrado (USD) | No |
| `descuento_aplicado` | Decimal(precision=12, scale=2) | Descuento en valor monetario (nulos imputados con 0) | No |
| `vr_venta_neto` | Decimal(precision=32, scale=2) | Valor neto = qty_vendida * precio_unitario_venta - descuento_aplicado | No |
| `ind_con_descuento` | Boolean | La línea tuvo descuento | No |
| `tipo_pago` | String | Medio de pago (nulos = no_informado) | No |
| `canal_venta` | String | Canal de venta (tienda_fisica, web, app) | No |
| `anio` | Int64 | Año (columna de partición) | No |
| `mes` | Int64 | Mes (columna de partición) | No |

### `gold.fact_inventario`

Hecho de inventario con cobertura y alerta de quiebre. Particionado por año y mes.  
**Origen:** silver.inventario + silver.ventas

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_snapshot` | Int64 | Identificador del snapshot | No |
| `art_id` | Int64 | Identificador del artículo | No |
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `fec_snapshot` | Date | Fecha del snapshot | No |
| `stock_fisico` | Int64 | Unidades en tienda | No |
| `stock_transito` | Int64 | Unidades en camino (nulos imputados con 0) | No |
| `stock_reservado` | Int64 | Unidades reservadas (nulos imputados con 0) | No |
| `stock_minimo_config` | Int64 | Stock mínimo configurado | No |
| `stock_maximo_config` | Int64 | Stock máximo configurado | No |
| `unidades_vendidas_dia` | Decimal(precision=38, scale=0) | Unidades vendidas ese día | No |
| `promedio_consumo_14dias` | Float64 | Promedio de unidades vendidas por día en los últimos 14 días | No |
| `cobertura_dias` | Float64 | Días que alcanza el stock = stock_fisico / promedio_consumo_14dias | No |
| `alerta_quiebre` | Boolean | Riesgo de quiebre: cobertura < 7 días y ventas en los últimos 14 días | No |
| `diferencia_vs_minimo` | Int64 | stock_fisico - stock_minimo_config | No |
| `anio` | Int64 | Año (columna de partición) | No |
| `mes` | Int64 | Mes (columna de partición) | No |

### `gold.fact_devoluciones`

Hecho de devoluciones con precio original y tasas.  
**Origen:** silver.devoluciones + silver.ventas + dim_productos

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_devolucion` | Int64 | Identificador de la devolución | No |
| `id_trans_origen` | Int64 | Ticket de la venta devuelta | No |
| `art_id` | Int64 | Identificador del artículo | No |
| `id_tienda` | Int64 | Identificador de la tienda | No |
| `fec_devolucion` | Date | Fecha de la devolución | No |
| `qty_devuelta` | Int64 | Unidades devueltas | No |
| `motivo_cod` | String | Código de motivo normalizado | No |
| `motivo_descripcion` | String | Motivo legible | No |
| `canal_devolucion` | String | Canal de la devolución | No |
| `estado_devolucion` | String | Estado de la devolución | No |
| `vr_reembolso` | Decimal(precision=12, scale=2) | Valor reembolsado (nulo = en revisión) | No |
| `ind_reembolso_pendiente` | Boolean | Reembolso aún no definido | No |
| `precio_original` | Decimal(precision=12, scale=2) | Precio unitario de la venta original | No |
| `fec_venta_original` | Date | Fecha de la venta original | No |
| `canal_venta_original` | String | Canal de la venta original | No |
| `dias_hasta_devolucion` | Int64 | Días entre la venta y la devolución | No |
| `id_categ_n1` | Int64 | Categoría nivel 1 (macro categoría) | No |
| `categoria_n1` | String | Nombre de la categoría nivel 1 | No |
| `id_proveedor` | Int64 | Identificador del proveedor | No |
| `proveedor` | String | Razón social del proveedor | No |
| `mes_devolucion` | String | Mes de la devolución (AAAA-MM) | No |
| `tasa_devolucion_articulo_pct` | Float64 | Unidades devueltas / vendidas del artículo en el mes (%) | No |
| `tasa_devolucion_categoria_pct` | Float64 | Unidades devueltas / vendidas de la categoría en el mes (%) | No |

### `gold.fact_rfm_clientes`

Score RFM semanal y segmento por cliente activo. Particionado por fecha de corte.  
**Origen:** fact_ventas

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `id_cliente` | String | Cliente: hash SHA-256 del id_miembro con salt de Key Vault, o 'ANONIMO' | Sí: identificador del cliente cifrado con SHA-256 + salt (seudonimizado) |
| `recencia_dias` | Int64 | Días desde la última compra | No |
| `frecuencia_90d` | Int64 | Tickets en los últimos 90 días | No |
| `monetario_90d` | Decimal(precision=38, scale=2) | Valor neto comprado en los últimos 90 días | No |
| `score_r` | Int64 | Quintil de recencia (5 = más reciente) | No |
| `score_f` | Int64 | Quintil de frecuencia | No |
| `score_m` | Int64 | Quintil monetario | No |
| `codigo_rfm` | String | Código R-F-M | No |
| `segmento` | String | Segmento de negocio (Champions, En riesgo, Leales...) | No |
| `orden_segmento` | Int64 | Orden de presentación del segmento (1 = Champions) | No |
| `fecha_corte` | Date | Fecha de corte del cálculo (partición) | No |

### `gold.kpi_ventas_diarias`

KPIs ejecutivos: ventas netas por país y canal vs. semana anterior. Particionado por año y mes.  
**Origen:** fact_ventas + dim_tiendas

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `fecha` | Date | Fecha | No |
| `dia_semana` | String | Día de la semana | No |
| `id_pais` | String | Código ISO del país | No |
| `nombre_pais` | String | Nombre del país | No |
| `canal_venta` | String | Canal de venta (tienda_fisica, web, app) | No |
| `ventas_netas` | Decimal(precision=38, scale=2) | Suma de vr_venta_neto | No |
| `tickets` | Int64 | Número de tickets | No |
| `unidades` | Decimal(precision=38, scale=0) | Unidades vendidas | No |
| `ticket_promedio` | Float64 | ventas_netas / tickets | No |
| `tasa_descuento_pct` | Float64 | Descuento total / ventas brutas (%) | No |
| `ventas_netas_semana_anterior` | Decimal(precision=38, scale=2) | Ventas netas del mismo día de la semana anterior | No |
| `variacion_vs_semana_anterior_pct` | Float64 | Variación vs. el mismo día de la semana anterior (%) | No |
| `anio` | Int64 | Año (columna de partición) | No |
| `mes` | Int64 | Mes (columna de partición) | No |

### `gold.kpi_top_articulos`

Top 10 de artículos por categoría y día.  
**Origen:** fact_ventas + dim_productos

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `fecha` | Date | Fecha | No |
| `categoria_n1` | String | Nombre de la categoría nivel 1 | No |
| `art_id` | Int64 | Identificador del artículo | No |
| `desc_art` | String | Descripción del artículo | No |
| `ventas_netas` | Decimal(precision=38, scale=2) | Suma de vr_venta_neto | No |
| `unidades` | Decimal(precision=38, scale=0) | Unidades vendidas | No |
| `posicion` | Int64 | Posición en el top 10 de la categoría | No |

### `gold.kpi_tasa_devolucion`

Tasa de devolución por mes, categoría nivel 1 y canal.  
**Origen:** fact_ventas + fact_devoluciones

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `mes` | String | Mes (columna de partición) | No |
| `id_categ_n1` | Int64 | Categoría nivel 1 (macro categoría) | No |
| `categoria_n1` | String | Nombre de la categoría nivel 1 | No |
| `canal_venta` | String | Canal de venta (tienda_fisica, web, app) | No |
| `unidades_vendidas` | Decimal(precision=38, scale=0) | Unidades vendidas en el periodo | No |
| `unidades_devueltas` | Decimal(precision=38, scale=0) | Unidades devueltas en el periodo | No |
| `tasa_devolucion_pct` | Float64 | unidades_devueltas / unidades_vendidas (%) | No |

### `gold.kpi_conversion_canal`

Conversión (compras / visitas) y ticket promedio por mes, canal y categoría.  
**Origen:** fact_ventas + silver.visitas

| Campo | Tipo | Descripción | Sensible |
|---|---|---|---|
| `mes` | String | Mes (columna de partición) | No |
| `canal` | String | Canal (tienda_fisica, web, app) | No |
| `categoria` | String | Categoría nivel 1 o 'TODAS' | No |
| `tickets` | Int64 | Número de tickets | No |
| `visitas` | Decimal(precision=38, scale=0) | Visitas o sesiones | No |
| `tasa_conversion_pct` | Float64 | tickets / visitas (%) | No |
| `ticket_promedio` | Float64 | ventas_netas / tickets | No |

## Linaje de campos calculados (Gold)

| Campo | Origen | Transformación | Propósito |
|---|---|---|---|
| `fact_ventas.vr_venta_neto` | TRANS_VENTAS (qty_vendida, precio_unitario_venta, descuento_aplicado) | qty_vendida * precio_unitario_venta - descuento_aplicado | Valor real de cada línea de venta; base de todos los indicadores de ventas. |
| `fact_inventario.cobertura_dias` | INV_STOCK_DIARIO.stock_fisico + TRANS_VENTAS.qty_vendida (14 días) | stock_fisico / promedio de unidades vendidas por día en los últimos 14 días | Cuántos días alcanza el stock actual al ritmo de venta reciente. |
| `fact_inventario.alerta_quiebre` | fact_inventario.cobertura_dias, promedio_consumo_14dias | cobertura_dias < 7 AND promedio_consumo_14dias > 0 | Referencias en riesgo de agotarse en los próximos 7 días (Supply Chain). |
| `fact_rfm_clientes.segmento` | TRANS_VENTAS + CRM_MIEMBROS (vía fact_ventas y dim_clientes) | R, F y M en 90 días -> quintiles 1 a 5 sobre clientes activos (180 días) -> reglas de segmento | Segmentación semanal de clientes para campañas de Marketing. |
| `kpi_tasa_devolucion.tasa_devolucion_pct` | POST_DEVOLUCIONES.qty_devuelta + TRANS_VENTAS.qty_vendida | SUM(unidades devueltas) / SUM(unidades vendidas) * 100 por mes, categoría nivel 1 y canal | Tasa oficial de devolución (regla de negocio del PDF). |

## Problematica 

RetailMax no tiene visibilidad oportuna de su operación. El inventario se revisa a mano (hasta 48 h sin visibilidad), las campañas de marketing segmentan mal y las devoluciones no tienen análisis de causas.

## Objetivo
Se plantea diseñar un pipeline automatico y diario que consolido los sistemas de origen y asi entregue informacion confiable para cada área

| Necesidad del negocio | Área | Tabla Gold que la responde |
|---|---|---|
| Referencias en riesgo de quiebre en 7 días | Supply Chain | `fact_inventario` (`alerta_quiebre`) |
| Segmentación RFM semanal (≥ 5 grupos) | Marketing | `fact_rfm_clientes` |
| Tasa de conversión y ticket promedio por canal | Comercial | `kpi_conversion_canal` |
| Devoluciones por motivo, categoría, proveedor y canal | Devoluciones | `fact_devoluciones` |
| Ventas diarias por país, tienda, canal y categoría | Dirección | `kpi_ventas_diarias` (tabla de KPIs ejecutivos) |



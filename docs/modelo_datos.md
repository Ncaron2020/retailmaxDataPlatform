# Modelo de datos — RetailMax

GitHub dibuja estos diagramas automáticamente (Mermaid).

## 1. Modelo relacional de origen (Azure SQL)

Los maestros tienen llave primaria. Las tablas transaccionales **no tienen PK ni FK**, simulando un
sistema legado: por eso pueden existir duplicados y referencias rotas, que Silver detecta.
Las relaciones del diagrama son **lógicas** (no están declaradas en la base).

```mermaid
erDiagram
    MSTR_PROVEEDORES ||--o{ MSTR_ARTICULOS : "abastece"
    MSTR_ARTICULOS ||--o{ TRANS_VENTAS : "se vende en"
    MSTR_TIENDAS ||--o{ TRANS_VENTAS : "registra"
    CRM_MIEMBROS |o--o{ TRANS_VENTAS : "compra (opcional: anónimo)"
    MSTR_ARTICULOS ||--o{ INV_STOCK_DIARIO : "tiene stock"
    MSTR_TIENDAS ||--o{ INV_STOCK_DIARIO : "guarda"
    TRANS_VENTAS ||--o{ POST_DEVOLUCIONES : "se devuelve"
    MSTR_TIENDAS ||--o{ TRAF_VISITAS : "recibe"

    MSTR_PROVEEDORES {
        int id_proveedor PK
        nvarchar razon_social
        nvarchar pais_origen
        int tiempo_repo_dias
        decimal calificacion_calidad
        bit activo
    }
    MSTR_ARTICULOS {
        int art_id PK
        varchar cod_barra
        nvarchar desc_art
        int id_categ_n1
        int id_categ_n2
        int id_categ_n3
        int id_proveedor FK
        decimal precio_lista
        decimal peso_kg
        varchar unid_medida
        bit activo
        date fec_alta
    }
    MSTR_TIENDAS {
        int id_tienda PK
        nvarchar nom_tienda
        nvarchar tipo_tienda
        int id_ciudad
        varchar id_pais
        decimal metros_cuadrados
        bit activo
        date fec_apertura
    }
    CRM_MIEMBROS {
        int id_miembro PK "PII"
        date fec_registro
        int id_ciudad
        varchar genero
        varchar rango_edad
        varchar canal_pref
        bit activo
        date fec_ultima_compra
    }
    TRANS_VENTAS {
        bigint id_trans
        int id_miembro FK "PII"
        int id_tienda FK
        int art_id FK
        date fec_trans
        time hra_trans
        int qty_vendida
        decimal precio_unitario_venta
        decimal descuento_aplicado
        varchar tipo_pago
        varchar canal_venta
    }
    INV_STOCK_DIARIO {
        bigint id_snapshot
        int art_id FK
        int id_tienda FK
        date fec_snapshot
        int stock_fisico
        int stock_transito
        int stock_reservado
        int stock_minimo_config
        int stock_maximo_config
    }
    POST_DEVOLUCIONES {
        bigint id_devolucion
        bigint id_trans_origen FK
        int art_id FK
        int id_tienda FK
        date fec_devolucion
        int qty_devuelta
        varchar motivo_cod
        varchar canal_devolucion
        varchar estado_devolucion
        decimal vr_reembolso
    }
    TRAF_VISITAS {
        bigint id_visita
        date fec_visita
        int id_tienda FK
        varchar canal
        int num_visitas
    }
```

## 2. Modelo dimensional de Gold (estrella)

Las dimensiones salen de los maestros; los hechos, de las transaccionales. Las tablas `kpi_*` son
agregaciones sobre los hechos para consumo directo en dashboards.

```mermaid
erDiagram
    dim_productos ||--o{ fact_ventas : "art_id"
    dim_tiendas ||--o{ fact_ventas : "id_tienda"
    dim_clientes ||--o{ fact_ventas : "id_cliente"
    dim_productos ||--o{ fact_inventario : "art_id"
    dim_tiendas ||--o{ fact_inventario : "id_tienda"
    dim_productos ||--o{ fact_devoluciones : "art_id"
    dim_tiendas ||--o{ fact_devoluciones : "id_tienda"
    dim_clientes ||--o{ fact_rfm_clientes : "id_cliente"

    dim_productos {
        int art_id PK
        string categoria_n1
        string proveedor
        decimal precio_lista
        double margen_estimado_pct
    }
    dim_tiendas {
        int id_tienda PK
        string tipo_tienda
        string nombre_ciudad
        string nombre_pais
        string zona_distribucion
    }
    dim_clientes {
        string id_cliente PK "hash SHA-256"
        string genero
        string rango_edad
        int antiguedad_dias
    }
    fact_ventas {
        bigint id_trans
        string id_cliente FK
        int id_tienda FK
        int art_id FK
        date fec_trans
        decimal vr_venta_neto
        bool ind_con_descuento
    }
    fact_inventario {
        int art_id FK
        int id_tienda FK
        date fec_snapshot
        int stock_fisico
        double cobertura_dias
        bool alerta_quiebre
    }
    fact_devoluciones {
        bigint id_devolucion
        int art_id FK
        int id_tienda FK
        string motivo_descripcion
        decimal precio_original
        double tasa_devolucion_articulo_pct
    }
    fact_rfm_clientes {
        date fecha_corte
        string id_cliente FK
        int score_r
        int score_f
        int score_m
        string segmento
    }
```

Tablas de agregación (KPIs): `kpi_ventas_diarias` (tabla de KPIs ejecutivos), `kpi_top_articulos`,
`kpi_tasa_devolucion`, `kpi_conversion_canal`. Detalle de cada campo en [catalogo_datos.md](catalogo_datos.md).

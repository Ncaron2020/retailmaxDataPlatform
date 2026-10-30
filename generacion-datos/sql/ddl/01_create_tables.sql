-- Portable: el mismo script corre en SQL Server local (Docker) y en Azure SQL Database.
--   * No usa USE ni CREATE DATABASE (Azure SQL no los permite así). Se ejecuta con -d <base>.
--   * Idempotente: si la tabla ya existe, no hace nada.
--
-- Decisión de diseño:
--   Los maestros (MSTR_*, CRM_MIEMBROS) tienen llave primaria.
--   Las tablas transaccionales (TRANS_VENTAS, INV_STOCK_DIARIO, POST_DEVOLUCIONES) NO tienen
--   llaves primarias ni foráneas, simulando un sistema legado sin restricciones. Así pueden
--   existir las anomalías intencionales (duplicados, referencias huérfanas) que el pipeline
--   debe detectar en Silver.

-- ============================================================
-- Maestros
-- ============================================================

IF OBJECT_ID(N'dbo.MSTR_PROVEEDORES', N'U') IS NULL
CREATE TABLE dbo.MSTR_PROVEEDORES (
    id_proveedor          INT            NOT NULL,
    razon_social          NVARCHAR(200)  NULL,
    pais_origen           NVARCHAR(50)   NULL,
    tiempo_repo_dias      INT            NULL,
    calificacion_calidad  DECIMAL(3,2)   NULL,   -- escala 1.00 a 5.00
    activo                BIT            NULL,
    CONSTRAINT PK_MSTR_PROVEEDORES PRIMARY KEY (id_proveedor)
);
GO

IF OBJECT_ID(N'dbo.MSTR_ARTICULOS', N'U') IS NULL
CREATE TABLE dbo.MSTR_ARTICULOS (
    art_id         INT            NOT NULL,
    cod_barra      VARCHAR(20)    NULL,
    desc_art       NVARCHAR(200)  NULL,
    id_categ_n1    INT            NULL,
    id_categ_n2    INT            NULL,
    id_categ_n3    INT            NULL,
    id_proveedor   INT            NULL,
    precio_lista   DECIMAL(12,2)  NULL,
    peso_kg        DECIMAL(8,3)   NULL,
    unid_medida    VARCHAR(10)    NULL,
    activo         BIT            NULL,
    fec_alta       DATE           NULL,
    CONSTRAINT PK_MSTR_ARTICULOS PRIMARY KEY (art_id)
);
GO

IF OBJECT_ID(N'dbo.MSTR_TIENDAS', N'U') IS NULL
CREATE TABLE dbo.MSTR_TIENDAS (
    id_tienda         INT            NOT NULL,
    nom_tienda        NVARCHAR(150)  NULL,
    tipo_tienda       NVARCHAR(50)   NULL,   -- valores "sucios" a propósito
    id_ciudad         INT            NULL,
    id_pais           VARCHAR(3)     NULL,   -- código ISO: CO, MX, CL, PE, EC
    metros_cuadrados  DECIMAL(10,2)  NULL,
    activo            BIT            NULL,
    fec_apertura      DATE           NULL,
    CONSTRAINT PK_MSTR_TIENDAS PRIMARY KEY (id_tienda)
);
GO

IF OBJECT_ID(N'dbo.CRM_MIEMBROS', N'U') IS NULL
CREATE TABLE dbo.CRM_MIEMBROS (
    id_miembro         INT           NOT NULL,
    fec_registro       DATE          NULL,
    id_ciudad          INT           NULL,
    genero             VARCHAR(20)   NULL,   -- valores "sucios": M, F, Masculino, fem, NULL...
    rango_edad         VARCHAR(10)   NULL,   -- ej. 18-24, 25-34
    canal_pref         VARCHAR(30)   NULL,
    activo             BIT           NULL,
    fec_ultima_compra  DATE          NULL,
    CONSTRAINT PK_CRM_MIEMBROS PRIMARY KEY (id_miembro)
);
GO

-- ============================================================
-- Transaccionales (sin PK/FK: sistema legado)
-- ============================================================

IF OBJECT_ID(N'dbo.TRANS_VENTAS', N'U') IS NULL
CREATE TABLE dbo.TRANS_VENTAS (
    id_trans               BIGINT         NULL,   -- una transacción puede tener varias líneas (art_id)
    id_miembro             INT            NULL,   -- NULL = cliente anónimo
    id_tienda              INT            NULL,
    art_id                 INT            NULL,
    fec_trans              DATE           NULL,
    hra_trans              TIME(0)        NULL,
    qty_vendida            INT            NULL,
    precio_unitario_venta  DECIMAL(12,2)  NULL,
    descuento_aplicado     DECIMAL(12,2)  NULL,   -- supuesto: valor monetario, no porcentaje
    tipo_pago              VARCHAR(30)    NULL,
    canal_venta            VARCHAR(30)    NULL
);
GO

IF OBJECT_ID(N'dbo.INV_STOCK_DIARIO', N'U') IS NULL
CREATE TABLE dbo.INV_STOCK_DIARIO (
    id_snapshot          BIGINT  NULL,
    art_id               INT     NULL,
    id_tienda            INT     NULL,
    fec_snapshot         DATE    NULL,
    stock_fisico         INT     NULL,
    stock_transito       INT     NULL,
    stock_reservado      INT     NULL,
    stock_minimo_config  INT     NULL,
    stock_maximo_config  INT     NULL
);
GO

IF OBJECT_ID(N'dbo.POST_DEVOLUCIONES', N'U') IS NULL
CREATE TABLE dbo.POST_DEVOLUCIONES (
    id_devolucion       BIGINT         NULL,
    id_trans_origen     BIGINT         NULL,
    art_id              INT            NULL,
    id_tienda           INT            NULL,
    fec_devolucion      DATE           NULL,
    qty_devuelta        INT            NULL,
    motivo_cod          VARCHAR(10)    NULL,
    canal_devolucion    VARCHAR(30)    NULL,
    estado_devolucion   VARCHAR(30)    NULL,
    vr_reembolso        DECIMAL(12,2)  NULL
);
GO

-- Tabla adicional (no incluida en el PDF): tráfico de visitas por día, tienda y canal.
-- Necesaria para calcular la tasa de conversión (compradores / visitantes).
IF OBJECT_ID(N'dbo.TRAF_VISITAS', N'U') IS NULL
CREATE TABLE dbo.TRAF_VISITAS (
    id_visita     BIGINT       NULL,
    fec_visita    DATE         NULL,
    id_tienda     INT          NULL,   -- en web/app: tienda que atiende el pedido
    canal         VARCHAR(30)  NULL,   -- tienda_fisica, web, app
    num_visitas   INT          NULL    -- personas en tienda o sesiones digitales
);
GO


IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_TRANS_VENTAS_fec_trans')
    CREATE NONCLUSTERED INDEX IX_TRANS_VENTAS_fec_trans ON dbo.TRANS_VENTAS (fec_trans);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_INV_STOCK_DIARIO_fec_snapshot')
    CREATE NONCLUSTERED INDEX IX_INV_STOCK_DIARIO_fec_snapshot ON dbo.INV_STOCK_DIARIO (fec_snapshot);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_POST_DEVOLUCIONES_fec_devolucion')
    CREATE NONCLUSTERED INDEX IX_POST_DEVOLUCIONES_fec_devolucion ON dbo.POST_DEVOLUCIONES (fec_devolucion);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_TRAF_VISITAS_fec_visita')
    CREATE NONCLUSTERED INDEX IX_TRAF_VISITAS_fec_visita ON dbo.TRAF_VISITAS (fec_visita);
GO

PRINT 'Tablas de origen listas.';
GO

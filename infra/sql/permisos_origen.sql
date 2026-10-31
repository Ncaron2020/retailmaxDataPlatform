-- Acceso de solo lectura a la base de origen para una identidad administrada de Azure
-- (Data Factory o la Function App). Se ejecuta una vez por identidad, después de terraform apply.
--
-- La identidad se autentica con Entra ID: no hay usuario ni contraseña de SQL.
-- Solo lectura (db_datareader): el pipeline nunca modifica el sistema fuente.
--
-- Uso:
--   python generacion-datos/load.py --target azure --sin-carga \
--     --sql ../infra/sql/permisos_origen.sql --var IDENTIDAD=<nombre del recurso>

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(IDENTIDAD)')
    CREATE USER [$(IDENTIDAD)] FROM EXTERNAL PROVIDER;
GO

ALTER ROLE db_datareader ADD MEMBER [$(IDENTIDAD)];
GO

PRINT '$(IDENTIDAD) tiene acceso de solo lectura a la base de origen.';
GO

-- Acceso de Data Factory a la base de origen (se ejecuta una vez, después de terraform apply).
--
-- Data Factory se autentica con su identidad administrada: no hay usuario ni contraseña.
-- Solo lectura (db_datareader): el pipeline nunca modifica el sistema fuente.
--
-- Uso:
--   python generacion-datos/load.py --target azure --sin-carga \
--     --sql ../infra/sql/permisos_origen.sql --var ADF_NOMBRE=<output data_factory>

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(ADF_NOMBRE)')
    CREATE USER [$(ADF_NOMBRE)] FROM EXTERNAL PROVIDER;
GO

ALTER ROLE db_datareader ADD MEMBER [$(ADF_NOMBRE)];
GO

PRINT 'Data Factory tiene acceso de solo lectura a la base de origen.';
GO

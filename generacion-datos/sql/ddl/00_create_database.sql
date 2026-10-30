-- Crea la base de datos de origen.

IF DB_ID(N'$(DB_NAME)') IS NULL
BEGIN
    CREATE DATABASE [$(DB_NAME)];
    PRINT 'Base de datos $(DB_NAME) creada.';
END
ELSE
    PRINT 'Base de datos $(DB_NAME) ya existe. Sin cambios.';
GO

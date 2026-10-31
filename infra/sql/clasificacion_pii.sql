-- Clasificación de datos personales (PII) en las tablas de origen (PDF fase 5:
-- "identificar y etiquetar todas las columnas que contengan información de identificación personal").
--
-- Usa la clasificación de sensibilidad nativa de SQL Server / Azure SQL: las etiquetas quedan en la
-- base, aparecen en el portal (Data Discovery & Classification) y en los registros de auditoría.
--
-- Uso:
--   python generacion-datos/load.py --target azure --sin-carga --sql ../infra/sql/clasificacion_pii.sql

-- Identificador directo del cliente: permite llegar a la persona en el CRM. Se cifra (hash) en Silver.
ADD SENSITIVITY CLASSIFICATION TO dbo.CRM_MIEMBROS.id_miembro
    WITH (LABEL = 'Confidential', INFORMATION_TYPE = 'Name', RANK = HIGH);
GO
ADD SENSITIVITY CLASSIFICATION TO dbo.TRANS_VENTAS.id_miembro
    WITH (LABEL = 'Confidential', INFORMATION_TYPE = 'Name', RANK = HIGH);
GO

-- Cuasi-identificadores: por sí solos no identifican, combinados podrían ayudar a hacerlo.
ADD SENSITIVITY CLASSIFICATION TO dbo.CRM_MIEMBROS.genero
    WITH (LABEL = 'General', INFORMATION_TYPE = 'Other', RANK = LOW);
GO
ADD SENSITIVITY CLASSIFICATION TO dbo.CRM_MIEMBROS.rango_edad
    WITH (LABEL = 'General', INFORMATION_TYPE = 'Date Of Birth', RANK = MEDIUM);
GO
ADD SENSITIVITY CLASSIFICATION TO dbo.CRM_MIEMBROS.id_ciudad
    WITH (LABEL = 'General', INFORMATION_TYPE = 'Contact Info', RANK = LOW);
GO
ADD SENSITIVITY CLASSIFICATION TO dbo.CRM_MIEMBROS.fec_registro
    WITH (LABEL = 'General', INFORMATION_TYPE = 'Other', RANK = LOW);
GO

PRINT 'Clasificación de PII aplicada.';
GO

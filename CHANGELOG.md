# CHANGELOG

Historial de cambios significativos del proyecto. Formato: fecha, autor y descripción.

## 2026-10-30 — Nicolás Caro

### Despliegue continuo, ajustes de operación y evidencias (tarde)
- Despliegue del código con GitHub Actions y OIDC: identidad `gh-retailmax-deploy-dev` sin contraseña,
  con permiso solo sobre la Function App (Website Contributor). En GitHub solo se guardan identificadores.
- Corrección del empaquetado: un zip creado con `Compress-Archive` (PowerShell 5.1) guarda rutas con `\`
  y la Function quedaba sin funciones aunque el despliegue respondía OK. Se empaqueta con rutas `/` y se
  verifica con `az functionapp function list` después de desplegar.
- Bronze carga solo días cerrados: `fecha > marca AND fecha < fecha_corte`, por defecto hoy en Bogotá.
  Nuevo parámetro `fecha_corte` en el pipeline de Data Factory (y `--fecha-corte` en local) para
  ejecuciones manuales. Evita perder ventas de un día cargado a medias por una ejecución manual.
- La prueba de calidad `volumen_ultimo_dia` pasa de error a advertencia: una caída de ventas puede ser
  real (festivo, tienda cerrada) y no debe detener el pipeline.
- Grupo de administradores con Contributor en lugar de Owner: el Owner de la suscripción tiene una
  condición que impide delegar roles privilegiados; los permisos solo se otorgan con Terraform.
- CI ejecutado sobre las ramas `develop` y `main`.
- Evidencias en `docs/evidencias` (gobierno, orquestación, correos y alertas), `infra/README.md` con el
  despliegue paso a paso y `docs/arquitectura.md` actualizado al estado final.

### Orquestación, notificaciones y gobierno
- Pipeline de Data Factory `pl_retailmax_medallon` definido como código en `/orchestration` y desplegado
  con Terraform: Despertar_BD → Bronze → Silver → Gold → Calidad → Notificación, con dependencias
  explícitas, 3 reintentos por tarea, tiempo máximo por tarea y trigger diario a las 02:00 (hora de Bogotá).
- Reintentos con backoff exponencial dentro del código (5, 10, 20 s) y para la conexión a la base
  serverless pausada (10, 20, 40, 80 s).
- Alerta de anomalía de volumen en Bronze: diferencia mayor a 30 % frente al promedio de las últimas
  7 ejecuciones, enviada antes de continuar el pipeline.
- Correos de reporte diario y de fallo con Azure Communication Services (identidad administrada) y
  alerta de Azure Monitor sobre ejecuciones fallidas de Data Factory.
- Seis pruebas automatizadas de calidad sobre Gold (unicidad, completitud, integridad referencial,
  rangos, volumen y reglas RFM), con reporte en `ops/calidad_pruebas`.
- Roles de Entra ID (administradores, ingenieros de datos, analistas) con permisos por contenedor,
  auditoría de SQL hacia Log Analytics y clasificación de PII en la base de origen.
- Catálogo de datos (`docs/catalogo_datos.md`) y modelo de datos ER (`docs/modelo_datos.md`).

### Ejecución en Azure
- Function App (Flex Consumption, Python 3.12) que ejecuta Bronze, Silver y Gold en la nube con el
  mismo código del ambiente local. Clave de la Function guardada en Key Vault para Data Factory.
- Corrección: el runtime fallaba con "AuthenticationFailed" porque el proveedor de Terraform agrega
  cadenas de conexión con clave; se eliminan automáticamente para usar solo la identidad administrada.
- Corrección: reintentos y tiempo de espera para la base de datos serverless pausada.

### Pipeline medallón
- Capa Bronze: ingesta incremental con marca de agua, columnas de auditoría, partición año/mes/día,
  bitácora de ejecuciones y tabla de errores. Verificador de requisitos (`pipelines/verificar_bronze.py`).
- Capa Silver: duplicados, rechazos con motivo (integridad referencial y campos obligatorios),
  estrategia de nulos documentada, estandarización, hash SHA-256 de PII y reporte de calidad.
- Capa Gold: modelo dimensional (3 dimensiones, 4 hechos), 4 tablas de KPIs, reglas de negocio de
  RetailMax (quiebre de stock, RFM, tasa de devolución, conversión, dashboard ejecutivo), particiones
  y linaje documentado.

### Infraestructura y datos
- Terraform del ambiente dev: lago ADLS Gen2 (bronze, silver, gold, ops), Key Vault, Azure SQL con la
  oferta gratuita (vía `azapi`), Data Factory, Log Analytics y permisos con identidades administradas.
- Azure SQL desplegado en Central US: South Central US está restringido para suscripciones de prueba.
- Generador de datos sintéticos reproducible (semilla) con volúmenes mínimos del PDF, anomalías
  plantadas y tabla adicional de visitas; cargador hacia SQL Server local y Azure SQL.

## 2026-10-29 — Nicolás Caro
- README inicial con la problemática y el mapeo de necesidades del negocio a tablas Gold.
- Ambiente local con SQL Server 2022 en Docker (puerto solo en 127.0.0.1) y DDL portable.

## 2026-10-28 — Nicolás Caro
- Creación del repositorio, diseño de la arquitectura por capas y decisión de plataforma
  (ADR-001: Fabric y Databricks no disponibles en la suscripción de prueba).

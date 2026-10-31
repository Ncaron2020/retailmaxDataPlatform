# Orquestación en Data Factory: conexiones (linked services), pipeline y programación diaria.
# La definición del pipeline (las actividades) vive en /orchestration, versionada como código.

# --- Clave de la Function, guardada en Key Vault ---
# Data Factory necesita la clave para llamar a la Function. Terraform la lee y la guarda
# directamente en Key Vault: nadie la ve y no aparece en el código.
data "azurerm_function_app_host_keys" "pipeline" {
  name                = azurerm_function_app_flex_consumption.pipeline.name
  resource_group_name = azurerm_resource_group.principal.name
}

resource "azurerm_key_vault_secret" "clave_funcion" {
  name         = "funcion-pipeline-clave"
  value        = data.azurerm_function_app_host_keys.pipeline.default_function_key
  key_vault_id = azurerm_key_vault.secretos.id

  depends_on = [azurerm_role_assignment.terraform_secretos]
}

# --- Conexiones (linked services) ---

resource "azurerm_data_factory_linked_service_key_vault" "secretos" {
  name            = "ls_key_vault"
  data_factory_id = azurerm_data_factory.orquestador.id
  key_vault_id    = azurerm_key_vault.secretos.id
}

# Base de origen, autenticada con la identidad administrada de Data Factory (solo lectura)
resource "azurerm_data_factory_linked_service_azure_sql_database" "origen" {
  name                 = "ls_sql_origen"
  data_factory_id      = azurerm_data_factory.orquestador.id
  use_managed_identity = true
  connection_string = join(";", [
    "Data Source=tcp:${azurerm_mssql_server.origen.fully_qualified_domain_name},1433",
    "Initial Catalog=${azapi_resource.bd_origen.name}",
    "Encrypt=True",
    "Connection Timeout=120",
  ])
}

resource "azurerm_data_factory_linked_service_azure_function" "pipeline" {
  name            = "ls_funcion_pipeline"
  data_factory_id = azurerm_data_factory.orquestador.id
  url             = "https://${azurerm_function_app_flex_consumption.pipeline.default_hostname}"

  key_vault_key {
    linked_service_name = azurerm_data_factory_linked_service_key_vault.secretos.name
    secret_name         = azurerm_key_vault_secret.clave_funcion.name
  }
}

# --- Pipeline ---

resource "azurerm_data_factory_pipeline" "retailmax" {
  name            = "pl_retailmax_medallon"
  data_factory_id = azurerm_data_factory.orquestador.id
  description     = "Pipeline diario RetailMax: Bronze -> Silver -> Gold -> Calidad -> Notificación."
  concurrency     = 1 # nunca dos ejecuciones al mismo tiempo sobre el mismo lago

  # tablas_bronze: vacío = todas. Permite ejecuciones de prueba, por ejemplo forzar un fallo
  # con ["TABLA_INEXISTENTE"] para verificar la alerta de fallo.
  # fecha_corte: vacío = hoy (se cargan solo días cerrados). En una ejecución manual se puede
  # pasar AAAA-MM-DD, por ejemplo en dev para cargar días simulados.
  parameters = {
    tablas_bronze = ""
    fecha_corte   = ""
  }

  activities_json = templatefile("${path.module}/../orchestration/pipeline_retailmax.json.tftpl", {
    ls_sql     = azurerm_data_factory_linked_service_azure_sql_database.origen.name
    ls_funcion = azurerm_data_factory_linked_service_azure_function.pipeline.name
  })
}

# --- Programación diaria (02:00, hora de Bogotá) ---

resource "azurerm_data_factory_trigger_schedule" "diario" {
  name            = "tr_diario"
  data_factory_id = azurerm_data_factory.orquestador.id
  pipeline_name   = azurerm_data_factory_pipeline.retailmax.name
  description     = "Ejecución diaria del pipeline RetailMax."
  frequency       = "Day"
  interval        = 1
  time_zone       = "SA Pacific Standard Time" # Bogotá (UTC-5)
  start_time      = "2026-10-30T00:00:00Z"
  activated       = true

  schedule {
    hours   = [var.adf_hora_ejecucion]
    minutes = [var.adf_minuto_ejecucion]
  }
}

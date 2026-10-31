# Function App que ejecuta las capas Bronze, Silver y Gold (código en /pipelines).
# Plan Flex Consumption: serverless, se paga solo por el tiempo de ejecución.

# Almacenamiento interno de la Function (paquete del código y estado del runtime).
# Separado del lago: el lago es solo para datos.
resource "azurerm_storage_account" "funcion" {
  name                            = local.nombres.storage_fn
  resource_group_name             = azurerm_resource_group.principal.name
  location                        = azurerm_resource_group.principal.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false # también sin claves: la Function entra con su identidad
  tags                            = local.etiquetas
}

resource "azurerm_storage_container" "despliegues" {
  name                  = "despliegues"
  storage_account_id    = azurerm_storage_account.funcion.id
  container_access_type = "private"

  depends_on = [azurerm_role_assignment.terraform_storage_funcion]
}

# Application Insights: logs y trazas de cada ejecución, guardados en Log Analytics
resource "azurerm_application_insights" "funcion" {
  name                = local.nombres.app_insights
  resource_group_name = azurerm_resource_group.principal.name
  location            = azurerm_resource_group.principal.location
  workspace_id        = azurerm_log_analytics_workspace.logs.id
  application_type    = "other"
  tags                = local.etiquetas
}

resource "azurerm_service_plan" "funcion" {
  name                = local.nombres.plan_fn
  resource_group_name = azurerm_resource_group.principal.name
  location            = azurerm_resource_group.principal.location
  os_type             = "Linux"
  sku_name            = "FC1" # Flex Consumption
  tags                = local.etiquetas
}

resource "azurerm_function_app_flex_consumption" "pipeline" {
  name                = local.nombres.function_app
  resource_group_name = azurerm_resource_group.principal.name
  location            = azurerm_resource_group.principal.location
  service_plan_id     = azurerm_service_plan.funcion.id

  runtime_name           = "python"
  runtime_version        = "3.12"
  instance_memory_in_mb  = 2048 # el procesamiento de 1 M de filas en memoria necesita más que el mínimo
  maximum_instance_count = 40

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.funcion.primary_blob_endpoint}${azurerm_storage_container.despliegues.name}"
  storage_authentication_type = "SystemAssignedIdentity"

  identity {
    type = "SystemAssigned"
  }

  # Variables de entorno: hacen que el MISMO código de /pipelines se conecte a Azure
  app_settings = {
    RETAILMAX_ENTORNO                = "azure"
    AZURE_SQL_SERVER                 = azurerm_mssql_server.origen.fully_qualified_domain_name
    AZURE_SQL_DATABASE               = azapi_resource.bd_origen.name
    LAGO_CUENTA                      = azurerm_storage_account.lago.name
    KEY_VAULT_URL                    = azurerm_key_vault.secretos.vault_uri
    AzureWebJobsStorage__accountName = azurerm_storage_account.funcion.name
    AzureWebJobsStorage__credential  = "managedidentity"
    # Correo de notificaciones (Azure Communication Services, autenticado con la identidad)
    ACS_ENDPOINT     = "https://${azurerm_communication_service.comunicacion.hostname}"
    CORREO_REMITENTE = "DoNotReply@${azurerm_email_communication_service_domain.azure.mail_from_sender_domain}"
    CORREO_ALERTAS   = var.correo_alertas
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.funcion.connection_string
    minimum_tls_version                    = "1.2"
  }

  https_only = true
  tags       = local.etiquetas
}

# El proveedor azurerm agrega por su cuenta "AzureWebJobsStorage" y "DEPLOYMENT_STORAGE_CONNECTION_STRING"
# (cadenas de conexión con clave) en cada actualización de la Function. Como el Storage tiene las claves
# desactivadas, el runtime falla con "AuthenticationFailed" si existen: deben quedar solo las variables
# por identidad (AzureWebJobsStorage__accountName/__credential). Este paso las elimina después de cada cambio.
resource "terraform_data" "config_storage_por_identidad" {
  triggers_replace = [sha1(jsonencode(azurerm_function_app_flex_consumption.pipeline.app_settings))]

  provisioner "local-exec" {
    command = "az functionapp config appsettings delete -g ${azurerm_resource_group.principal.name} -n ${azurerm_function_app_flex_consumption.pipeline.name} --setting-names AzureWebJobsStorage DEPLOYMENT_STORAGE_CONNECTION_STRING -o none"
  }
}

# Log Analytics: destino central de logs y auditoría de toda la plataforma.
resource "azurerm_log_analytics_workspace" "logs" {
  name                = local.nombres.log_analytics
  resource_group_name = azurerm_resource_group.principal.name
  location            = azurerm_resource_group.principal.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retencion_logs_dias
  tags                = local.etiquetas
}

# Historial de ejecuciones de Data Factory (pipelines, actividades y triggers).
resource "azurerm_monitor_diagnostic_setting" "data_factory" {
  name                           = "diag-adf"
  target_resource_id             = azurerm_data_factory.orquestador.id
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.logs.id
  log_analytics_destination_type = "Dedicated"

  enabled_log { category = "PipelineRuns" }
  enabled_log { category = "ActivityRuns" }
  enabled_log { category = "TriggerRuns" }
  enabled_metric { category = "AllMetrics" }
}

# Auditoría del Data Lake: quién leyó, escribió o borró cada archivo.
resource "azurerm_monitor_diagnostic_setting" "lago_blobs" {
  name                       = "diag-lago-auditoria"
  target_resource_id         = "${azurerm_storage_account.lago.id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log { category = "StorageRead" }
  enabled_log { category = "StorageWrite" }
  enabled_log { category = "StorageDelete" }
}

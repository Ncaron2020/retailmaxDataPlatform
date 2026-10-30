# Nombres y URLs de los recursos creados, para que los usen los scripts del pipeline.

output "grupo_recursos" {
  value = azurerm_resource_group.principal.name
}

output "storage_lago" {
  value = azurerm_storage_account.lago.name
}

output "lago_url_dfs" {
  description = "Endpoint ADLS Gen2 (abfss://<contenedor>@<cuenta>.dfs.core.windows.net)"
  value       = azurerm_storage_account.lago.primary_dfs_endpoint
}

output "key_vault" {
  value = azurerm_key_vault.secretos.name
}

output "key_vault_url" {
  value = azurerm_key_vault.secretos.vault_uri
}

output "sql_server_fqdn" {
  description = "Usar como AZURE_SQL_SERVER en load.py"
  value       = azurerm_mssql_server.origen.fully_qualified_domain_name
}

output "sql_database" {
  description = "Usar como AZURE_SQL_DATABASE en load.py"
  value       = azapi_resource.bd_origen.name
}

output "data_factory" {
  value = azurerm_data_factory.orquestador.name
}

output "data_factory_identidad" {
  description = "Principal de Data Factory (para darle acceso de lectura en SQL)"
  value       = azurerm_data_factory.orquestador.identity[0].principal_id
}

output "log_analytics" {
  value = azurerm_log_analytics_workspace.logs.name
}

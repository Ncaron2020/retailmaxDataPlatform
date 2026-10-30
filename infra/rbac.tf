# Permisos (RBAC). Cada asignación = quién + qué rol + sobre qué recurso.

# --- Identidad que ejecuta Terraform (tu usuario o GitHub Actions) ---

# Crear contenedores y revisar archivos del lago con Entra ID
resource "azurerm_role_assignment" "terraform_datos_lago" {
  scope                = azurerm_storage_account.lago.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = data.azurerm_client_config.actual.object_id
}

# Escribir el secreto del salt en el Key Vault
resource "azurerm_role_assignment" "terraform_secretos" {
  scope                = azurerm_key_vault.secretos.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.actual.object_id
}

# --- Data Factory ---

# Escribe la copia cruda en bronze y la bitácora en ops (solo esos dos contenedores)
resource "azurerm_role_assignment" "adf_escribe" {
  for_each = toset(["bronze", "ops"])

  scope                = azurerm_storage_container.capas[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_data_factory.orquestador.identity[0].principal_id
}

# Lee secretos (ej. para pasarlos a las transformaciones)
resource "azurerm_role_assignment" "adf_secretos" {
  scope                = azurerm_key_vault.secretos.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_data_factory.orquestador.identity[0].principal_id
}

# Nota: el acceso de Data Factory a la base de datos (solo lectura) no es RBAC de Azure,
# sino un usuario dentro de SQL. Se crea con sql/permisos_origen.sql después del despliegue.

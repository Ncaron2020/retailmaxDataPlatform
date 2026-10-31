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

# --- Function App (ejecuta Bronze, Silver y Gold) ---

# Su almacenamiento interno: paquete del código, colas y tablas del runtime
resource "azurerm_role_assignment" "funcion_storage_interno" {
  for_each = toset(["Storage Blob Data Owner", "Storage Queue Data Contributor", "Storage Table Data Contributor"])

  scope                = azurerm_storage_account.funcion.id
  role_definition_name = each.key
  principal_id         = azurerm_function_app_flex_consumption.pipeline.identity[0].principal_id
}

# El lago: lee bronze y escribe bronze, silver, gold y ops (contenedor por contenedor)
resource "azurerm_role_assignment" "funcion_lago" {
  for_each = toset(["bronze", "silver", "gold", "ops"])

  scope                = azurerm_storage_container.capas[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.pipeline.identity[0].principal_id
}

# Lee el salt para el hash de PII
resource "azurerm_role_assignment" "funcion_secretos" {
  scope                = azurerm_key_vault.secretos.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_function_app_flex_consumption.pipeline.identity[0].principal_id
}

# Terraform necesita crear el contenedor de despliegues con Entra ID
resource "azurerm_role_assignment" "terraform_storage_funcion" {
  scope                = azurerm_storage_account.funcion.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = data.azurerm_client_config.actual.object_id
}

# Nota: el acceso a la base de datos (solo lectura) no es RBAC de Azure, sino un usuario
# dentro de SQL. Se crea con sql/permisos_origen.sql para Data Factory y para la Function.

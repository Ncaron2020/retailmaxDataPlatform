# Gobierno: roles de personas, auditoría de accesos a datos.
#
# Tres roles (PDF fase 5), como grupos de Entra ID. Los permisos se dan al GRUPO, no a personas:
# para dar acceso a alguien basta con agregarlo al grupo.
#
#   Administrador     -> control total sobre los recursos del proyecto (Contributor, no Owner)
#   Ingeniero de datos -> lectura y escritura en todas las capas del lago + operar Data Factory
#   Analista          -> solo lectura de la capa Gold (no puede ver Bronze, Silver ni ops)
#
# Por qué Contributor y no Owner: Owner también permite dar permisos a otros. Azure bloquea por defecto
# que se deleguen roles privilegiados (Owner, User Access Administrator) y, además, dejar los permisos
# solo en Terraform es mínimo privilegio: cualquier acceso nuevo pasa por código revisado, no por el portal.

resource "azuread_group" "administradores" {
  display_name     = "grp-retailmax-administradores-${var.ambiente}"
  description      = "RetailMax ${var.ambiente}: control total sobre los recursos del proyecto."
  security_enabled = true
  owners           = [data.azurerm_client_config.actual.object_id]
  members          = [data.azurerm_client_config.actual.object_id]
}

resource "azuread_group" "ingenieros" {
  display_name     = "grp-retailmax-ingenieros-datos-${var.ambiente}"
  description      = "RetailMax ${var.ambiente}: lectura y escritura en todas las capas del lago."
  security_enabled = true
  owners           = [data.azurerm_client_config.actual.object_id]
}

resource "azuread_group" "analistas" {
  display_name     = "grp-retailmax-analistas-${var.ambiente}"
  description      = "RetailMax ${var.ambiente}: solo lectura de la capa Gold."
  security_enabled = true
  owners           = [data.azurerm_client_config.actual.object_id]
}

# --- Administrador: control total ---
resource "azurerm_role_assignment" "admin_grupo_recursos" {
  scope                = azurerm_resource_group.principal.id
  role_definition_name = "Contributor"
  principal_id         = azuread_group.administradores.object_id
}

resource "azurerm_role_assignment" "admin_datos_lago" {
  scope                = azurerm_storage_account.lago.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azuread_group.administradores.object_id
}

resource "azurerm_role_assignment" "admin_secretos" {
  scope                = azurerm_key_vault.secretos.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = azuread_group.administradores.object_id
}

# --- Ingeniero de datos: todas las capas + operar el orquestador ---
resource "azurerm_role_assignment" "ingeniero_lectura_recursos" {
  scope                = azurerm_resource_group.principal.id
  role_definition_name = "Reader"
  principal_id         = azuread_group.ingenieros.object_id
}

resource "azurerm_role_assignment" "ingeniero_capas" {
  for_each = toset(["bronze", "silver", "gold", "ops"])

  scope                = azurerm_storage_container.capas[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_group.ingenieros.object_id
}

resource "azurerm_role_assignment" "ingeniero_data_factory" {
  scope                = azurerm_data_factory.orquestador.id
  role_definition_name = "Data Factory Contributor"
  principal_id         = azuread_group.ingenieros.object_id
}

# --- Analista: solo Gold ---
# Reader sobre la cuenta solo permite VER que existe en el portal; no da acceso a los datos.
resource "azurerm_role_assignment" "analista_ver_cuenta" {
  scope                = azurerm_storage_account.lago.id
  role_definition_name = "Reader"
  principal_id         = azuread_group.analistas.object_id
}

resource "azurerm_role_assignment" "analista_gold" {
  scope                = azurerm_storage_container.capas["gold"].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azuread_group.analistas.object_id
}

# --- Auditoría de accesos a la base de origen (quién consultó qué y cuándo) ---
resource "azurerm_mssql_server_extended_auditing_policy" "origen" {
  server_id              = azurerm_mssql_server.origen.id
  log_monitoring_enabled = true
}

resource "azurerm_monitor_diagnostic_setting" "auditoria_sql" {
  name                       = "diag-sql-auditoria"
  target_resource_id         = "${azurerm_mssql_server.origen.id}/databases/master"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log { category = "SQLSecurityAuditEvents" }

  depends_on = [azurerm_mssql_server_extended_auditing_policy.origen]
}

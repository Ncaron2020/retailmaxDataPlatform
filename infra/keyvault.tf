# Key Vault: secretos que no se pueden reemplazar por identidades (ej. el salt para cifrar PII).
resource "azurerm_key_vault" "secretos" {
  name                = local.nombres.key_vault
  resource_group_name = azurerm_resource_group.principal.name
  location            = azurerm_resource_group.principal.location
  tenant_id           = data.azurerm_client_config.actual.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled = true # permisos con RBAC de Azure, no con políticas de acceso
  soft_delete_retention_days = 7
  purge_protection_enabled   = var.ambiente == "prod"

  tags = local.etiquetas
}

# Salt para el hash SHA-256 de datos personales en Silver. Lo genera Terraform:
# nadie lo escribe ni lo ve, y nunca aparece en el código.
resource "random_password" "salt_pii" {
  length  = 32
  special = false
}

resource "azurerm_key_vault_secret" "salt_pii" {
  name         = "salt-pii"
  value        = random_password.salt_pii.result
  key_vault_id = azurerm_key_vault.secretos.id

  depends_on = [azurerm_role_assignment.terraform_secretos]
}

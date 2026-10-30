# Data Lake: Storage Account con espacio de nombres jerárquico (ADLS Gen2).
resource "azurerm_storage_account" "lago" {
  name                     = local.nombres.storage
  resource_group_name      = azurerm_resource_group.principal.name
  location                 = azurerm_resource_group.principal.location
  account_tier             = "Standard"
  account_replication_type = var.replicacion_storage
  account_kind             = "StorageV2"
  is_hns_enabled           = true # esto lo convierte en ADLS Gen2

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false # ningún contenedor puede ser público
  shared_access_key_enabled       = false # solo Entra ID, sin claves de acceso

  blob_properties {
    # Permite recuperar archivos borrados por error durante 7 días
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }

  tags = local.etiquetas
}

# Capas del medallón + ops (bitácora del pipeline)
resource "azurerm_storage_container" "capas" {
  for_each = toset(["bronze", "silver", "gold", "ops"])

  name                  = each.key
  storage_account_id    = azurerm_storage_account.lago.id
  container_access_type = "private"

  # Terraform crea los contenedores usando tu identidad: necesita el rol de datos primero
  depends_on = [azurerm_role_assignment.terraform_datos_lago]
}

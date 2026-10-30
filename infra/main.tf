# Identidad con la que corre Terraform (tu usuario en local, o la de GitHub Actions en CI/CD).
data "azurerm_client_config" "actual" {}

# Sufijo aleatorio corto para los nombres que deben ser únicos en todo Azure
# (Storage, Key Vault, servidor SQL). Se genera una vez y queda fijo en el estado.
resource "random_string" "sufijo" {
  length  = 4
  upper   = false
  special = false
}

locals {
  proyecto = "retailmax"
  sufijo   = random_string.sufijo.result

  # Convención de nombres: <tipo>-retailmax-<componente>-<ambiente>
  nombres = {
    grupo_recursos = "rg-${local.proyecto}-${var.ambiente}"
    storage        = "st${local.proyecto}${var.ambiente}${local.sufijo}" # sin guiones, máx. 24
    key_vault      = "kv-${local.proyecto}-${var.ambiente}-${local.sufijo}"
    sql_server     = "sql-${local.proyecto}-origen-${var.ambiente}-${local.sufijo}"
    sql_database   = "sqldb-${local.proyecto}-${var.ambiente}"
    log_analytics  = "log-${local.proyecto}-${var.ambiente}"
    data_factory   = "adf-${local.proyecto}-${var.ambiente}-${local.sufijo}"
  }

  etiquetas = merge({
    proyecto   = local.proyecto
    ambiente   = var.ambiente
    gestionado = "terraform"
  }, var.etiquetas)
}

resource "azurerm_resource_group" "principal" {
  name     = local.nombres.grupo_recursos
  location = var.ubicacion
  tags     = local.etiquetas
}

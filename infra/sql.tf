# Base de datos de origen (simula el sistema transaccional de RetailMax).

# Servidor lógico de Azure SQL con autenticación SOLO de Entra ID: no existe usuario
# ni contraseña de SQL. El administrador es la identidad que ejecuta Terraform.
resource "azurerm_mssql_server" "origen" {
  name                          = local.nombres.sql_server
  resource_group_name           = azurerm_resource_group.principal.name
  location                      = var.ubicacion_sql
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = true

  azuread_administrator {
    login_username              = "administrador-entra"
    object_id                   = data.azurerm_client_config.actual.object_id
    tenant_id                   = data.azurerm_client_config.actual.tenant_id
    azuread_authentication_only = true
  }

  tags = local.etiquetas
}

# Base serverless con la oferta gratuita de Azure SQL: 100.000 segundos de vCore y 32 GB
# al mes sin costo. Si se agota, la base se pausa hasta el mes siguiente (no cobra).
resource "azapi_resource" "bd_origen" {
  type      = "Microsoft.Sql/servers/databases@2023-08-01-preview"
  name      = local.nombres.sql_database
  parent_id = azurerm_mssql_server.origen.id
  location  = var.ubicacion_sql
  tags      = local.etiquetas

  body = {
    sku = {
      name     = "GP_S_Gen5"
      tier     = "GeneralPurpose"
      family   = "Gen5"
      capacity = 2
    }
    properties = {
      useFreeLimit                = true
      freeLimitExhaustionBehavior = "AutoPause"
      autoPauseDelay              = 60 # minutos sin uso antes de pausarse
      minCapacity                 = 0.5
      maxSizeBytes                = 34359738368 # 32 GB
      collation                   = "SQL_Latin1_General_CP1_CI_AS"
    }
  }
}

# Permite el acceso desde servicios de Azure (Data Factory y Functions sin red privada).
resource "azurerm_mssql_firewall_rule" "servicios_azure" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.origen.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# Permite el acceso desde tu equipo para ejecutar load.py (solo si se define ip_cliente).
resource "azurerm_mssql_firewall_rule" "cliente" {
  count            = var.ip_cliente == "" ? 0 : 1
  name             = "ClienteCarga"
  server_id        = azurerm_mssql_server.origen.id
  start_ip_address = var.ip_cliente
  end_ip_address   = var.ip_cliente
}

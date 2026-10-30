# Orquestador del pipeline. Su identidad administrada (SystemAssigned) es la que usa
# para leer la base de origen y escribir en el lago, sin contraseñas.
resource "azurerm_data_factory" "orquestador" {
  name                   = local.nombres.data_factory
  resource_group_name    = azurerm_resource_group.principal.name
  location               = azurerm_resource_group.principal.location
  public_network_enabled = true

  identity {
    type = "SystemAssigned"
  }

  tags = local.etiquetas
}

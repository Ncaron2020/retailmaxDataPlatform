# Notificaciones del pipeline:
#   1. Correo de resumen (éxito o fallo con detalle), enviado por la Function con Azure Communication
#      Services al terminar cada ejecución. Lo dispara Data Factory.
#   2. Alerta de Azure Monitor: si una ejecución de Data Factory falla, avisa por correo aunque
#      el propio pipeline no alcance a notificar (red de seguridad independiente del código).

resource "azurerm_email_communication_service" "correo" {
  name                = local.nombres.correo
  resource_group_name = azurerm_resource_group.principal.name
  data_location       = "United States"
  tags                = local.etiquetas
}

# Dominio administrado por Azure (xxxx.azurecomm.net): permite enviar sin configurar un dominio propio
resource "azurerm_email_communication_service_domain" "azure" {
  name              = "AzureManagedDomain"
  email_service_id  = azurerm_email_communication_service.correo.id
  domain_management = "AzureManaged"
  tags              = local.etiquetas
}

resource "azurerm_communication_service" "comunicacion" {
  name                = local.nombres.comunicacion
  resource_group_name = azurerm_resource_group.principal.name
  data_location       = "United States"
  tags                = local.etiquetas
}

resource "azurerm_communication_service_email_domain_association" "correo" {
  communication_service_id = azurerm_communication_service.comunicacion.id
  email_service_domain_id  = azurerm_email_communication_service_domain.azure.id
}

# La Function envía correos con su identidad administrada (sin claves de ACS)
resource "azurerm_role_assignment" "funcion_correo" {
  scope                = azurerm_communication_service.comunicacion.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_function_app_flex_consumption.pipeline.identity[0].principal_id
}

# --- Alerta de Azure Monitor ---

resource "azurerm_monitor_action_group" "alertas" {
  name                = local.nombres.grupo_accion
  resource_group_name = azurerm_resource_group.principal.name
  short_name          = "retailmax"

  email_receiver {
    name                    = "equipo-datos"
    email_address           = var.correo_alertas
    use_common_alert_schema = true
  }

  tags = local.etiquetas
}

resource "azurerm_monitor_metric_alert" "pipeline_fallido" {
  name                = "alerta-pipeline-fallido-${var.ambiente}"
  resource_group_name = azurerm_resource_group.principal.name
  scopes              = [azurerm_data_factory.orquestador.id]
  description         = "Una ejecución del pipeline de RetailMax falló en Data Factory."
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.DataFactory/factories"
    metric_name      = "PipelineFailedRuns"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 0
  }

  action {
    action_group_id = azurerm_monitor_action_group.alertas.id
  }

  tags = local.etiquetas
}

variable "subscription_id" {
  description = "ID de la suscripción. Si se deja en null, se usa la variable de entorno ARM_SUBSCRIPTION_ID."
  type        = string
  default     = null
}

variable "ambiente" {
  description = "Nombre del ambiente: dev o prod."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.ambiente)
    error_message = "El ambiente debe ser dev o prod."
  }
}

variable "ubicacion" {
  description = "Región de Azure."
  type        = string
  default     = "southcentralus"
}

variable "ubicacion_sql" {
  description = "Región de Azure SQL. Separada porque las suscripciones de prueba tienen SQL restringido en algunas regiones (South Central US incluida)."
  type        = string
  default     = "centralus"
}

variable "replicacion_storage" {
  description = "Redundancia del Storage: LRS (una zona, dev) o ZRS (tres zonas, prod)."
  type        = string
  default     = "LRS"
}

variable "ip_cliente" {
  description = "IP pública desde la que se ejecuta load.py, para abrir el firewall de Azure SQL. Vacío = sin regla."
  type        = string
  default     = ""
}

variable "retencion_logs_dias" {
  description = "Días que Log Analytics conserva los logs."
  type        = number
  default     = 30
}

variable "etiquetas" {
  description = "Etiquetas adicionales para todos los recursos."
  type        = map(string)
  default     = {}
}

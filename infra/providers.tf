terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
    # azapi habla directo con la API de Azure. Se usa solo para la base de datos,
    # porque azurerm todavía no soporta la oferta gratuita de Azure SQL (useFreeLimit).
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.5"
    }
    # azuread: grupos de Entra ID para los roles del proyecto (administrador, ingeniero, analista)
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.4"
    }
  }

  # Estado remoto en un Storage Account dedicado (creado por bootstrap/crear-backend.sh).
  # La ubicación concreta por ambiente se pasa en el init:
  #   terraform init -backend-config=environments/backend-dev.hcl
  backend "azurerm" {}
}

provider "azapi" {}

provider "azuread" {}

provider "azurerm" {
  # Si es null, se toma de la variable de entorno ARM_SUBSCRIPTION_ID
  subscription_id = var.subscription_id
  # Entra ID en vez de claves de acceso para hablar con el Storage
  storage_use_azuread = true

  features {
    key_vault {
      # Al destruir, no purgar: el Key Vault queda recuperable (soft delete)
      purge_soft_delete_on_destroy = false
    }
    resource_group {
      # No borrar un grupo de recursos que tenga recursos creados fuera de Terraform
      prevent_deletion_if_contains_resources = true
    }
  }
}

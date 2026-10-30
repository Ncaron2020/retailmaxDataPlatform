#!/usr/bin/env bash
# Crea el Storage Account donde Terraform guarda su estado (una sola vez por suscripción).
#
# Es el problema del "huevo y la gallina": Terraform necesita dónde guardar su estado
# antes de poder crear cualquier cosa, así que este almacenamiento se crea con Azure CLI.
#
# Uso (desde Git Bash, con sesión iniciada en `az login`):
#   bash infra/bootstrap/crear-backend.sh
#
# Genera infra/environments/backend-dev.hcl y backend-prod.hcl para `terraform init`.

set -euo pipefail
export MSYS_NO_PATHCONV=1   # evita que Git Bash convierta rutas tipo /subscriptions/... en rutas de Windows

UBICACION="${1:-southcentralus}"
GRUPO="rg-retailmax-tfstate"
CONTENEDOR="tfstate"
SUSCRIPCION=$(az account show --query id -o tsv)
CUENTA="sttfretailmax${SUSCRIPCION:0:6}"          # nombre único derivado de la suscripción
USUARIO=$(az ad signed-in-user show --query id -o tsv)
CARPETA_ENV="$(cd "$(dirname "$0")/../environments" && pwd)"

echo "Grupo: $GRUPO | Storage: $CUENTA | Región: $UBICACION"

az group create --name "$GRUPO" --location "$UBICACION" \
  --tags proyecto=retailmax gestionado=bootstrap --output none

az storage account create --name "$CUENTA" --resource-group "$GRUPO" --location "$UBICACION" \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
  --allow-blob-public-access false --allow-shared-key-access false --output none

# Versionado: cada cambio del estado guarda la versión anterior (permite recuperarlo)
az storage account blob-service-properties update --account-name "$CUENTA" --resource-group "$GRUPO" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 7 --output none

# Permiso para leer y escribir el estado con Entra ID (sin claves de acceso)
ID_CUENTA=$(az storage account show --name "$CUENTA" --resource-group "$GRUPO" --query id -o tsv)
az role assignment create --assignee-object-id "$USUARIO" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" --scope "$ID_CUENTA" --output none

# El permiso tarda en propagarse: se reintenta crear el contenedor hasta que funcione
for intento in 1 2 3 4 5 6 7 8 9 10; do
  if az storage container create --name "$CONTENEDOR" --account-name "$CUENTA" --auth-mode login --output none 2>/dev/null; then
    break
  fi
  echo "Esperando propagación de permisos ($intento/10)..."
  sleep 15
done

# Candado: el grupo del estado no se puede borrar por accidente
az lock create --name "no-borrar-estado" --lock-type CanNotDelete --resource-group "$GRUPO" --output none

for AMBIENTE in dev prod; do
  cat > "$CARPETA_ENV/backend-$AMBIENTE.hcl" <<EOF
resource_group_name  = "$GRUPO"
storage_account_name = "$CUENTA"
container_name       = "$CONTENEDOR"
key                  = "$AMBIENTE.tfstate"
use_azuread_auth     = true
EOF
done

echo "Listo. Siguiente paso:"
echo "  cd infra && terraform init -backend-config=environments/backend-dev.hcl"

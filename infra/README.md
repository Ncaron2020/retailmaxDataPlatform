# Infraestructura (Terraform)

Toda la infraestructura de RetailMax en Azure se define en esta carpeta. El mismo código despliega
**dev** y **prod**; solo cambian los archivos de `environments/`.

## Qué crea

| Archivo | Recursos |
|---|---|
| `main.tf` | Grupo de recursos, sufijo aleatorio para nombres únicos, nombres de todos los recursos |
| `storage.tf` | Lago ADLS Gen2 (`bronze`, `silver`, `gold`, `ops`) sin claves de acceso |
| `sql.tf` | Servidor y base Azure SQL (oferta gratuita, serverless) con autenticación solo Entra ID |
| `keyvault.tf` | Key Vault (RBAC) y sal para el hash de datos personales |
| `functions.tf` | Function App Flex Consumption (Python 3.12) con identidad administrada |
| `datafactory.tf` | Data Factory con identidad administrada |
| `orquestacion.tf` | Servicios vinculados, pipeline `pl_retailmax_medallon` y trigger diario |
| `monitoring.tf` | Log Analytics, Application Insights y diagnósticos |
| `notificaciones.tf` | Azure Communication Services (correo), grupo de acciones y alerta de pipeline fallido |
| `rbac.tf` | Permisos de las identidades administradas (Function, Data Factory) |
| `gobierno.tf` | Grupos de Entra ID (administradores, ingenieros, analistas), sus permisos y auditoría de SQL |
| `sql/*.sql` | Scripts que se corren dentro de la base después del despliegue (permisos y clasificación de PII) |

Diferencias entre ambientes (`environments/*.tfvars`):

| Variable | dev | prod |
|---|---|---|
| `replicacion_storage` | LRS (una zona) | ZRS (tres zonas) |
| `retencion_logs_dias` | 30 | 90 |

## Requisitos

- Azure CLI con sesión iniciada (`az login`) y permisos de Owner sobre la suscripción.
- Terraform ≥ 1.9.
- Python 3.12 con las dependencias de `generacion-datos/requirements.txt` (para cargar datos y correr los scripts SQL).
- Git Bash (para el script de bootstrap en Windows).

## Despliegue paso a paso

Comandos en PowerShell desde la raíz del repositorio, salvo donde se indica.

### 1. Registrar los proveedores de recursos (una vez por suscripción)
Una suscripción nueva no tiene registrados los servicios que se usan:
```powershell
foreach ($p in "Microsoft.Storage","Microsoft.Sql","Microsoft.KeyVault","Microsoft.DataFactory",
  "Microsoft.Web","Microsoft.OperationalInsights","Microsoft.Insights","Microsoft.Communication") {
  az provider register --namespace $p
}
```

### 2. Crear el backend del estado (una vez por suscripción)
Terraform necesita dónde guardar su estado antes de crear cualquier cosa. Desde **Git Bash**:
```bash
bash infra/bootstrap/crear-backend.sh
```
Crea `rg-retailmax-tfstate` con un Storage versionado y sin claves, y genera `environments/backend-*.hcl`.

### 3. Desplegar la infraestructura
```powershell
cd infra
$env:ARM_SUBSCRIPTION_ID = (az account show --query id -o tsv)
terraform init "-backend-config=environments/backend-dev.hcl"
terraform plan "-var-file=environments/dev.tfvars" "-var=ip_cliente=<tu IP pública>" "-var=correo_alertas=<correo>" "-out=dev.tfplan"
terraform apply dev.tfplan
cd ..
```
- `ip_cliente` abre el firewall de SQL para tu equipo (necesario en el paso 4). Consultarla con `curl ifconfig.me`.
- `correo_alertas` recibe los correos del pipeline. No se guarda en el repositorio.
- En PowerShell los argumentos `-var...` van entre comillas: si no, PowerShell los parte en el punto.

### 4. Crear las tablas y cargar los datos de origen
```powershell
cd generacion-datos
..\.venv\Scripts\python generate.py
..\.venv\Scripts\python load.py --target azure --sql sql/ddl/01_create_tables.sql
```

### 5. Permisos de solo lectura y clasificación de PII en la base
Una vez por identidad (Data Factory y Function App). Los nombres salen de `terraform output`:
```powershell
..\.venv\Scripts\python load.py --target azure --sin-carga --sql ../infra/sql/permisos_origen.sql --var IDENTIDAD=<data_factory>
..\.venv\Scripts\python load.py --target azure --sin-carga --sql ../infra/sql/permisos_origen.sql --var IDENTIDAD=<function_app>
..\.venv\Scripts\python load.py --target azure --sin-carga --sql ../infra/sql/clasificacion_pii.sql
cd ..
```

### 6. Desplegar el código del pipeline
Automático con el workflow `.github/workflows/deploy-pipelines-dev.yml` al cambiar `pipelines/` en `develop`.
Requiere configurar OIDC una vez (identidad de GitHub en Entra ID, sin contraseña):
```powershell
$appId = az ad app create --display-name "gh-retailmax-deploy-dev" --query appId -o tsv
az ad sp create --id $appId
'{"name":"github-dev","issuer":"https://token.actions.githubusercontent.com","subject":"repo:<usuario>/<repo>:environment:dev","audiences":["api://AzureADTokenExchange"]}' | Out-File -Encoding ascii "$env:TEMP\fed-cred.json"
az ad app federated-credential create --id $appId --parameters "$env:TEMP\fed-cred.json"
$funcId = az functionapp show -g <grupo_recursos> -n <function_app> --query id -o tsv
az role assignment create --assignee $appId --role "Website Contributor" --scope $funcId
```
Luego, en GitHub (*Settings → Secrets and variables → Actions*), crear `AZURE_CLIENT_ID` (`$appId`),
`AZURE_TENANT_ID` y `AZURE_SUBSCRIPTION_ID` (`az account show`). Son identificadores, no contraseñas.
El permiso es solo sobre la Function: esta identidad no puede tocar el lago, la base ni el Key Vault.

Manualmente:
```powershell
# El zip debe tener rutas con "/" (Compress-Archive de PowerShell 5.1 usa "\" y la Function no carga)
az functionapp deployment source config-zip -g <grupo_recursos> -n <function_app> --src pipelines.zip --build-remote true
az functionapp function list -g <grupo_recursos> -n <function_app> --query "[].name" -o tsv
```
La segunda línea debe listar `ejecutar_capa` y `notificar`. Si sale vacía, el código no cargó.

### 7. Ejecutar
- Automático: trigger diario a las 02:00 (hora de Bogotá).
- Manual: Data Factory Studio → `pl_retailmax_medallon` → *Add trigger* → *Trigger now*.
  Parámetros opcionales: `tablas_bronze` (ej. `["TRANS_VENTAS"]`) y `fecha_corte` (`AAAA-MM-DD`).

## Producción

```powershell
terraform init -reconfigure "-backend-config=environments/backend-prod.hcl"
terraform plan "-var-file=environments/prod.tfvars" "-var=correo_alertas=<correo>" "-out=prod.tfplan"
```
Estado separado (`prod.tfstate`) en el mismo backend. Prod está definido pero no desplegado.

## Notas

- **Nada de secretos en el repositorio:** sin contraseñas de SQL (solo Entra ID), Storage sin claves,
  la sal y la clave de la Function viven en Key Vault. El estado de Terraform está en el backend remoto
  y `.gitignore` excluye `*.tfstate` y `*.tfplan`.
- **Azure SQL en Central US:** las suscripciones de prueba no pueden crear SQL en South Central US.
- **Administradores con Contributor, no Owner:** el Owner de la suscripción tiene una condición que
  impide delegar roles privilegiados; los permisos se otorgan solo desde Terraform.
- **Cadenas con clave en la Function:** el proveedor `azurerm` las agrega en cada actualización;
  `functions.tf` las elimina con un `terraform_data` para que la Function use solo su identidad.

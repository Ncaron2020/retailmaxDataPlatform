"""
Configuración del ambiente. El mismo código corre en dos lugares:

  RETAILMAX_ENTORNO=local  (por defecto) -> SQL Server en Docker y lago en ambiente-local/lake/
  RETAILMAX_ENTORNO=azure                -> Azure SQL y ADLS Gen2, autenticando con Entra ID

En Azure las variables las define la Function App; en local se leen de ambiente-local/.env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ_REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    entorno: str                 # "local" o "azure"
    sistema_fuente: str          # va en la columna de auditoría _sistema_fuente
    # Base de datos de origen
    sql_servidor: str
    sql_base: str
    sql_puerto: str = "1433"
    sql_password_local: str = ""
    # Lago
    lago_local: Path | None = None   # carpeta raíz del lago en local
    lago_cuenta: str = ""            # Storage Account en Azure
    key_vault_url: str = ""

    @property
    def es_local(self) -> bool:
        return self.entorno == "local"


def cargar_config() -> Config:
    entorno = os.getenv("RETAILMAX_ENTORNO", "local")

    if entorno == "local":
        load_dotenv(RAIZ_REPO / "ambiente-local" / ".env")
        return Config(
            entorno="local",
            sistema_fuente="sqlserver-local",
            # 127.0.0.1 y no "localhost": Docker publica el puerto solo en IPv4
            sql_servidor="127.0.0.1",
            sql_puerto=os.getenv("SQL_PORT", "1433"),
            sql_base=os.getenv("DB_NAME", "RetailMax"),
            sql_password_local=os.environ["MSSQL_SA_PASSWORD"],
            lago_local=RAIZ_REPO / "ambiente-local" / "lake",
        )

    if entorno == "azure":
        return Config(
            entorno="azure",
            sistema_fuente="azuresql-retailmax",
            sql_servidor=os.environ["AZURE_SQL_SERVER"],
            sql_base=os.environ["AZURE_SQL_DATABASE"],
            lago_cuenta=os.environ["LAGO_CUENTA"],
            key_vault_url=os.getenv("KEY_VAULT_URL", ""),
        )

    raise ValueError(f"RETAILMAX_ENTORNO desconocido: {entorno}")


def obtener_salt_pii(cfg: Config) -> str:
    """
    Salt para el hash SHA-256 de datos personales.
    En Azure se lee del Key Vault (secreto 'salt-pii', generado por Terraform).
    En local se usa PII_SALT del .env, o un valor de desarrollo si no existe.
    """
    if cfg.es_local:
        return os.getenv("PII_SALT", "salt-solo-para-desarrollo-local")

    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    cliente = SecretClient(vault_url=cfg.key_vault_url, credential=DefaultAzureCredential())
    return cliente.get_secret("salt-pii").value

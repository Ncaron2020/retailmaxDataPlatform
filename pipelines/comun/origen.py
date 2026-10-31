"""Conexión de solo lectura a la base de datos de origen (SQL Server local o Azure SQL)."""

from __future__ import annotations

import logging
import struct
import time

import polars as pl
import pyodbc

from comun.config import Config

DRIVER = "ODBC Driver 18 for SQL Server"
SQL_COPT_SS_ACCESS_TOKEN = 1256   # atributo ODBC para autenticarse con un token de Entra ID


def conectar(cfg: Config) -> pyodbc.Connection:
    if cfg.es_local:
        cadena = (
            f"DRIVER={{{DRIVER}}};SERVER={cfg.sql_servidor},{cfg.sql_puerto};DATABASE={cfg.sql_base};"
            f"UID=sa;PWD={cfg.sql_password_local};Encrypt=yes;TrustServerCertificate=yes;"
        )
        return pyodbc.connect(cadena)

    # Azure: sin contraseña. En tu PC usa `az login`; en la Function, su identidad administrada.
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token("https://database.windows.net/.default").token
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    cadena = (
        f"DRIVER={{{DRIVER}}};SERVER=tcp:{cfg.sql_servidor},1433;DATABASE={cfg.sql_base};"
        "Encrypt=yes;TrustServerCertificate=no;"
    )
    # La base serverless se pausa sin uso y tarda ~1 min en despertar. Mientras despierta responde
    # "no disponible" (error 40613) o agota el tiempo de espera. Reintento con espera creciente
    # (backoff exponencial: 10, 20, 40, 80 s), en vez del reintento fijo de Data Factory.
    intentos = 5
    for intento in range(intentos):
        try:
            return pyodbc.connect(cadena, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct}, timeout=180)
        except pyodbc.Error as exc:
            if intento == intentos - 1:
                raise
            espera = 10 * 2 ** intento
            logging.warning("Base de origen no disponible (intento %s/%s), reintento en %s s: %s",
                            intento + 1, intentos, espera, str(exc)[:200])
            time.sleep(espera)


def consultar(conn: pyodbc.Connection, sql: str, parametros: list | None = None) -> pl.DataFrame:
    """Ejecuta una consulta y devuelve un DataFrame con los tipos de la base."""
    return pl.read_database(sql, connection=conn, execute_options={"parameters": parametros or []},
                            infer_schema_length=None)

"""
Carga los archivos de generacion-datos/output/ en la base de datos de origen.

Destinos:
  --target local   SQL Server en Docker. Lee usuario y contraseña de ambiente-local/.env
  --target azure   Azure SQL Database. Sin contraseña: usa la sesión de `az login` (Entra ID).
                   Requiere las variables AZURE_SQL_SERVER y AZURE_SQL_DATABASE.

Uso:
    python load.py --target local
    python load.py --target azure
    python load.py --target local --tablas MSTR_TIENDAS CRM_MIEMBROS

    # Ejecutar scripts SQL (separados por GO) antes de cargar, o sin cargar:
    python load.py --target azure --sql sql/ddl/01_create_tables.sql --sin-carga
    python load.py --target azure --sql ../infra/sql/permisos_origen.sql --var ADF_NOMBRE=adf-xxx --sin-carga

Cada tabla se vacía (TRUNCATE) antes de cargar, así que se puede ejecutar varias veces
sin duplicar datos. Al final compara COUNT(*) de cada tabla contra las filas del archivo.
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import time
from pathlib import Path

import polars as pl
import pyodbc
import yaml
from dotenv import load_dotenv

CARPETA = Path(__file__).resolve().parent
RAIZ = CARPETA.parent
DRIVER = "ODBC Driver 18 for SQL Server"
LOTE = 50_000                      # filas por envío a la base de datos

# Orden de carga: primero los maestros, luego las transaccionales
TABLAS = [
    "MSTR_PROVEEDORES", "MSTR_ARTICULOS", "MSTR_TIENDAS", "CRM_MIEMBROS",
    "TRANS_VENTAS", "INV_STOCK_DIARIO", "POST_DEVOLUCIONES", "TRAF_VISITAS",
]

# Columnas que en el CSV parecen números pero en la base son texto
TIPOS_CSV = {"MSTR_ARTICULOS": {"cod_barra": pl.String}}


def conectar(target: str) -> pyodbc.Connection:
    if target == "local":
        load_dotenv(RAIZ / "ambiente-local" / ".env")
        cadena = (
            # 127.0.0.1 y no "localhost": Docker publica el puerto solo en IPv4, y en Windows
            # "localhost" intenta primero IPv6 (::1), donde la conexión es rechazada
            f"DRIVER={{{DRIVER}}};SERVER=127.0.0.1,{os.getenv('SQL_PORT', '1433')};"
            f"DATABASE={os.getenv('DB_NAME', 'RetailMax')};UID=sa;PWD={os.environ['MSSQL_SA_PASSWORD']};"
            "Encrypt=yes;TrustServerCertificate=yes;"   # certificado autofirmado del contenedor
        )
        return pyodbc.connect(cadena, autocommit=False)

    # Azure: token de Entra ID tomado de `az login`, sin usuario ni contraseña
    from azure.identity import AzureCliCredential

    servidor = os.environ["AZURE_SQL_SERVER"]          # ej. sql-retailmax-dev.database.windows.net
    base = os.environ["AZURE_SQL_DATABASE"]            # ej. sqldb-retailmax-dev
    token = AzureCliCredential().get_token("https://database.windows.net/.default").token
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    SQL_COPT_SS_ACCESS_TOKEN = 1256                    # atributo ODBC para autenticación por token
    cadena = f"DRIVER={{{DRIVER}}};SERVER=tcp:{servidor},1433;DATABASE={base};Encrypt=yes;TrustServerCertificate=no;"
    return pyodbc.connect(cadena, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct}, autocommit=False)


def ejecutar_script(conn: pyodbc.Connection, ruta: Path, variables: dict[str, str]) -> None:
    """Ejecuta un script SQL dividido por GO, reemplazando $(VARIABLE) como lo hace sqlcmd."""
    texto = ruta.read_text(encoding="utf-8")
    for clave, valor in variables.items():
        texto = texto.replace(f"$({clave})", valor)
    pendientes = re.findall(r"\$\((\w+)\)", texto)
    if pendientes:
        raise SystemExit(f"Faltan variables para {ruta.name}: {sorted(set(pendientes))} (usar --var NOMBRE=valor)")

    cursor = conn.cursor()
    for bloque in re.split(r"^\s*GO\s*$", texto, flags=re.MULTILINE | re.IGNORECASE):
        if bloque.strip():
            cursor.execute(bloque)
            while cursor.nextset():   # consume los mensajes de PRINT
                pass
    conn.commit()
    print(f"  Script ejecutado: {ruta.name}")


def leer_archivo(nombre: str, cfg: dict) -> pl.DataFrame:
    carpeta = CARPETA / cfg["salida"]["carpeta"]
    if nombre in cfg["salida"]["parquet"]:
        return pl.read_parquet(carpeta / f"{nombre}.parquet")
    return pl.read_csv(carpeta / f"{nombre}.csv", try_parse_dates=True,
                       schema_overrides=TIPOS_CSV.get(nombre))


def cargar_tabla(conn: pyodbc.Connection, nombre: str, df: pl.DataFrame) -> float:
    inicio = time.time()
    cursor = conn.cursor()
    cursor.fast_executemany = True                     # envía cada lote en una sola llamada
    cursor.execute(f"TRUNCATE TABLE dbo.{nombre}")

    columnas = ", ".join(df.columns)
    marcadores = ", ".join("?" for _ in df.columns)
    sql = f"INSERT INTO dbo.{nombre} ({columnas}) VALUES ({marcadores})"

    for desde in range(0, df.height, LOTE):
        cursor.executemany(sql, df.slice(desde, LOTE).rows())
        print(f"\r  {nombre:<20} {min(desde + LOTE, df.height):>10,} / {df.height:,}", end="", flush=True)
    conn.commit()
    return time.time() - inicio


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga los datos generados en la base de origen")
    parser.add_argument("--target", choices=["local", "azure"], required=True)
    parser.add_argument("--tablas", nargs="*", default=TABLAS, help="por defecto, todas")
    parser.add_argument("--sql", nargs="*", type=Path, default=[], help="scripts SQL a ejecutar antes de cargar")
    parser.add_argument("--var", nargs="*", default=[], help="variables para los scripts: NOMBRE=valor")
    parser.add_argument("--sin-carga", action="store_true", help="solo ejecutar los scripts, sin cargar datos")
    args = parser.parse_args()

    with open(CARPETA / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    print(f"Conectando a {args.target}...")
    conn = conectar(args.target)

    variables = dict(v.split("=", 1) for v in args.var)
    for ruta in args.sql:
        ejecutar_script(conn, ruta if ruta.is_absolute() else CARPETA / ruta, variables)
    if args.sin_carga:
        conn.close()
        return

    esperado = {}
    for nombre in args.tablas:
        df = leer_archivo(nombre, cfg)
        segundos = cargar_tabla(conn, nombre, df)
        esperado[nombre] = df.height
        print(f"  ({segundos:.0f} s)")

    print("\nVerificación (COUNT(*) en la base vs. filas del archivo):")
    cursor = conn.cursor()
    todo_ok = True
    for nombre, filas in esperado.items():
        en_base = cursor.execute(f"SELECT COUNT(*) FROM dbo.{nombre}").fetchone()[0]
        ok = en_base == filas
        todo_ok &= ok
        print(f"  {nombre:<20} {en_base:>12,}  {'OK' if ok else f'ERROR: se esperaban {filas:,}'}")
    conn.close()

    if not todo_ok:
        raise SystemExit("La carga no coincide con los archivos.")
    print("\nCarga completa.")


if __name__ == "__main__":
    main()

"""
Acceso al lago de datos. Misma interfaz en los dos ambientes:

  local -> carpetas en ambiente-local/lake/<contenedor>/...
  azure -> ADLS Gen2, abfss://<contenedor>@<cuenta>.dfs.core.windows.net/...

Los contenedores son las capas: bronze, silver, gold y ops.
"""

from __future__ import annotations

import io
import json

import polars as pl

from comun.config import Config


class Lago:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        if not cfg.es_local:
            from azure.identity import DefaultAzureCredential
            from azure.storage.filedatalake import DataLakeServiceClient

            # Sin claves: en tu PC usa `az login`; en la Function, su identidad administrada
            self._credencial = DefaultAzureCredential()
            self._servicio = DataLakeServiceClient(
                f"https://{cfg.lago_cuenta}.dfs.core.windows.net", credential=self._credencial)

    # --- Rutas y opciones para leer con polars / deltalake ---

    def uri(self, contenedor: str, ruta: str = "") -> str:
        if self.cfg.es_local:
            return str((self.cfg.lago_local / contenedor / ruta).as_posix())
        return f"abfss://{contenedor}@{self.cfg.lago_cuenta}.dfs.core.windows.net/{ruta}"

    def opciones(self) -> dict:
        """storage_options para polars y deltalake (vacío en local)."""
        if self.cfg.es_local:
            return {}
        token = self._credencial.get_token("https://storage.azure.com/.default").token
        return {"account_name": self.cfg.lago_cuenta, "bearer_token": token}

    # --- Archivos ---

    def escribir(self, contenedor: str, ruta: str, datos: bytes) -> None:
        if self.cfg.es_local:
            destino = self.cfg.lago_local / contenedor / ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(datos)
        else:
            sistema = self._servicio.get_file_system_client(contenedor)
            sistema.get_file_client(ruta).upload_data(datos, overwrite=True)

    def leer(self, contenedor: str, ruta: str) -> bytes | None:
        if self.cfg.es_local:
            origen = self.cfg.lago_local / contenedor / ruta
            return origen.read_bytes() if origen.exists() else None
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._servicio.get_file_system_client(contenedor).get_file_client(ruta).download_file().readall()
        except ResourceNotFoundError:
            return None

    def listar(self, contenedor: str, carpeta: str) -> list[str]:
        """Rutas de todos los archivos bajo una carpeta, relativas al contenedor."""
        if self.cfg.es_local:
            base = self.cfg.lago_local / contenedor
            raiz = base / carpeta
            return sorted(p.relative_to(base).as_posix() for p in raiz.rglob("*") if p.is_file()) if raiz.exists() else []
        from azure.core.exceptions import ResourceNotFoundError

        sistema = self._servicio.get_file_system_client(contenedor)
        try:
            return sorted(p.name for p in sistema.get_paths(path=carpeta, recursive=True) if not p.is_directory)
        except ResourceNotFoundError:
            return []   # la carpeta aún no existe (ej. pipeline_errors sin errores): igual que en local

    def escribir_parquet(self, df: pl.DataFrame, contenedor: str, ruta: str) -> int:
        """Escribe un DataFrame como Parquet y devuelve el tamaño del archivo en bytes."""
        buffer = io.BytesIO()
        df.write_parquet(buffer, compression="zstd")
        datos = buffer.getvalue()
        self.escribir(contenedor, ruta, datos)
        return len(datos)

    def leer_json(self, contenedor: str, ruta: str) -> dict:
        datos = self.leer(contenedor, ruta)
        return json.loads(datos) if datos else {}

    def escribir_json(self, contenedor: str, ruta: str, contenido: dict) -> None:
        self.escribir(contenedor, ruta, json.dumps(contenido, indent=2, ensure_ascii=False, default=str).encode("utf-8"))

    def leer_parquet_carpeta(self, contenedor: str, carpeta: str) -> pl.DataFrame:
        """Lee todos los Parquet de una carpeta (incluidas subcarpetas de partición)."""
        opciones = self.opciones() or None
        try:
            return pl.read_parquet(self.uri(contenedor, f"{carpeta}/**/*.parquet"),
                                   storage_options=opciones, hive_partitioning=False)
        except pl.exceptions.SchemaError:
            # Archivos con tipos distintos entre ejecuciones: se leen uno a uno y se unifican
            partes = [pl.read_parquet(self.uri(contenedor, ruta), storage_options=opciones)
                      for ruta in self.listar(contenedor, carpeta) if ruta.endswith(".parquet")]
            return pl.concat(partes, how="diagonal_relaxed")

"""
Bitácora del pipeline en el contenedor ops:

  ops/ejecuciones/      una fila por tabla procesada: registros, bytes, duración, estado
  ops/pipeline_errors/  una fila por excepción capturada, con el motivo
  ops/marcas_agua/      hasta dónde se cargó cada tabla (para el modo incremental)

Se guardan como Parquet particionado por fecha (anio/mes/dia), igual que Bronze.
"""

from __future__ import annotations

import datetime as dt
import traceback
import uuid

import polars as pl

from comun.lago import Lago


def ahora_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ruta_particionada(carpeta: str, momento: dt.datetime, id_lote: str) -> str:
    sufijo = uuid.uuid4().hex[:6]   # evita pisar otro archivo del mismo lote
    return f"{carpeta}/anio={momento:%Y}/mes={momento:%m}/dia={momento:%d}/{id_lote}-{sufijo}.parquet"


def registrar_ejecuciones(lago: Lago, filas: list[dict], id_lote: str) -> None:
    if filas:
        # Tipos fijos: si todas las marcas de agua son nulas, polars las guardaría como tipo Null
        # y los archivos de distintas ejecuciones no se podrían leer juntos.
        df = pl.DataFrame(filas).with_columns(
            pl.col("marca_agua_anterior", "marca_agua_nueva", "archivo").cast(pl.String))
        lago.escribir_parquet(df, "ops", _ruta_particionada("ejecuciones", ahora_utc(), id_lote))


def registrar_errores(lago: Lago, errores: list[dict], id_lote: str) -> None:
    if errores:
        lago.escribir_parquet(pl.DataFrame(errores), "ops", _ruta_particionada("pipeline_errors", ahora_utc(), id_lote))


def error_desde_excepcion(capa: str, tabla: str, id_lote: str, exc: Exception) -> dict:
    return {
        "id_lote": id_lote,
        "capa": capa,
        "tabla": tabla,
        "tipo_error": type(exc).__name__,
        "mensaje": str(exc)[:2000],
        "detalle": traceback.format_exc()[-4000:],
        "fecha_error": ahora_utc(),
    }


def leer_marcas_agua(lago: Lago, capa: str) -> dict:
    return lago.leer_json("ops", f"marcas_agua/{capa}.json")


def guardar_marcas_agua(lago: Lago, capa: str, marcas: dict) -> None:
    lago.escribir_json("ops", f"marcas_agua/{capa}.json", marcas)

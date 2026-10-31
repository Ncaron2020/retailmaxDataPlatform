"""
Capa Bronze: copia fiel de la base de origen al lago.

Requisitos del PDF y cómo se cumplen:
  - Formato Parquet en la nube ............ bronze/<TABLA>/...parquet
  - Esquema original sin modificar ........ SELECT * sin transformar columnas
  - 3 columnas de auditoría ............... _fecha_ingesta, _sistema_fuente, _id_lote
  - Partición por fecha de ingesta ........ bronze/<TABLA>/anio=AAAA/mes=MM/dia=DD/<lote>.parquet
  - Log de cada ejecución ................. ops/ejecuciones (registros, bytes, duración)
  - Modo incremental ...................... marca de agua por tabla en ops/marcas_agua/bronze.json
  - Solo días cerrados .................... se carga hasta el día ANTERIOR a la fecha de corte (por defecto
                                            hoy, hora de Bogotá). Así una ejecución manual a mitad del día
                                            no deja un día a medias que luego la marca de agua saltaría.
  - Reproducir estados anteriores ......... los archivos nunca se sobrescriben entre lotes:
                                            cada carga queda en su partición con su _id_lote
  - Reintentos con backoff exponencial .... 3 reintentos por tabla (5, 10, 20 s), ver comun/reintentos.py
  - Validación de volumen ................. si una tabla incremental trae más de 30 % por encima o por
                                            debajo del promedio de sus últimas 7 cargas, se registra en
                                            ops/alertas_volumen y se envía una alerta antes de seguir
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time

import polars as pl

from comun import bitacora, notificacion
from comun.config import Config, cargar_config
from comun.lago import Lago
from comun.origen import conectar, consultar
from comun.reintentos import con_reintentos

UMBRAL_VOLUMEN = 0.30      # 30 % de diferencia frente al promedio (regla del PDF)
VENTANA_VOLUMEN = 7        # últimas 7 ejecuciones
HISTORIAL_MINIMO = 3       # con menos historial no hay promedio confiable
ZONA_NEGOCIO = dt.timezone(dt.timedelta(hours=-5))   # Bogotá (UTC-5, sin horario de verano)

# Tabla de origen -> columna para el modo incremental.
# None = maestro pequeño: se copia completo en cada ejecución (snapshot).
TABLAS: dict[str, str | None] = {
    "MSTR_PROVEEDORES": None,
    "MSTR_ARTICULOS": None,
    "MSTR_TIENDAS": None,
    "CRM_MIEMBROS": None,
    "TRANS_VENTAS": "fec_trans",
    "INV_STOCK_DIARIO": "fec_snapshot",
    "POST_DEVOLUCIONES": "fec_devolucion",
    "TRAF_VISITAS": "fec_visita",
}


def resolver_fecha_corte(fecha_corte: str | None) -> dt.date:
    """
    Fecha de corte: se cargan los días ANTERIORES a esta fecha (días cerrados).
    Por defecto es hoy en Bogotá: el trigger de las 02:00 carga hasta ayer completo.
    En una ejecución manual se puede pasar otra fecha (AAAA-MM-DD), por ejemplo en dev
    para cargar días simulados.
    """
    if fecha_corte:
        return dt.date.fromisoformat(fecha_corte)
    return dt.datetime.now(ZONA_NEGOCIO).date()


def ingerir_tabla(cfg: Config, conn, lago: Lago, tabla: str, id_lote: str, marcas: dict,
                  corte: dt.date) -> dict:
    """Copia una tabla a Bronze. Devuelve la fila para la bitácora de ejecuciones."""
    inicio, momento = time.time(), bitacora.ahora_utc()
    if tabla not in TABLAS:
        raise ValueError(f"La tabla {tabla} no está configurada para Bronze (ver TABLAS en bronze/ingesta.py)")
    columna = TABLAS[tabla]
    marca_anterior = marcas.get(tabla, {}).get("valor") if columna else None

    if columna and marca_anterior:
        # Incremental: días posteriores al último cargado y anteriores a la fecha de corte (cerrados)
        modo = "incremental"
        df = consultar(conn, f"SELECT * FROM dbo.{tabla} WHERE {columna} > ? AND {columna} < ?",
                       [marca_anterior, corte.isoformat()])
    elif columna:
        # Primera carga: todo el historial hasta el último día cerrado
        modo = "completa"
        df = consultar(conn, f"SELECT * FROM dbo.{tabla} WHERE {columna} < ?", [corte.isoformat()])
    else:
        modo = "snapshot"
        df = consultar(conn, f"SELECT * FROM dbo.{tabla}")

    marca_nueva, bytes_escritos, ruta = marca_anterior, 0, None
    if df.height:
        df = df.with_columns(
            pl.lit(momento).alias("_fecha_ingesta"),
            pl.lit(cfg.sistema_fuente).alias("_sistema_fuente"),
            pl.lit(id_lote).alias("_id_lote"),
        )
        ruta = f"{tabla}/anio={momento:%Y}/mes={momento:%m}/dia={momento:%d}/{id_lote}.parquet"
        bytes_escritos = lago.escribir_parquet(df, "bronze", ruta)
        if columna:
            marca_nueva = str(df[columna].max())
            marcas[tabla] = {"columna": columna, "valor": marca_nueva, "actualizado": momento.isoformat()}

    return {
        "id_lote": id_lote,
        "capa": "bronze",
        "tabla": tabla,
        "modo": modo,
        "registros": df.height,
        "bytes": bytes_escritos,
        "duracion_s": round(time.time() - inicio, 2),
        "archivo": ruta,
        "marca_agua_anterior": marca_anterior,
        "marca_agua_nueva": marca_nueva,
        "estado": "ok",
        "fecha_inicio": momento,
    }


def validar_volumen(lago: Lago, ejecuciones: list[dict], id_lote: str) -> list[dict]:
    """
    Compara los registros de cada tabla incremental en esta ejecución contra el promedio de sus
    últimas 7 cargas incrementales con datos. Las ejecuciones sin datos nuevos (0 filas, por ejemplo
    una re-ejecución el mismo día) no cuentan para el promedio.
    """
    historial = lago.leer_parquet_carpeta("ops", "ejecuciones") if lago.listar("ops", "ejecuciones") else None
    alertas = []
    for e in ejecuciones:
        if e["modo"] != "incremental" or historial is None or e["registros"] == 0:
            continue
        previas = (historial
                   .filter((pl.col("capa") == "bronze") & (pl.col("tabla") == e["tabla"])
                           & (pl.col("modo") == "incremental") & (pl.col("registros") > 0)
                           & (pl.col("id_lote") != id_lote))
                   .sort("fecha_inicio", descending=True).head(VENTANA_VOLUMEN))
        if previas.height < HISTORIAL_MINIMO:
            continue
        promedio = previas["registros"].mean()
        desviacion = (e["registros"] - promedio) / promedio
        if abs(desviacion) > UMBRAL_VOLUMEN:
            alertas.append({
                "id_lote": id_lote, "tabla": e["tabla"], "registros": e["registros"],
                "promedio_ultimas_ejecuciones": round(promedio, 1), "ejecuciones_comparadas": previas.height,
                "desviacion_pct": round(desviacion * 100, 1), "umbral_pct": UMBRAL_VOLUMEN * 100,
                "fecha": bitacora.ahora_utc(),
            })
    return alertas


def ejecutar(id_lote: str, tablas: list[str] | None = None, fecha_corte: str | None = None) -> dict:
    """
    Ingresa las tablas indicadas (todas por defecto). Un error en una tabla se registra
    en ops/pipeline_errors y NO detiene las demás, como pide el PDF.
    """
    corte = resolver_fecha_corte(fecha_corte)
    logging.info("Bronze lote %s: fecha de corte %s (se cargan días anteriores)", id_lote, corte)
    cfg = cargar_config()
    lago = Lago(cfg)
    marcas = bitacora.leer_marcas_agua(lago, "bronze")
    ejecuciones, errores = [], []

    try:
        conn = conectar(cfg)
    except Exception as exc:
        # Sin conexión al origen no hay nada que ingerir: se registra el error y se termina
        errores.append(bitacora.error_desde_excepcion("bronze", "CONEXION_ORIGEN", id_lote, exc))
        bitacora.registrar_errores(lago, errores, id_lote)
        return {"id_lote": id_lote, "capa": "bronze", "ejecuciones": ejecuciones, "errores": errores}

    try:
        for tabla in tablas or list(TABLAS):
            try:
                ejecuciones.append(con_reintentos(
                    lambda: ingerir_tabla(cfg, conn, lago, tabla, id_lote, marcas, corte), f"Bronze {tabla}"))
            except Exception as exc:  # se captura todo: el pipeline sigue con la siguiente tabla
                errores.append(bitacora.error_desde_excepcion("bronze", tabla, id_lote, exc))
    finally:
        conn.close()
        # La bitácora se escribe siempre, aunque haya errores
        bitacora.registrar_ejecuciones(lago, ejecuciones, id_lote)
        bitacora.registrar_errores(lago, errores, id_lote)
        bitacora.guardar_marcas_agua(lago, "bronze", marcas)

    # Validación de volumen: la alerta sale ANTES de que el pipeline siga con Silver (regla del PDF)
    alertas = validar_volumen(lago, ejecuciones, id_lote)
    if alertas:
        momento = bitacora.ahora_utc()
        lago.escribir_parquet(pl.DataFrame(alertas), "ops",
                              f"alertas_volumen/anio={momento:%Y}/mes={momento:%m}/dia={momento:%d}/{id_lote}.parquet")
        ambiente = "local" if cfg.es_local else os.getenv("AMBIENTE", "dev")
        asunto, cuerpo = notificacion.construir_alerta_volumen(alertas, id_lote, ambiente)
        envio = notificacion.enviar(cfg, asunto, cuerpo)
        logging.warning("Alerta de volumen lote %s: %s -> %s", id_lote, asunto, envio)

    return {"id_lote": id_lote, "capa": "bronze", "ejecuciones": ejecuciones, "errores": errores,
            "alertas_volumen": alertas}

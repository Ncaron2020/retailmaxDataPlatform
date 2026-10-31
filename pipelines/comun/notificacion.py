"""
Correos del pipeline. Tres tipos, como pide el PDF:

  1. Alerta de FALLO: nombre del pipeline, tarea y capa afectada, fecha y hora, mensaje de error completo.
  2. Reporte de ÉXITO: registros por capa, tiempo total, registros rechazados por calidad, alertas de calidad.
  3. Alerta de VOLUMEN anómalo (diferenciada): la envía Bronze antes de que el pipeline continúe.

Los datos salen de ops/ (lo que el propio pipeline registró en ese lote). Se envían con Azure
Communication Services usando la identidad de la Function. En local no se envía nada.
"""

from __future__ import annotations

import datetime as dt
import html
import os

import polars as pl

from comun.config import Config
from comun.lago import Lago


def _leer_lote(lago: Lago, carpeta: str, id_lote: str) -> pl.DataFrame:
    if not lago.listar("ops", carpeta):
        return pl.DataFrame()
    df = lago.leer_parquet_carpeta("ops", carpeta)
    return df.filter(pl.col("id_lote") == id_lote) if "id_lote" in df.columns else pl.DataFrame()


def resumen_lote(lago: Lago, id_lote: str) -> dict:
    return {
        "ejecuciones": _leer_lote(lago, "ejecuciones", id_lote),
        "errores": _leer_lote(lago, "pipeline_errors", id_lote),
        "pruebas": _leer_lote(lago, "calidad_pruebas", id_lote),
        "calidad_silver": _leer_lote(lago, "calidad_silver", id_lote),
        "alertas_volumen": _leer_lote(lago, "alertas_volumen", id_lote),
    }


def _tabla_html(df: pl.DataFrame, columnas: list[str], max_texto: int = 300) -> str:
    columnas = [c for c in columnas if c in df.columns]
    if df.height == 0 or not columnas:
        return "<p><i>Sin registros.</i></p>"
    filas = "".join("<tr>" + "".join(f"<td>{html.escape(str(f[c]))[:max_texto]}</td>" for c in columnas) + "</tr>"
                    for f in df.select(columnas).to_dicts())
    return ("<table border='1' cellpadding='4' cellspacing='0'><tr>"
            + "".join(f"<th>{c}</th>" for c in columnas) + f"</tr>{filas}</table>")


def construir_correo(resumen: dict, id_lote: str, estado: str, ambiente: str, pipeline: str = "pl_retailmax_medallon",
                     inicio: str | None = None, detalle_adf: str = "") -> tuple[str, str]:
    ejecuciones, errores, pruebas = resumen["ejecuciones"], resumen["errores"], resumen["pruebas"]
    calidad_silver, alertas_volumen = resumen["calidad_silver"], resumen["alertas_volumen"]

    ahora = dt.datetime.now(dt.timezone.utc)
    duracion = ""
    if inicio:
        try:
            segundos = (ahora - dt.datetime.fromisoformat(inicio.replace("Z", "+00:00"))).total_seconds()
            duracion = f"{int(segundos // 60)} min {int(segundos % 60)} s"
        except ValueError:
            pass

    pruebas_fallidas = pruebas.filter(pl.col("resultado") != "APROBADA").height if pruebas.height else 0
    rechazados = int(calidad_silver["rechazados"].sum()) if calidad_silver.height else 0
    alertas_calidad = pruebas_fallidas + alertas_volumen.height

    fallo = estado != "exito" or errores.height > 0
    icono, titulo = ("❌", "FALLO del pipeline") if fallo else ("✅", "Reporte diario: pipeline completado")
    asunto = f"[RetailMax {ambiente}] {icono} {titulo} | {pipeline}"

    por_capa = (ejecuciones.filter(pl.col("capa").is_in(["bronze", "silver", "gold"]))
                .group_by("capa").agg(pl.len().alias("tablas"), pl.col("registros").sum().alias("registros"))
                .sort("capa") if ejecuciones.height else pl.DataFrame())

    secciones = [f"""
    <h2>{icono} {titulo}</h2>
    <p><b>Pipeline (DAG):</b> {html.escape(pipeline)}<br>
       <b>Ambiente:</b> {ambiente}<br>
       <b>Ejecución (lote):</b> {html.escape(id_lote)}<br>
       <b>Fecha y hora del reporte (UTC):</b> {ahora:%Y-%m-%d %H:%M:%S}<br>
       {f"<b>Tiempo total de ejecución:</b> {duracion}<br>" if duracion else ""}
       <b>Registros rechazados por calidad (Silver):</b> {rechazados:,}<br>
       <b>Alertas de calidad generadas:</b> {alertas_calidad} ({pruebas_fallidas} pruebas fallidas o con advertencia, {alertas_volumen.height} de volumen)</p>
    """]
    if fallo:
        secciones.append("<h3>Errores (tarea, capa, hora y mensaje completo)</h3>"
                         + _tabla_html(errores, ["capa", "tabla", "fecha_error", "tipo_error", "mensaje"], 2000))
        if detalle_adf:
            secciones.append(f"<p><b>Detalle de Data Factory:</b> {html.escape(detalle_adf)}</p>")
    secciones += [
        "<h3>Registros procesados por capa</h3>", _tabla_html(por_capa, ["capa", "tablas", "registros"]),
        "<h3>Detalle por tabla</h3>", _tabla_html(ejecuciones, ["capa", "tabla", "modo", "registros", "duracion_s"]),
        "<h3>Pruebas de calidad</h3>", _tabla_html(pruebas, ["prueba", "resultado", "filas_que_incumplen"]),
    ]
    if alertas_volumen.height:
        secciones += ["<h3>⚠️ Alertas de volumen</h3>",
                      _tabla_html(alertas_volumen, ["tabla", "registros", "promedio_ultimas_ejecuciones", "desviacion_pct"])]
    secciones.append("<p style='color:gray'>Historial completo en el monitor de Data Factory y en el contenedor ops del lago.</p>")
    return asunto, "".join(secciones)


def construir_alerta_volumen(alertas: list[dict], id_lote: str, ambiente: str) -> tuple[str, str]:
    asunto = f"[RetailMax {ambiente}] ⚠️ ANOMALÍA DE VOLUMEN detectada en Bronze"
    cuerpo = f"""
    <h2>⚠️ Anomalía de volumen</h2>
    <p>En la ejecución <b>{html.escape(id_lote)}</b>, los registros cargados en Bronze difieren más de 30 %
       del promedio de las últimas 7 ejecuciones. El pipeline <b>continúa</b>; revise el origen antes de
       usar los indicadores del día.</p>
    {_tabla_html(pl.DataFrame(alertas), ["tabla", "registros", "promedio_ultimas_ejecuciones", "ejecuciones_comparadas", "desviacion_pct", "umbral_pct"])}
    <p style='color:gray'>Registrado en ops/alertas_volumen.</p>
    """
    return asunto, cuerpo


def enviar(cfg: Config, asunto: str, cuerpo_html: str) -> str:
    endpoint, remitente, destino = (os.getenv("ACS_ENDPOINT"), os.getenv("CORREO_REMITENTE"),
                                    os.getenv("CORREO_ALERTAS"))
    if cfg.es_local or not (endpoint and remitente and destino):
        return "no enviado (ambiente local o sin configuración de correo)"

    from azure.communication.email import EmailClient
    from azure.identity import DefaultAzureCredential

    cliente = EmailClient(endpoint, DefaultAzureCredential())
    mensaje = {
        "senderAddress": remitente,
        "recipients": {"to": [{"address": destino}]},
        "content": {"subject": asunto, "html": cuerpo_html},
    }
    resultado = cliente.begin_send(mensaje).result()
    return f"enviado ({resultado.get('status')})"

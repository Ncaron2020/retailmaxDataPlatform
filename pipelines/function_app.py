"""
Puerta de entrada en Azure Functions. Equivale a run_local.py, pero por HTTP:

    POST https://<function-app>/api/capas/bronze?lote=<id>
    POST https://<function-app>/api/capas/silver?lote=<id>
    POST https://<function-app>/api/capas/gold?lote=<id>

Data Factory llama a cada URL en orden y le pasa como lote el id de su ejecución,
así cada archivo del lago se puede rastrear hasta la ejecución de ADF que lo creó.

Respuesta: 200 si todas las tablas terminaron bien; 500 si alguna falló
(Data Factory marca la actividad como fallida y dispara la alerta).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os

import azure.functions as func

from bronze import ingesta
from calidad import pruebas
from comun import notificacion
from comun.config import cargar_config
from comun.lago import Lago
from gold import modelo
from silver import limpieza

CAPAS = {"bronze": ingesta.ejecutar, "silver": limpieza.ejecutar, "gold": modelo.ejecutar,
         "calidad": pruebas.ejecutar}

# AuthLevel.FUNCTION: se necesita la clave de la función para llamarla (no es pública)
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="capas/{capa}", methods=["GET", "POST"])
def ejecutar_capa(req: func.HttpRequest) -> func.HttpResponse:
    capa = req.route_params.get("capa", "")
    if capa not in CAPAS:
        return func.HttpResponse(json.dumps({"error": f"Capa desconocida: {capa}"}), status_code=400,
                                 mimetype="application/json")

    try:
        cuerpo = req.get_json()
    except ValueError:
        cuerpo = {}
    id_lote = req.params.get("lote") or cuerpo.get("lote") or f"azure-{dt.datetime.utcnow():%Y%m%d-%H%M%S}"
    tablas = cuerpo.get("tablas")

    logging.info("Ejecutando capa %s, lote %s", capa, id_lote)
    if capa == "bronze":
        # fecha_corte opcional (AAAA-MM-DD): vacío = hoy, se cargan solo días cerrados
        resultado = ingesta.ejecutar(id_lote, tablas, cuerpo.get("fecha_corte") or None)
    else:
        resultado = CAPAS[capa](id_lote, tablas)

    resumen = {
        "capa": capa,
        "id_lote": id_lote,
        "tablas_ok": len(resultado["ejecuciones"]),
        "tablas_con_error": len(resultado["errores"]),
        "registros": {e["tabla"]: e["registros"] for e in resultado["ejecuciones"]},
        "errores": [{"tabla": e["tabla"], "mensaje": e["mensaje"]} for e in resultado["errores"]],
    }
    estado = 500 if resultado["errores"] else 200
    return func.HttpResponse(json.dumps(resumen, ensure_ascii=False, default=str), status_code=estado,
                             mimetype="application/json")


@app.route(route="notificar", methods=["POST"])
def notificar(req: func.HttpRequest) -> func.HttpResponse:
    """Envía el correo de resumen de una ejecución. Body: {"lote": ..., "estado": "exito"|"fallo", "detalle": ...}"""
    try:
        cuerpo = req.get_json()
    except ValueError:
        cuerpo = {}
    id_lote, estado = cuerpo.get("lote", "desconocido"), cuerpo.get("estado", "fallo")

    cfg = cargar_config()
    resumen = notificacion.resumen_lote(Lago(cfg), id_lote)
    asunto, html = notificacion.construir_correo(
        resumen, id_lote, estado, os.getenv("AMBIENTE", "dev"),
        pipeline=cuerpo.get("pipeline", "pl_retailmax_medallon"), inicio=cuerpo.get("inicio"),
        detalle_adf=cuerpo.get("detalle", ""))
    envio = notificacion.enviar(cfg, asunto, html)
    logging.info("Notificación lote %s: %s -> %s", id_lote, asunto, envio)
    return func.HttpResponse(json.dumps({"asunto": asunto, "envio": envio}, ensure_ascii=False),
                             mimetype="application/json")

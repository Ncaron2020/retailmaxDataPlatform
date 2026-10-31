"""
Verifica, contra los datos reales, cada requisito del PDF para la capa Bronze.

    python pipelines/verificar_bronze.py                      # ambiente local
    $env:RETAILMAX_ENTORNO="azure"; python pipelines/verificar_bronze.py   # Azure

Cada requisito se marca como CUMPLE o NO CUMPLE, con la evidencia encontrada.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import polars as pl  # noqa: E402

from bronze.ingesta import TABLAS  # noqa: E402
from comun.config import cargar_config  # noqa: E402
from comun.lago import Lago  # noqa: E402
from comun.origen import conectar, consultar  # noqa: E402

AUDITORIA = ["_fecha_ingesta", "_sistema_fuente", "_id_lote"]
PARTICION = re.compile(r"^[A-Z_]+/anio=\d{4}/mes=\d{2}/dia=\d{2}/[^/]+\.parquet$")

resultados: list[tuple[str, bool, str]] = []


def revisar(requisito: str, cumple: bool, evidencia: str) -> None:
    resultados.append((requisito, cumple, evidencia))


def main() -> None:
    cfg = cargar_config()
    lago = Lago(cfg)
    conn = conectar(cfg)
    print(f"Verificando Bronze en ambiente: {cfg.entorno}\n")

    archivos = {t: lago.listar("bronze", t) for t in TABLAS}
    datos = {t: lago.leer_parquet_carpeta("bronze", t) for t in TABLAS if archivos[t]}

    # 1. Formato Parquet en el lago
    faltan = [t for t in TABLAS if not archivos[t]]
    total = sum(len(a) for a in archivos.values())
    revisar("1. Ingesta en el lago en formato Parquet", not faltan,
            f"{total} archivos .parquet para {len(TABLAS) - len(faltan)}/{len(TABLAS)} tablas"
            + (f"; faltan: {faltan}" if faltan else ""))

    # 2. Esquema original sin modificaciones: mismas columnas y en el mismo orden que la tabla de origen
    distintas = []
    for tabla, df in datos.items():
        origen = consultar(conn, f"SELECT TOP 0 * FROM dbo.{tabla}").columns
        if [c for c in df.columns if c not in AUDITORIA] != origen:
            distintas.append(tabla)
    revisar("2. Esquema original sin modificaciones", not distintas,
            "columnas idénticas a la base de origen en todas las tablas" if not distintas
            else f"diferencias en: {distintas}")

    # 3. Tres columnas de auditoría, presentes y sin nulos
    problemas = [t for t, df in datos.items()
                 if any(c not in df.columns or df[c].null_count() for c in AUDITORIA)]
    ejemplo = datos["TRANS_VENTAS"].select(AUDITORIA).row(0) if "TRANS_VENTAS" in datos else None
    revisar("3. Columnas de auditoría (ingesta, fuente, lote)", not problemas,
            f"{AUDITORIA} completas en todas las filas; ejemplo: {ejemplo}" if not problemas
            else f"faltan o tienen nulos en: {problemas}")

    # 4. Particionamiento año / mes / día
    mal = [r for lista in archivos.values() for r in lista if not PARTICION.match(r)]
    revisar("4. Partición por fecha de ingesta año/mes/día", not mal,
            f"ejemplo: {archivos['TRANS_VENTAS'][0] if archivos['TRANS_VENTAS'] else '-'}" if not mal
            else f"{len(mal)} archivos fuera de la estructura, ej. {mal[0]}")

    # 5. Log de cada ejecución: registros, tamaño y duración
    log = lago.leer_parquet_carpeta("ops", "ejecuciones").filter(pl.col("capa") == "bronze")
    columnas_log = {"registros", "bytes", "duracion_s"}
    revisar("5. Log por ejecución (registros, tamaño, duración)",
            log.height > 0 and columnas_log <= set(log.columns),
            f"{log['id_lote'].n_unique()} ejecuciones registradas, {log.height} filas en ops/ejecuciones")

    # 6. Modo incremental: las transaccionales tienen marca de agua y NO se copiaron dos veces.
    #    Si el incremental fallara, Bronze tendría más filas que el origen.
    marcas = lago.leer_json("ops", "marcas_agua/bronze.json")
    detalle, ok_incremental = [], True
    for tabla, columna in TABLAS.items():
        if columna is None or tabla not in datos:
            continue
        en_origen = consultar(conn, f"SELECT COUNT(*) AS n FROM dbo.{tabla}")["n"][0]
        en_bronze = datos[tabla].height
        lotes = datos[tabla]["_id_lote"].n_unique()
        ok = tabla in marcas and en_bronze == en_origen
        ok_incremental &= ok
        detalle.append(f"{tabla}: origen={en_origen:,} bronze={en_bronze:,} en {lotes} lote(s), "
                       f"marca={marcas.get(tabla, {}).get('valor')}")
    revisar("6. Modo incremental (solo registros nuevos)", ok_incremental, " | ".join(detalle))

    # Extra: reproducibilidad. Cada lote queda en su propio archivo y no se sobrescribe.
    lotes_maestro = datos["MSTR_TIENDAS"]["_id_lote"].n_unique() if "MSTR_TIENDAS" in datos else 0
    revisar("Extra. Reproducir estados anteriores", lotes_maestro >= 1,
            f"MSTR_TIENDAS conserva {lotes_maestro} snapshot(s) históricos, uno por lote")

    conn.close()
    for requisito, cumple, evidencia in resultados:
        print(f"[{'CUMPLE' if cumple else 'NO CUMPLE':^9}] {requisito}")
        print(f"            {evidencia}\n")
    print(f"Resultado: {sum(c for _, c, _ in resultados)}/{len(resultados)} requisitos cumplidos")
    sys.exit(0 if all(c for _, c, _ in resultados) else 1)


if __name__ == "__main__":
    main()

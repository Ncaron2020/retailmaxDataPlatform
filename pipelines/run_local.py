"""
Ejecuta las capas del pipeline desde tu PC.

    python pipelines/run_local.py bronze
    python pipelines/run_local.py bronze --tablas TRANS_VENTAS MSTR_TIENDAS
    python pipelines/run_local.py bronze --fecha-corte 2026-11-03   (carga hasta el 2 de nov.)

Por defecto usa el ambiente local (Docker + ambiente-local/lake/).
Con RETAILMAX_ENTORNO=azure corre el mismo código contra Azure SQL y ADLS.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # para importar comun/, bronze/...

from bronze import ingesta  # noqa: E402
from silver import limpieza  # noqa: E402
from gold import modelo  # noqa: E402
from calidad import pruebas  # noqa: E402

CAPAS = {"bronze": ingesta.ejecutar, "silver": limpieza.ejecutar, "gold": modelo.ejecutar,
         "calidad": pruebas.ejecutar}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta una capa del pipeline RetailMax")
    parser.add_argument("capa", choices=CAPAS)
    parser.add_argument("--tablas", nargs="*")
    parser.add_argument("--lote", help="id del lote (por defecto: local-<fecha y hora>)")
    parser.add_argument("--fecha-corte", help="solo bronze: carga los días anteriores a esta fecha "
                                              "(AAAA-MM-DD; por defecto hoy)")
    args = parser.parse_args()

    id_lote = args.lote or f"local-{dt.datetime.now():%Y%m%d-%H%M%S}"
    print(f"Capa {args.capa} | lote {id_lote}\n")
    if args.capa == "bronze":
        resultado = ingesta.ejecutar(id_lote, args.tablas, args.fecha_corte)
    else:
        resultado = CAPAS[args.capa](id_lote, args.tablas)

    if resultado.get("pruebas") is not None:
        print(f"  {'PRUEBA':<32} {'RESULTADO':<10} {'INCUMPLEN':>10}")
        for p in resultado["pruebas"]:
            print(f"  {p['prueba']:<32} {p['resultado']:<10} {p['filas_que_incumplen']:>10,}")
        for err in resultado["errores"]:
            print(f"  ! {err['tabla']}: {err['mensaje'][:150]}")
        sys.exit(1 if resultado["errores"] else 0)

    print(f"  {'TABLA':<20} {'MODO':<12} {'REGISTROS':>12} {'KB':>10} {'SEG':>7}  MARCA DE AGUA")
    for e in resultado["ejecuciones"]:
        print(f"  {e['tabla']:<20} {e['modo']:<12} {e['registros']:>12,} {e['bytes'] / 1024:>10,.0f} "
              f"{e['duracion_s']:>7}  {e['marca_agua_nueva'] or ''}")
    if resultado.get("calidad"):
        print(f"\n  Reporte de calidad")
        print(f"  {'TABLA':<20} {'ENTRADA':>10} {'DUPLIC.':>8} {'RECHAZ.':>8} {'CONFORMES':>10} {'%CONF':>7}")
        for c in resultado["calidad"]:
            print(f"  {c['tabla']:<20} {c['registros_entrada']:>10,} {c['duplicados_eliminados']:>8,} "
                  f"{c['rechazados']:>8,} {c['conformes']:>10,} {c['pct_conformes']:>7}")
            if c["rechazos_por_motivo"] != "{}":
                print(f"      motivos: {c['rechazos_por_motivo']}")
    for err in resultado["errores"]:
        print(f"  {err['tabla']:<20} ERROR {err['tipo_error']}: {err['mensaje'][:120]}")

    if resultado["errores"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

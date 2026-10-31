"""
Reintentos con backoff exponencial (PDF: al menos tres intentos por tarea, con espera exponencial).

Data Factory solo reintenta a intervalos fijos, así que el backoff exponencial se aplica aquí,
dentro de cada tarea: si falla, espera 5 s, luego 10 s, luego 20 s (cada espera duplica la anterior).
"""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

T = TypeVar("T")

INTENTOS = 3          # intentos adicionales después del primero
ESPERA_BASE_S = 5     # 5, 10, 20 segundos


def con_reintentos(tarea: Callable[[], T], nombre: str, intentos: int = INTENTOS, espera_base: float = ESPERA_BASE_S) -> T:
    for intento in range(intentos + 1):
        try:
            return tarea()
        except Exception as exc:
            if intento == intentos:
                raise
            espera = espera_base * 2 ** intento
            logging.warning("%s falló (intento %s de %s): %s. Reintento en %s s",
                            nombre, intento + 1, intentos + 1, str(exc)[:200], espera)
            time.sleep(espera)

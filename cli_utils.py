"""
Sdílené CLI utility pro pic2omap skripty.

Drží opakované boilerplate, který se jinak duplikuje v každém CLI vstupu
(force_utf8_console, dále případně argument parsery, error handling, ...).
"""

from __future__ import annotations

import sys
from pathlib import Path


def imread_unicode(path, flags=None):
    """
    Načte obraz cestou s diakritikou (UTF-8 safe na Windows).

    `cv2.imread(str(path))` na Windows selže (vrátí None) u ne-ASCII cest,
    protože interně používá ANSI fopen. Obejdeme to čtením bytů přes Python
    a dekódováním přes `cv2.imdecode`. Vrací None při chybě (jako cv2.imread).

    flags: cv2 IMREAD_* flag (default IMREAD_COLOR jako cv2.imread).
    """
    import cv2
    import numpy as np

    if flags is None:
        flags = cv2.IMREAD_COLOR
    try:
        data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, flags)


def force_utf8_console() -> None:
    """
    Vynutí UTF-8 encoding pro stdout + stderr.

    Důvod: Windows konzole má default cp1250 (CZ Windows) nebo cp852,
    což rozbíjí českou diakritiku v reportech (`Zpracov�no` apod.).
    sys.stdout.reconfigure() je dostupné od Python 3.7 na TextIOWrapper.

    `hasattr` check chrání proti situaci, kdy stdout není TextIOWrapper
    (např. piped do souboru, redirected, IDE konzole) — tam reconfigure
    metodu nemá, AttributeError nechceme.

    Idempotentní — opakované volání je no-op (reconfigure jen překlopí stav).
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

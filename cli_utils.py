"""
Sdílené CLI utility pro pic2omap skripty.

Drží opakované boilerplate, který se jinak duplikuje v každém CLI vstupu
(force_utf8_console, dále případně argument parsery, error handling, ...).
"""

from __future__ import annotations

import sys


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

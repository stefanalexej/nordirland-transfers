#!/usr/bin/env python3
"""Diagnose-Skript: testet, ob EIN einzelner, isolierter Abruf einer
Kader-Unterseite von GitHub Actions aus funktioniert. Hilft zu klären,
ob das Problem an der Menge/dem Tempo der Anfragen liegt (dann würde
Verteilung über mehrere Stunden helfen) oder ob es eine grundsätzliche
Blockade ist (dann würde Verteilung NICHT helfen)."""

import sys
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

URL = "https://www.anstoss-online.de/?do=verein&verein_id=5010&detail=kader"  # Ballymoney Soccer

print(f"Teste isolierten Abruf von: {URL}")
try:
    resp = requests.get(URL, headers=HEADERS, timeout=25)
    print(f"Status-Code: {resp.status_code}")
    print(f"Antwortlänge: {len(resp.text)} Zeichen")
    print(f"Erste 200 Zeichen: {resp.text[:200]}")
    print("ERGEBNIS: Erfolgreich!")
except requests.RequestException as e:
    print(f"ERGEBNIS: Fehlgeschlagen: {e}")
    sys.exit(1)

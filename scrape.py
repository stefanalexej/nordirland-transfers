#!/usr/bin/env python3
"""
Liest die Anstoss-Online Länderseite für Nordirland aus und sammelt
alle bisher gesehenen Transfers in data.json auf.

Die Länderseite zeigt immer nur die letzten ~10 Transfers, deshalb wird
dieses Skript regelmäßig (per GitHub Actions) ausgeführt und merged
neue Einträge in die bestehende Datei, statt sie zu überschreiben.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# land_id=240 ist Nordirland. Für ein anderes Land einfach die ID
# austauschen (siehe Flaggenleiste unten auf anstoss-online.de).
URL = "https://www.anstoss-online.de/?do=land&land_id=240"
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
STRENGTH_RE = re.compile(r"^\d\.\d$")


def fetch_html() -> str:
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def find_transfer_table(soup: BeautifulSoup):
    """Findet die Transfer-Tabelle robust anhand ihrer Spaltenüberschriften,
    statt dich auf eine feste CSS-Klasse zu verlassen (die Seite hat keine
    stabilen IDs)."""
    keywords = {"pos", "spieler", "stärke", "alter", "nat", "von", "nach", "datum"}
    best_table, best_hits = None, 0
    for table in soup.find_all("table"):
        header_cells = table.find_all(["th", "td"], limit=12)
        header_text = " ".join(c.get_text(strip=True).lower() for c in header_cells)
        hits = sum(1 for kw in keywords if kw in header_text)
        if hits > best_hits:
            best_table, best_hits = table, hits
    return best_table if best_hits >= 5 else None


def parse_transfers(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = find_transfer_table(soup)
    if table is None:
        return []

    transfers = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue

        cell_texts = [c.get_text(" ", strip=True) for c in cells]
        full_text = " ".join(cell_texts)

        date_match = DATE_RE.search(full_text)
        if not date_match:
            continue  # Kopfzeile oder irrelevante Zeile

        pos = cell_texts[0].strip()

        player_link = row.find("a", href=re.compile(r"do=spieler"))
        if not player_link:
            continue
        player_name = player_link.get_text(strip=True)
        player_id_match = re.search(r"spieler(?:_)?id=(\d+)", player_link.get("href", ""))
        player_id = player_id_match.group(1) if player_id_match else None

        strength = next((t.strip() for t in cell_texts if STRENGTH_RE.match(t.strip())), None)

        age = None
        for t in cell_texts:
            t2 = t.strip()
            if t2.isdigit() and 14 <= int(t2) <= 45:
                age = int(t2)
                break

        nat_img = row.find("img", alt=True)
        nationality = nat_img.get("alt") if nat_img else None

        club_links = row.find_all("a", href=re.compile(r"do=verein"))
        if len(club_links) < 2:
            continue
        von, nach = club_links[0], club_links[1]
        von_name, nach_name = von.get_text(strip=True), nach.get_text(strip=True)
        von_id_m = re.search(r"verein_id=(\d+)", von.get("href", ""))
        nach_id_m = re.search(r"verein_id=(\d+)", nach.get("href", ""))

        date_str = date_match.group(0)

        transfer_id = "-".join([
            player_id or player_name,
            von_id_m.group(1) if von_id_m else von_name,
            nach_id_m.group(1) if nach_id_m else nach_name,
            date_str,
        ])

        transfers.append({
            "id": transfer_id,
            "pos": pos,
            "player": player_name,
            "player_id": player_id,
            "strength": strength,
            "age": age,
            "nationality": nationality,
            "from_club": von_name,
            "from_club_id": von_id_m.group(1) if von_id_m else None,
            "to_club": nach_name,
            "to_club_id": nach_id_m.group(1) if nach_id_m else None,
            "date": date_str,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })

    return transfers


def load_existing() -> list[dict]:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save(transfers: list[dict]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(transfers, f, ensure_ascii=False, indent=2)


def main() -> int:
    try:
        html = fetch_html()
    except requests.RequestException as e:
        print(f"Fehler beim Abrufen der Seite: {e}", file=sys.stderr)
        return 1

    scraped = parse_transfers(html)
    if not scraped:
        print("Warnung: Keine Transfers gefunden - evtl. hat sich die Seitenstruktur geändert.", file=sys.stderr)

    existing = load_existing()
    existing_ids = {t["id"] for t in existing}

    new_count = 0
    for t in scraped:
        if t["id"] not in existing_ids:
            existing.append(t)
            existing_ids.add(t["id"])
            new_count += 1

    def sort_key(t):
        try:
            return datetime.strptime(t["date"], "%d.%m.%Y")
        except (ValueError, KeyError):
            return datetime.min

    existing.sort(key=sort_key, reverse=True)
    save(existing)
    print(f"{new_count} neue Transfers hinzugefügt. Gesamt gespeichert: {len(existing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

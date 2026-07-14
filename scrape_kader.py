#!/usr/bin/env python3
"""
Speichert täglich den Kader aller 20 Premiership-Vereine aus clubs.json
und vergleicht ihn mit dem Stand vom letzten Lauf. So werden ALLE
Kaderveränderungen erkannt - auch wenn an einem Tag mehr als 10 Transfers
passieren (die Grenze der Transferliste auf der Länderseite betrifft
dieses Skript nicht, weil es keine Transferliste liest, sondern die
tatsächlichen Kader).

Ein Spieler, der bei Verein A verschwindet und am selben Tag bei Verein B
auftaucht, wird als "A -> B" erkannt. Verschwindet er nur (ohne bei einem
der 20 Vereine aufzutauchen), ist er vermutlich ins Ausland, in eine
andere Liga oder zu einem Verein ohne Manager gewechselt. Taucht er neu
auf, ohne vorher bei einem der 20 gewesen zu sein, kam er von außerhalb
(z.B. Ausland, Jugend, vereinsloser Verein).
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(__file__)
CLUBS_FILE = os.path.join(BASE_DIR, "clubs.json")
SNAPSHOT_FILE = os.path.join(BASE_DIR, "kader_latest.json")
CHANGES_FILE = os.path.join(BASE_DIR, "kader_changes.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}
KADER_URL = "https://www.anstoss-online.de/?do=verein&verein_id={id}&detail=kader"


def load_clubs():
    with open(CLUBS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_kader(session: requests.Session, club_id: str, attempts: int = 3, retry_delay: int = 15) -> list[dict]:
    last_error = None
    resp = None
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(KADER_URL.format(id=club_id), timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_error = e
            print(f"  Versuch {attempt}/{attempts} fehlgeschlagen: {e}")
            if attempt < attempts:
                time.sleep(retry_delay)
    if resp is None:
        raise last_error

    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # Die Kader-Tabelle anhand ihrer Spaltenüberschriften finden (robuster
    # als eine feste CSS-Klasse, die es auf dieser Seite nicht gibt).
    keywords = {"pos", "spieler", "stärke", "alter", "nat"}
    table = None
    for t in soup.find_all("table"):
        header_cells = t.find_all(["th", "td"], limit=10)
        header_text = " ".join(c.get_text(strip=True).lower() for c in header_cells)
        if sum(1 for kw in keywords if kw in header_text) >= 3:
            table = t
            break
    if table is None:
        return []

    strength_re = re.compile(r"^\d\.\d$")
    players = []
    for row in table.find_all("tr"):
        player_link = row.find("a", href=re.compile(r"do=spieler"))
        if not player_link:
            continue
        player_id_match = re.search(r"spieler(?:_)?id=(\d+)", player_link.get("href", ""))
        if not player_id_match:
            continue

        cell_texts = [c.get_text(" ", strip=True) for c in row.find_all("td")]
        pos = cell_texts[0].strip() if cell_texts else ""
        strength = next((t.strip() for t in cell_texts if strength_re.match(t.strip())), None)
        age = None
        for t in cell_texts:
            t2 = t.strip()
            if t2.isdigit() and 14 <= int(t2) <= 45:
                age = int(t2)
                break
        nat_img = row.find("img", alt=True)
        nationality = nat_img.get("alt") if nat_img else None

        players.append({
            "player_id": player_id_match.group(1),
            "player": player_link.get_text(strip=True),
            "pos": pos,
            "strength": strength,
            "age": age,
            "nationality": nationality,
        })

    return players


def fetch_loan_status(session: requests.Session, player_id: str, club_id: str):
    """Prüft im Spielerprofil (Tabelle "Bisherige Stationen"), ob der
    aktuelle Stint bei club_id als Leihe markiert ist. Da wir den Spieler
    schon als neu bei diesem Verein erkannt haben (Kadervergleich), reicht
    die letzte Zeile mit diesem Verein - kein Datumsabgleich nötig."""
    if not player_id or not club_id:
        return None
    try:
        resp = session.get(
            f"https://www.anstoss-online.de/?do=spieler&spieler_id={player_id}",
            timeout=20,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None

    keywords = {"verein", "ab", "bis", "einsätze", "leihe"}
    table = None
    for t in soup.find_all("table"):
        header_cells = t.find_all(["th", "td"], limit=10)
        header_text = " ".join(c.get_text(strip=True).lower() for c in header_cells)
        if sum(1 for kw in keywords if kw in header_text) >= 3:
            table = t
            break
    if table is None:
        return None

    result = None
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        club_link = cells[0].find("a", href=re.compile(r"do=verein"))
        if not club_link:
            continue
        row_club_id_m = re.search(r"verein_id=(\d+)", club_link.get("href", ""))
        if not row_club_id_m or row_club_id_m.group(1) != str(club_id):
            continue
        # Letzte passende Zeile gewinnt (Tabelle ist chronologisch).
        leihe_text = cells[5].get_text(strip=True)
        result = bool(leihe_text)
    return result


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> int:
    clubs = load_clubs()
    club_names = {c["id"]: c["name"] for c in clubs}

    print(f"Lade Kader für {len(clubs)} Vereine ...")
    session = requests.Session()
    session.headers.update(HEADERS)
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    current_snapshot = {}
    for club in clubs:
        try:
            players = fetch_kader(session, club["id"])
        except requests.RequestException as e:
            print(f"  Fehler bei {club['name']} ({club['id']}): {e}")
            continue
        current_snapshot[club["id"]] = players
        print(f"  {club['name']}: {len(players)} Spieler")
        time.sleep(1.5)  # kleine Pause, damit es nicht wie ein Bot-Sturm aussieht

    previous = load_json(SNAPSHOT_FILE, {"date": None, "clubs": {}})
    previous_clubs = previous.get("clubs", {})

    if previous.get("date") is None:
        # Erster Lauf: es gibt noch keinen Vergleichsstand. Nur den
        # aktuellen Kader als Basis speichern, keine "Fake-Transfers"
        # für alle ~400 Spieler erzeugen.
        save_json(SNAPSHOT_FILE, {"date": today, "clubs": current_snapshot})
        print("Erster Lauf: Basis-Kader gespeichert, noch keine Vergleichsdaten vorhanden.")
        return 0

    # Für jeden Verein: welche Spieler-IDs waren vorher da, welche jetzt?
    def player_index(club_players):
        return {p["player_id"]: p for p in club_players}

    left = {}   # player_id -> (club_id, player_info)
    joined = {}  # player_id -> (club_id, player_info)

    for club_id, players in current_snapshot.items():
        prev_players = player_index(previous_clubs.get(club_id, []))
        curr_players = player_index(players)

        for pid, info in curr_players.items():
            if pid not in prev_players:
                joined[pid] = (club_id, info)

        for pid, info in prev_players.items():
            if pid not in curr_players:
                left[pid] = (club_id, info)

    changes = load_json(CHANGES_FILE, [])
    existing_ids = {c["id"] for c in changes}

    new_count = 0
    all_player_ids = set(left.keys()) | set(joined.keys())
    for pid in all_player_ids:
        from_club_id, from_info = left.get(pid, (None, None))
        to_club_id, to_info = joined.get(pid, (None, None))
        info = to_info or from_info
        change_id = f"{pid}-{from_club_id}-{to_club_id}-{today}"
        if change_id in existing_ids:
            continue

        is_loan = None
        if to_club_id:
            time.sleep(1)  # kleine Pause vor dem Extra-Request zum Spielerprofil
            is_loan = fetch_loan_status(session, pid, to_club_id)

        changes.append({
            "id": change_id,
            "date": today,
            "player_id": pid,
            "player": info["player"],
            "pos": info["pos"],
            "strength": info["strength"],
            "age": info["age"],
            "nationality": info["nationality"],
            "from_club": club_names.get(from_club_id, "außerhalb Nordirland-1" if from_club_id is None else from_club_id),
            "from_club_id": from_club_id,
            "to_club": club_names.get(to_club_id, "außerhalb Nordirland-1" if to_club_id is None else to_club_id),
            "to_club_id": to_club_id,
            "is_loan": is_loan,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        })
        existing_ids.add(change_id)
        new_count += 1

    changes.sort(key=lambda c: c["detected_at"], reverse=True)
    save_json(CHANGES_FILE, changes)
    save_json(SNAPSHOT_FILE, {"date": today, "clubs": current_snapshot})

    print(f"{new_count} Kaderveränderungen erkannt. Gesamt gespeichert: {len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

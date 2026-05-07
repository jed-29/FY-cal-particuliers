import re
import hashlib
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event

BASE_URL = "https://www.impots.gouv.fr"
START_URL = "https://www.impots.gouv.fr/particulier/calendrier-fiscal"
OUTPUT_FILE = "calendrier-fiscal.ics"

# Nombre de mois à récupérer, mois courant inclus.
MONTHS_TO_FETCH = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 calendrier-fiscal-particulier-outlook"
}

MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def detect_month_year(soup):
    """
    Détecte le mois et l'année du calendrier affiché.
    Exemple : Mai 2026
    """
    month_title = soup.find(id="mois_calendrier")

    if month_title:
        text = clean_text(month_title.get_text(" "))
    else:
        text = soup.get_text(" ")

    match = re.search(
        r"\b(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )

    if not match:
        raise ValueError("Impossible de détecter le mois et l'année du calendrier fiscal.")

    month_name = match.group(1).lower()
    year = int(match.group(2))
    month = MONTHS[month_name]

    return month, year


def make_uid(event_date, title, description):
    """
    UID stable et unique.
    On inclut la description pour éviter les collisions quand deux événements ont le même titre le même jour.
    """
    raw = f"{event_date.isoformat()}|{title}|{description}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()
    return f"{digest}@calendrier-fiscal-particulier-impots"


def extract_description(card):
    desc = card.find(class_="fr-card__desc")

    if not desc:
        return ""

    # Supprime les badges "particulier" s'ils sont inclus dans le bloc.
    for badge in desc.find_all(class_=re.compile("fr-badge")):
        badge.decompose()

    lines = []

    for element in desc.find_all(["p", "li"]):
        text = clean_text(element.get_text(" "))
        if text:
            lines.append(text)

    if not lines:
        text = clean_text(desc.get_text(" "))
        if text:
            lines.append(text)

    unique_lines = []
    seen = set()

    for line in lines:
        if line.lower() in ["particulier", "professionnel"]:
            continue

        if line in seen:
            continue

        seen.add(line)
        unique_lines.append(line)

    return "\n".join(unique_lines)


def extract_events_from_page(soup, source_url):
    month, year = detect_month_year(soup)

    container = soup.find(id="calendrier_items")

    if not container:
        raise ValueError("Impossible de trouver le bloc calendrier_items.")

    events = []
    current_day = None

    items = container.find_all(["h3", "div"], recursive=True)

    for item in items:
        classes = item.get("class", [])

        # Détection d'un bloc date : "À partir du 15", puis "mai".
        if item.name == "h3":
            sr_only = item.find(class_="fr-sr-only")
            if sr_only and "À partir du" in sr_only.get_text(" "):
                day_match = re.search(r"\b(\d{1,2})\b", item.get_text(" "))
                if day_match:
                    current_day = int(day_match.group(1))
            continue

        # Détection d'une carte événement.
        if item.name == "div" and "fr-card" in classes:
            if current_day is None:
                continue

            title_tag = item.find("h4", class_=re.compile("fr-card__title"))

            if not title_tag:
                continue

            title = clean_text(title_tag.get_text(" "))
            description = extract_description(item)

            event_date = date(year, month, current_day)

            if description:
                full_description = f"{description}\nSource : {source_url}"
            else:
                full_description = f"Source : {source_url}"

            events.append({
                "date": event_date,
                "title": title,
                "description": full_description,
            })

    next_button = soup.find("button", class_=re.compile("after-month"))
    next_url = None

    if next_button and next_button.get("data-link"):
        next_url = urljoin(BASE_URL, next_button["data-link"])

    return events, next_url, month, year


def fetch_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def main():
    calendar = Calendar()
    calendar.creator = "github.com/jed-29/calendrier-impots-particulier"

    all_events = []
    current_url = START_URL
    visited_urls = set()

    for index in range(MONTHS_TO_FETCH):
        if not current_url:
            print("Plus de lien vers le mois suivant. Arrêt.")
            break

        if current_url in visited_urls:
            print(f"URL déjà visitée, arrêt pour éviter une boucle : {current_url}")
            break

        visited_urls.add(current_url)

        print(f"Récupération du mois {index + 1}/{MONTHS_TO_FETCH} : {current_url}")

        soup = fetch_page(current_url)
        events, next_url, month, year = extract_events_from_page(soup, current_url)

        print(f"  Mois détecté : {month}/{year}")
        print(f"  Événements trouvés : {len(events)}")

        all_events.extend(events)
        current_url = next_url

    all_events.sort(key=lambda item: (item["date"], item["title"], item["description"]))

    for item in all_events:
        event = Event()
        event.name = item["title"]
        event.begin = item["date"]
        event.make_all_day()
        event.description = item["description"]
        event.uid = make_uid(item["date"], item["title"], item["description"])
        calendar.events.add(event)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(calendar.serialize_iter())

    print(f"Calendrier généré : {OUTPUT_FILE}")
    print(f"Nombre total d'événements générés : {len(all_events)}")


if __name__ == "__main__":
    main()

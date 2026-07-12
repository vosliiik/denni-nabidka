#!/usr/bin/env python3
"""
Scraper denního menu z hotelzruc.cz -> denni-menu.json

Očekávaná struktura na stránce (sekce s kotvou #polednimenu) je sled
nadpisů/prvků v pořadí:
    [den, např. "Středa 1.7."]
    [polévka nebo první položka]
    [cena, obsahuje "Kč"]
    [položka]
    [cena]
    ...
Skript je odolný vůči drobným změnám (hledá container podle id, čte
z něj čistý text po řádcích a páruje "název -> cena podle Kč").

Použití:
    pip install requests beautifulsoup4 --break-system-packages
    python scrape_denni_menu.py > denni-menu.json

V produkci (GitHub Actions / cron) doporučeno spouštět vícekrát ráno
(např. 8:00, 9:00, 10:00) a vždy přepsat výstupní JSON — personál menu
nahrává ručně a čas se den ode dne liší.
"""

import json
import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

URL = "https://hotelzruc.cz/index.php"
TIMEOUT = 15

# Kč se v cenách objevuje vždy - to je nejspolehlivější signál "tohle je cena"
PRICE_RE = re.compile(r"\d+\s*Kč", re.IGNORECASE)

# Regex na český den v týdnu na začátku řádku, např. "Středa 1.7."
DAY_RE = re.compile(
    r"^(Pond[ěe]l[íi]|Úter[ýy]|St[řr]eda|Čtvrtek|P[áa]tek|Sobota|Ned[ěe]le)\b",
    re.IGNORECASE,
)


def fetch_html(url: str = URL) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MenuBot/1.0; +restaurace-zruc)"
    }
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def find_menu_container(soup: BeautifulSoup):
    """
    Sekce může být buď element s id="polednimenu", nebo kotva/odkaz
    <a id="polednimenu"> uvnitř širšího obalu — zkusíme obě varianty
    a vezmeme nejbližšího rozumně velkého rodiče.
    """
    anchor = soup.find(id="polednimenu")
    if anchor is None:
        # fallback: hledej podle nadpisu "POLEDNÍ MENU"
        anchor = soup.find(
            lambda tag: tag.name in ("h1", "h2", "h3", "h4")
            and "polední menu" in tag.get_text(strip=True).lower()
        )
    if anchor is None:
        return None

    # Vylez o pár úrovní výš, dokud nenajdeme kontejner s víc než ~5 řádky textu
    node = anchor
    for _ in range(5):
        if node.parent is None:
            break
        node = node.parent
        text_lines = [
            l.strip() for l in node.get_text("\n").split("\n") if l.strip()
        ]
        if len(text_lines) >= 5:
            return node
    return anchor.parent or anchor


def parse_menu(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    container = find_menu_container(soup)

    if container is None:
        return {"date": None, "day_label": None, "soup": None, "items": [], "found": False}

    lines = [l.strip() for l in container.get_text("\n").split("\n") if l.strip()]

    # Odfiltruj samotný nadpis "POLEDNÍ MENU" pokud tam je
    lines = [l for l in lines if l.upper() != "POLEDNÍ MENU"]

    day_label = None
    if lines and DAY_RE.match(lines[0]):
        day_label = lines.pop(0)

    # Teď by měly zbýt dvojice: název, cena, název, cena, ...
    items = []
    soup_item = None
    i = 0
    while i < len(lines) - 1:
        name, price = lines[i], lines[i + 1]
        if PRICE_RE.search(price):
            # Heuristika: první položka s cenou <= 60 Kč a obsahující "polévka"
            # nebo "vývar" v názvu bereme jako polévku dne, ne hlavní chod
            if soup_item is None and re.search(r"pol[ée]vk|vývar", name, re.IGNORECASE):
                soup_item = {"name": name, "price": price}
            else:
                items.append({"name": name, "price": price})
            i += 2
        else:
            # Řádek nevypadá jako pár (název, cena) - přeskoč a zkus dál
            i += 1

    now = datetime.now(timezone(timedelta(hours=2)))  # Europe/Prague (CEST, upravit dle DST dle potřeby)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "day_label": day_label,
        "soup": soup_item["name"] if soup_item else None,
        "soup_price": soup_item["price"] if soup_item else None,
        "items": items,
        "updated_at": now.strftime("%d.%m.%Y %H:%M"),
        "found": bool(items),
    }


def main():
    try:
        html = fetch_html()
    except requests.RequestException as e:
        print(json.dumps({"error": f"fetch failed: {e}", "found": False}, ensure_ascii=False))
        sys.exit(1)

    data = parse_menu(html)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

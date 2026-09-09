"""HTML -> objets. C'est ici que vivent tous les pièges du site.

Règle appliquée partout : jamais d'échec silencieux. Un champ qu'on ne sait
pas lire lève `ParseError`, l'appelant journalise et saute la fiche.
Retourner `None` en douce remplirait la base de valeurs fausses sans que
personne ne s'en aperçoive : c'est exactement le bug que le brief décrit.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import Book, ListingEntry

log = logging.getLogger(__name__)


class ParseError(ValueError):
    """Structure inattendue : la fiche est journalisée puis sautée."""


# PIEGE 1 - La note n'est pas un texte, elle est encodee dans une classe CSS.
RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

_PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_STOCK_RE = re.compile(r"(\d+)\s*available", re.IGNORECASE)


def parse_rating(node: Tag | BeautifulSoup) -> int:
    """Extrait la note depuis <p class="star-rating Three">.

    Deux façons de se tromper, toutes les deux SILENCIEUSES :

    1. chercher un chiffre dans le texte : il n'y en a aucun ;
    2. compter les <i class="icon-star"> : il y en a TOUJOURS cinq, quelle
       que soit la note. Vérifié en reconnaissance - un len(select(...))
       renverrait 5 pour les 1000 livres sans lever la moindre erreur.

    Seule la deuxième classe du <p> porte l'information.
    """
    tag = node.select_one("p.star-rating")
    if tag is None:
        raise ParseError("no star-rating element found")

    classes = [c for c in tag.get("class", []) if c != "star-rating"]
    for word in classes:
        if word in RATING_WORDS:
            return RATING_WORDS[word]
    raise ParseError(f"unrecognised rating class: {classes!r}")


def parse_price(raw: str | None) -> float:
    """Extrait la valeur numérique d'un prix.

    Regex sur les chiffres plutôt qu'un strip du symbole monétaire : ça
    immunise contre la devise, les espaces insécables, et un eventuel
    mojibake si l'encodage avait été mal deviné en amont.
    """
    match = _PRICE_RE.search(raw or "")
    if match is None:
        raise ParseError(f"no number found in price {raw!r}")
    return float(match.group(1).replace(",", "."))


def parse_stock(raw: str | None) -> int:
    """PIEGE 2 - Le stock réel n'existe que sur la fiche produit.

    La page de liste affiche "In stock", sans plus. La fiche indique
    "In stock (22 available)". S'arrêter à la liste rend la question
    centrale du brief impossible à traiter.
    """
    text = " ".join((raw or "").split())
    match = _STOCK_RE.search(text)
    if match:
        return int(match.group(1))
    if "out of stock" in text.lower():
        return 0
    raise ParseError(f"unreadable availability: {text!r}")


def parse_listing_page(
    soup: BeautifulSoup, page_url: str, listing_page: int
) -> list[ListingEntry]:
    """Extrait les livres d'une page de liste (20 par page)."""
    entries: list[ListingEntry] = []

    for article in soup.select("article.product_pod"):
        link = article.select_one("h3 a")
        if link is None or not link.get("href"):
            raise ParseError("product_pod without a title link")

        # PIEGE 3 - Le titre affiché est TRONQUE : "A Light in the ...".
        # Seul l'attribut title porte le titre complet. Se fier au texte
        # visible mutilerait des centaines de titres, sans erreur visible.
        title = (link.get("title") or link.get_text(strip=True)).strip()

        # PIEGE 4 - Les href sont relatifs, et leur forme CHANGE selon la
        # page d'ou on les lit : "catalogue/xxx/index.html" depuis l'accueil,
        # "xxx/index.html" depuis /catalogue/page-2.html, et les fiches se
        # référencent entre elles en "../../xxx/index.html".
        # urljoin résout les ".." relativement à la page courante ; toute
        # concaténation naïve produit des 404.
        product_url = urljoin(page_url, link["href"])

        price_tag = article.select_one("p.price_color")
        entries.append(
            ListingEntry(
                title=title,
                price=parse_price(price_tag.get_text()) if price_tag else None,
                rating=parse_rating(article),
                product_url=product_url,
                listing_page=listing_page,
            )
        )

    if not entries:
        raise ParseError("no product found on this listing page")
    return entries


def _product_information(soup: BeautifulSoup) -> dict[str, str]:
    """La table "Product Information" de la fiche, en dictionnaire."""
    table: dict[str, str] = {}
    for row in soup.select("table.table-striped tr"):
        header = row.find("th")
        cell = row.find("td")
        if header and cell:
            table[header.get_text(strip=True)] = cell.get_text(strip=True)
    if not table:
        raise ParseError("no product information table found")
    return table


def _required_field(table: dict[str, str], key: str) -> str:
    try:
        return table[key]
    except KeyError as exc:
        # On nomme la clé manquante : le log doit suffire à diagnostiquer un
        # changement de structure du site sans rouvrir le navigateur.
        raise ParseError(f"missing field {key!r} (got {sorted(table)})") from exc


def _parse_category(soup: BeautifulSoup) -> str | None:
    """La catégorie vit dans le fil d'Ariane : Home > Books > Poetry.

    Elle est donc GRATUITE : inutile de crawler les 50 pages de catégorie,
    ce qui maintient le total à 1050 requêtes.
    """
    links = soup.select("ul.breadcrumb li a")
    return links[-1].get_text(strip=True) if len(links) >= 3 else None


def _parse_description(soup: BeautifulSoup) -> str | None:
    """La description est le <p> FRERE du div, pas son enfant.

    Certains livres n'en ont pas : l'absence est tolérée (None), contrairement
    aux champs métier qui, eux, lèvent.
    """
    header = soup.find(id="product_description")
    if header is None:
        return None
    paragraph = header.find_next_sibling("p")
    return paragraph.get_text(strip=True) if paragraph else None


def parse_product_page(soup: BeautifulSoup, product_url: str) -> Book:
    """Extrait la fiche complète : c'est l'objet du mini-brief."""
    table = _product_information(soup)

    title_tag = soup.select_one("div.product_main h1")
    if title_tag is None:
        raise ParseError("no product title on this page")

    availability_raw = _required_field(table, "Availability")

    # PIEGE 5 - Deux prix et une taxe. Les trois sont collectés TELS QUELS
    # malgré la redondance constatée (HT == TTC, taxe nulle sur tout
    # l'échantillon) : si le site change un jour, on le verra. La conclusion
    # métier est dans NOTE_OBSERVATION.md.
    return Book(
        # PIEGE 6 - L'UPC est la clé métier ; le titre n'en est pas une (deux
        # livres peuvent porter le même titre, c'est précisément le problème
        # remonté par les achats).
        upc=_required_field(table, "UPC"),
        title=title_tag.get_text(strip=True),
        category=_parse_category(soup),
        price_excl_tax=parse_price(_required_field(table, "Price (excl. tax)")),
        price_incl_tax=parse_price(_required_field(table, "Price (incl. tax)")),
        tax=parse_price(_required_field(table, "Tax")),
        stock_qty=parse_stock(availability_raw),
        availability_raw=availability_raw,
        rating=parse_rating(soup),
        reviews_count=int(_required_field(table, "Number of reviews")),
        description=_parse_description(soup),
        product_url=product_url,
    )

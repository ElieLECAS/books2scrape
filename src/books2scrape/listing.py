"""Phase 1 - collecte des pages de liste.

Résultat testable attendu en fin de J1 : une commande unique produit un
fichier contenant les 1000 livres avec l'URL de leur fiche, et les logs
disent combien de pages ont été parcourues.

Ce fichier est le carburant de la Phase 2 : sans lui, rien n'est possible.

Choix de parcours
-----------------
On marche sur des URLs PREVISIBLES (`catalogue/page-N.html`, constaté en
reconnaissance) plutôt qu'en suivant le lien "next" de page en page. La
raison est la robustesse : en suivant "next", une page en échec fait perdre
le lien vers la suivante et donc tout le reste du catalogue. Avec des URLs
calculées, une page en échec est simplement sautée.

Le lien "next" reste utilisé comme garde-fou : s'il est encore présent sur
la dernière page attendue, c'est que le catalogue a grossi, et on le signale.
"""

from __future__ import annotations

import logging

import requests

from . import parsers
from .config import (
    EXPECTED_BOOKS,
    EXPECTED_LISTING_PAGES,
    LISTING_FILE,
    LISTING_URL_TEMPLATE,
    Settings,
)
from .http_client import PoliteSession
from .models import ListingEntry
from .storage import write_all

log = logging.getLogger(__name__)


def collect_listing(settings: Settings, limit_pages: int | None = None) -> int:
    """Parcourt les pages de liste et écrit `LISTING_FILE`.

    Retourne le nombre de livres écrits.
    """
    pages = limit_pages if limit_pages else EXPECTED_LISTING_PAGES
    log.info(
        "Listing phase: %d page(s) to walk, %.2f s between requests",
        pages,
        settings.request_delay,
    )

    entries: list[ListingEntry] = []
    pages_done = 0
    pages_failed = 0
    last_soup = None

    with PoliteSession(settings) as http:
        for page in range(1, pages + 1):
            url = LISTING_URL_TEMPLATE.format(page=page)
            try:
                soup = http.get_soup(url)
                page_entries = parsers.parse_listing_page(soup, url, page)
            except (requests.RequestException, parsers.ParseError) as exc:
                # Une page perdue ici, c'est 20 livres que la Phase 2 ne
                # verra jamais. On continue pour ne pas tout perdre, mais on
                # le signale en ERROR, et le total final ne fera pas 1000 :
                # le WARNING de fin rendra l'incident impossible à manquer.
                pages_failed += 1
                log.error(
                    "Listing page %d failed (%s): %s", page, type(exc).__name__, exc
                )
                continue

            entries.extend(page_entries)
            pages_done += 1
            last_soup = soup
            log.info(
                "Page %2d/%d -> %3d book(s), running total %4d",
                page,
                pages,
                len(page_entries),
                len(entries),
            )

        requests_made = http.requests_made

    written = write_all(LISTING_FILE, [entry.to_dict() for entry in entries])
    log.info(
        "Listing phase: %d/%d page(s) walked, %d request(s), %d book(s) -> %s",
        pages_done,
        pages,
        requests_made,
        written,
        LISTING_FILE.name,
    )

    if pages_failed:
        log.warning("%d listing page(s) failed and were skipped", pages_failed)

    # Garde-fou : un lien "next" encore présent sur la dernière page attendue
    # signifie que le catalogue dépasse maintenant EXPECTED_LISTING_PAGES.
    if limit_pages is None and last_soup is not None:
        if last_soup.select_one("li.next a") is not None:
            log.warning(
                "A 'next' link still exists after page %d: the catalogue grew, "
                "EXPECTED_LISTING_PAGES needs updating",
                pages,
            )
        if written != EXPECTED_BOOKS:
            log.warning(
                "Expected %d books, collected %d - the catalogue may have changed",
                EXPECTED_BOOKS,
                written,
            )

    return written

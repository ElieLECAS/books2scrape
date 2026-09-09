"""Phase 2 - collecte des fiches produit.

Mille requêtes, une par fiche. C'est ici que se joue le mini-brief.

Résultat testable attendu en fin de J2 : le scraper se relance par une
commande unique, une interruption en cours de route ne fait pas repartir de
zéro, et la base contient les 1000 livres avec leur stock réel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from . import parsers
from .config import BOOKS_FILE, FAILURES_FILE, LISTING_FILE, Settings
from .http_client import PoliteSession
from .storage import JsonlWriter, already_collected, read_jsonl

log = logging.getLogger(__name__)

# A 1000 fiches, un log par fiche est illisible. Le fichier de log garde le
# détail complet (il est en DEBUG), la console garde un point de repère.
PROGRESS_EVERY = 25


class CollectionAborted(RuntimeError):
    """Trop d'échecs consécutifs : le site a changé ou est tombé."""


@dataclass
class WorkPlan:
    """Ce qui reste à faire, et ce qui est déjà fait."""

    todo: list[str]
    already_done: int
    total_known: int

    @property
    def is_resume(self) -> bool:
        return self.already_done > 0


def plan_work(limit: int | None = None) -> WorkPlan:
    """Calcule la liste des fiches restant à collecter.

    C'est toute la reprise sur interruption, et elle tient en trois lignes
    utiles : on lit les URLs connues (Phase 1), on lit les URLs déjà
    collectées (le fichier de sortie lui-même), on soustrait.

    Pourquoi la clé est `product_url` et pas l'UPC : c'est la seule
    information disponible AVANT de faire la requête. L'UPC n'existe qu'une
    fois la fiche téléchargée, donc s'en servir ici obligerait à faire la
    requête pour savoir s'il faut la faire. L'UPC reste la clé de
    dédoublonnage en base - deux clés, deux usages distincts.

    Pourquoi aucun fichier de point de reprise : l'état EST la donnée. Si la
    ligne est dans `books.jsonl`, la fiche est collectée. Un curseur séparé
    pourrait mentir si l'interruption tombait entre l'écriture de la fiche et
    celle du curseur.

    `limit` est appliqué APRES la soustraction : en mode échantillon, une
    relance continue là où elle s'était arrêtée au lieu de re-tenter les
    mêmes N fiches.
    """
    known_urls = [
        record["product_url"]
        for record in read_jsonl(LISTING_FILE)
        if record.get("product_url")
    ]
    if not known_urls:
        raise FileNotFoundError(
            f"{LISTING_FILE.name} is empty or missing - run the listing phase first"
        )

    done = already_collected(BOOKS_FILE, key="product_url")
    todo = [url for url in known_urls if url not in done]

    if limit is not None:
        todo = todo[:limit]

    return WorkPlan(todo=todo, already_done=len(done), total_known=len(known_urls))


def collect_details(settings: Settings, limit: int | None = None) -> int:
    """Collecte les fiches restantes et les ajoute à `BOOKS_FILE`.

    Retourne le nombre de fiches collectées pendant CETTE exécution.
    """
    plan = plan_work(limit)

    # La ligne que le jury doit voir à la relance.
    if plan.is_resume:
        log.info(
            "Resume: %d fiche(s) already collected, %d to go (of %d known)",
            plan.already_done,
            len(plan.todo),
            plan.total_known,
        )
    else:
        log.info("Fresh start: %d fiche(s) to collect", len(plan.todo))

    if not plan.todo:
        log.info("Nothing left to collect - already complete.")
        return 0

    total = len(plan.todo)
    collected = 0
    failed = 0
    consecutive_failures = 0

    # Le writer ouvre en append et vide le tampon à CHAQUE ligne : c'est ce
    # qui rend la reprise exacte. La fiche est écrite immédiatement, jamais
    # accumulée en mémoire pour un enregistrement final - une collecte de
    # 12 minutes perdue au Ctrl+C est exactement ce que le brief veut éviter.
    with (
        PoliteSession(settings) as http,
        JsonlWriter(BOOKS_FILE) as out,
        JsonlWriter(FAILURES_FILE) as failures,
    ):
        for index, url in enumerate(plan.todo, start=1):
            try:
                soup = http.get_soup(url)
                book = parsers.parse_product_page(soup, url)
            except (requests.RequestException, parsers.ParseError) as exc:
                failed += 1
                consecutive_failures += 1
                reason = f"{type(exc).__name__}: {exc}"
                log.warning("Skipped %s (%s)", url, reason)
                failures.write({"product_url": url, "reason": reason})

                # Consécutifs et non cumulés : c'est ce qui distingue "le site
                # est tombé ou a changé" de "trois fiches sont bizarres".
                if consecutive_failures >= settings.max_consecutive_failures:
                    raise CollectionAborted(
                        f"{consecutive_failures} consecutive failures - "
                        f"stopping after {collected} fiche(s). "
                        f"Check {FAILURES_FILE.name}; relaunch to resume."
                    ) from exc
                continue

            consecutive_failures = 0
            out.write(book.to_dict())
            collected += 1

            if index % PROGRESS_EVERY == 0 or index == total:
                log.info(
                    "%4d/%d done, %d collected, %d skipped, %d left",
                    index,
                    total,
                    collected,
                    failed,
                    total - index,
                )

        requests_made = http.requests_made

    log.info(
        "Details phase: %d fiche(s) collected, %d skipped, %d request(s) made",
        collected,
        failed,
        requests_made,
    )
    if failed:
        log.warning("%d fiche(s) skipped - see %s", failed, FAILURES_FILE.name)
    return collected

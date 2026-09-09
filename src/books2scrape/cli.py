"""Point d'entrée unique du collecteur : `uv run books2scrape <commande>`.

argparse plutôt qu'une bibliothèque tierce : aucune dépendance de plus, et
le brief valorise la lisibilité avant l'ergonomie.

Codes de sortie, pour que la commande soit utilisable dans un script :
    0   succès
    2   configuration absente ou invalide
    3   PostgreSQL injoignable
    4   étape pas encore implémentée (squelette)
    5   donnée d'entrée manquante (phase précédente pas jouée)
    6   collecte avortée : trop d'échecs consécutifs
    130 interrompu au clavier (Ctrl+C) - convention shell
"""

from __future__ import annotations

import argparse
import logging
import sys

import psycopg

from . import __version__, db
from .details import CollectionAborted
from .config import (
    BOOKS_FILE,
    EXPORT_CSV,
    FAILURES_FILE,
    LISTING_FILE,
    ConfigError,
    Settings,
    ensure_dirs,
    load_settings,
)
from .logging_setup import setup_logging
from .storage import count_lines

log = logging.getLogger(__name__)


# --- commandes -----------------------------------------------------------


def cmd_check(args: argparse.Namespace, settings: Settings) -> int:
    """Vérifie que la configuration tient debout et que la base répond."""
    log.info("Config   : %s", settings.safe_database_url)
    log.info("UA       : %s", settings.user_agent)
    log.info("Throttle : %.2f s between requests", settings.request_delay)
    log.info("Failures : stop after %d consecutive", settings.max_consecutive_failures)

    version = db.server_version(settings)
    log.info("Server   : %s", version.split(" on ")[0])
    for table, count in db.table_counts(settings).items():
        log.info("Table    : %-10s %6d row(s)", table, count)
    return 0


def cmd_init_db(args: argparse.Namespace, settings: Settings) -> int:
    """Applique (ou rejoue) le schéma."""
    db.apply_schema(settings)
    for table, count in db.table_counts(settings).items():
        log.info("Table    : %-10s %6d row(s)", table, count)
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    """État de la collecte. Support de démonstration : c'est cette commande
    qu'on lance avant et après une interruption pour montrer la reprise."""
    log.info("listing.jsonl  : %6d url(s)", count_lines(LISTING_FILE))
    log.info("books.jsonl    : %6d fiche(s) collectee(s)", count_lines(BOOKS_FILE))
    log.info("failures.jsonl : %6d echec(s)", count_lines(FAILURES_FILE))
    log.info("export CSV     : %s", "present" if EXPORT_CSV.exists() else "absent")
    try:
        for table, count in db.table_counts(settings).items():
            log.info("base %-10s: %6d row(s)", table, count)
    except psycopg.OperationalError:
        log.warning("base           : injoignable (docker compose up -d ?)")
    return 0


def cmd_scrape_listing(args: argparse.Namespace, settings: Settings) -> int:
    from .listing import collect_listing

    total = collect_listing(settings, limit_pages=args.limit_pages)
    log.info("Listing phase done: %d book(s) in %s", total, LISTING_FILE.name)
    return 0


def cmd_scrape_details(args: argparse.Namespace, settings: Settings) -> int:
    from .details import collect_details

    collected = collect_details(settings, limit=args.limit)
    log.info("Details phase done: %d fiche(s) collected this run", collected)
    return 0


def cmd_load(args: argparse.Namespace, settings: Settings) -> int:
    from .load import load_books

    load_books(settings)
    return 0


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    from .export import export_csv

    export_csv()
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    """La commande unique du brief : liste, fiches, chargement, export.

    Chaque étape est aussi disponible seule, ce qui permet de recharger sans
    re-scraper - et de ne pas retaper sur le site pendant qu'on met au point
    les upserts.
    """
    for step in (cmd_scrape_listing, cmd_scrape_details, cmd_load, cmd_export):
        code = step(args, settings)
        if code != 0:
            return code
    return 0


HANDLERS = {
    "check": cmd_check,
    "init-db": cmd_init_db,
    "status": cmd_status,
    "scrape-listing": cmd_scrape_listing,
    "scrape-details": cmd_scrape_details,
    "load": cmd_load,
    "export": cmd_export,
    "run": cmd_run,
}


# --- plomberie -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="books2scrape",
        description="Collecte le catalogue books.toscrape.com vers PostgreSQL.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="logs DEBUG en console")

    sub = parser.add_subparsers(dest="command", metavar="<commande>", required=True)

    sub.add_parser("check", help="verifie la configuration et la connexion a la base")
    sub.add_parser("init-db", help="applique sql/schema.sql (idempotent)")
    sub.add_parser("status", help="etat de la collecte et de la base")

    listing = sub.add_parser("scrape-listing", help="phase 1 : les 50 pages de liste")
    listing.add_argument(
        "--limit-pages",
        type=int,
        metavar="N",
        help="mode echantillon : ne parcourt que les N premieres pages",
    )

    details = sub.add_parser("scrape-details", help="phase 2 : les 1000 fiches produit")
    details.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="mode echantillon : ne collecte que N fiches restantes",
    )

    sub.add_parser("load", help="charge books.jsonl dans PostgreSQL (idempotent)")
    sub.add_parser("export", help="exporte le jeu collecte en CSV")

    run = sub.add_parser("run", help="enchaine liste, fiches, chargement et export")
    run.add_argument("--limit", type=int, metavar="N", help="mode echantillon (fiches)")
    run.add_argument("--limit-pages", type=int, metavar="N", help="mode echantillon (pages)")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(verbose=args.verbose)

    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    ensure_dirs()

    try:
        return HANDLERS[args.command](args, settings)
    except psycopg.OperationalError as exc:
        # Cas de loin le plus frequent : le conteneur n'est pas demarre.
        log.error("Cannot reach PostgreSQL: %s", str(exc).strip())
        log.error("Hint: run `docker compose up -d`, then `docker compose ps`.")
        return 3
    except NotImplementedError as exc:
        log.error("Pas encore implemente : %s", exc)
        return 4
    except CollectionAborted as exc:
        # Ce qui a ete collecte avant l'arret est deja sur disque : une
        # relance reprendra a partir de la.
        log.error("Collection aborted: %s", exc)
        return 6
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 5
    except KeyboardInterrupt:
        # La reprise repose sur le fichier deja ecrit ligne par ligne : une
        # interruption ici ne perd rien de ce qui a ete collecte.
        log.warning("Interrupted by user - relaunch to resume where it stopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())

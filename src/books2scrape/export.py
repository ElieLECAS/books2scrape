"""Export du jeu collecté.

Livrable du brief : "le jeu collecté exporté en CSV ou JSON dans le repo".
C'est le seul artefact de données qui est versionné - `data/` est gitignoré
parce qu'il est volumineux et regénérable, `exports/` ne l'est pas.

Le CSV est exporté COMPLET, description incluse. Elle rend le fichier moins
agréable à ouvrir dans un tableur, mais un livrable amputé demanderait une
justification dans le README, et le module csv gère très bien les retours à
la ligne et les guillemets à l'intérieur d'un champ.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .config import BOOKS_FILE, EXPORT_CSV
from .load import BOOK_COLUMNS
from .storage import read_jsonl

log = logging.getLogger(__name__)

# `category` s'ajoute aux colonnes de la table : un CSV se lit seul, personne
# ne va joindre un category_id à la main dans un tableur.
CSV_COLUMNS = (
    "upc",
    "title",
    "category",
    *(column for column in BOOK_COLUMNS if column not in ("upc", "title")),
)


def export_csv(source: Path = BOOKS_FILE, destination: Path = EXPORT_CSV) -> int:
    """Convertit le JSONL en CSV. Retourne le nombre de lignes écrites."""
    if not source.exists():
        log.error("%s not found - run the details phase first", source.name)
        return 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    # newline="" n'est pas optionnel sous Windows : sans lui, le module csv
    # écrit des \r\r\n et le fichier a une ligne vide entre chaque
    # enregistrement.
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CSV_COLUMNS,
            # Les enregistrements portent des champs qui ne vont pas au CSV
            # (rien aujourd'hui, mais le contrat peut évoluer).
            extrasaction="ignore",
        )
        writer.writeheader()
        for record in read_jsonl(source):
            writer.writerow(record)
            written += 1

    log.info("Exported %d row(s) to %s", written, destination.name)
    return written

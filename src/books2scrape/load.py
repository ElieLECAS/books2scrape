"""Chargement JSONL -> PostgreSQL, idempotent.

Résultat testable exigé par le brief : deux exécutions successives du
chargement ne doivent rien dupliquer. L'idempotence est tenue par SQL, pas
par du Python - un ON CONFLICT est plus court, plus rapide et plus facile à
défendre en revue de code qu'un "SELECT puis INSERT ou UPDATE".
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from .config import BOOKS_FILE, Settings
from .db import connect
from .storage import read_jsonl

log = logging.getLogger(__name__)


# La clé de conflit est l'UPC : identifiant métier stable, contrairement au
# titre (deux livres peuvent porter le même titre - c'est exactement le
# problème remonté par la responsable des achats).
#
# DO UPDATE plutôt que DO NOTHING : recharger doit rafraîchir les prix et le
# stock, qui sont le vrai besoin de veille de Bouquineo. DO NOTHING rendrait
# la base figée après le premier chargement.
UPSERT_BOOK = """
    INSERT INTO books (
        upc, title, category_id, price_excl_tax, price_incl_tax, tax,
        stock_qty, availability_raw, rating, reviews_count, description,
        product_url, scraped_at
    )
    VALUES (
        %(upc)s, %(title)s, %(category_id)s, %(price_excl_tax)s,
        %(price_incl_tax)s, %(tax)s, %(stock_qty)s, %(availability_raw)s,
        %(rating)s, %(reviews_count)s, %(description)s, %(product_url)s, now()
    )
    ON CONFLICT (upc) DO UPDATE SET
        title            = EXCLUDED.title,
        category_id      = EXCLUDED.category_id,
        price_excl_tax   = EXCLUDED.price_excl_tax,
        price_incl_tax   = EXCLUDED.price_incl_tax,
        tax              = EXCLUDED.tax,
        stock_qty        = EXCLUDED.stock_qty,
        availability_raw = EXCLUDED.availability_raw,
        rating           = EXCLUDED.rating,
        reviews_count    = EXCLUDED.reviews_count,
        description      = EXCLUDED.description,
        product_url      = EXCLUDED.product_url,
        scraped_at       = now()
"""

BOOK_COLUMNS = (
    "upc",
    "title",
    "price_excl_tax",
    "price_incl_tax",
    "tax",
    "stock_qty",
    "availability_raw",
    "rating",
    "reviews_count",
    "description",
    "product_url",
)


@dataclass
class LoadReport:
    """Ce que le chargement a vu. Sert de support de démonstration."""

    lines_read: int = 0
    rejected: int = 0
    rows_before: int = 0
    rows_after: int = 0
    duplicate_upcs: dict[str, int] | None = None

    @property
    def rows_added(self) -> int:
        return self.rows_after - self.rows_before


class CategoryCache:
    """Résout un nom de catégorie en identifiant.

    Le catalogue n'a que 50 catégories : on les charge une fois, puis on
    n'insère que les nouvelles. Évite 1000 allers-retours inutiles.
    """

    def __init__(self, cursor: psycopg.Cursor) -> None:
        self.cursor = cursor
        cursor.execute("SELECT name, id FROM categories")
        self._ids: dict[str, int] = dict(cursor.fetchall())

    def id_for(self, name: str | None) -> int | None:
        if not name:
            return None
        if name not in self._ids:
            # DO UPDATE et non DO NOTHING, malgré l'apparence de no-op :
            # DO NOTHING ne renvoie AUCUNE ligne en cas de conflit, donc le
            # RETURNING serait vide et le fetchone() planterait sur une
            # catégorie insérée entre-temps par une autre exécution.
            self.cursor.execute(
                "INSERT INTO categories (name) VALUES (%s) "
                "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING id",
                (name,),
            )
            row = self.cursor.fetchone()
            if row is None:
                raise RuntimeError(f"could not resolve category {name!r}")
            self._ids[name] = row[0]
        return self._ids[name]


def _row_count(cursor: psycopg.Cursor, table: str) -> int:
    cursor.execute(f"SELECT count(*) FROM {table}")
    row = cursor.fetchone()
    return row[0] if row else 0


def _to_params(record: dict[str, Any], categories: CategoryCache) -> dict[str, Any]:
    params = {column: record.get(column) for column in BOOK_COLUMNS}
    params["category_id"] = categories.id_for(record.get("category"))
    return params


def load_books(settings: Settings, path: Path = BOOKS_FILE) -> LoadReport:
    """Charge le JSONL produit par la Phase 2 dans PostgreSQL.

    Tout se joue dans une seule transaction : soit le lot passe, soit la base
    reste dans son état d'avant. Un chargement à moitié appliqué serait pire
    qu'un chargement échoué, parce qu'il faudrait deviner où il s'est arrêté.
    """
    report = LoadReport()
    upcs: Counter[str] = Counter()

    with connect(settings) as conn, conn.cursor() as cursor:
        report.rows_before = _row_count(cursor, "books")
        categories = CategoryCache(cursor)

        for record in read_jsonl(path):
            report.lines_read += 1

            upc = record.get("upc")
            if not upc or not record.get("product_url"):
                # On refuse plutôt que d'insérer une ligne bancale, et on dit
                # laquelle : le log doit suffire au diagnostic.
                log.warning("Line %d rejected: missing upc or product_url", report.lines_read)
                report.rejected += 1
                continue

            upcs[upc] += 1
            cursor.execute(UPSERT_BOOK, _to_params(record, categories))

        report.rows_after = _row_count(cursor, "books")
        conn.commit()

    # Un UPC vu deux fois dans le fichier signifie que deux fiches distinctes
    # partagent le même identifiant : l'upsert écrase alors la première par la
    # seconde, et la base contient MOINS de lignes que le fichier. Ce n'est pas
    # un bug du chargement, c'est une propriété de la donnée source - mais elle
    # doit être visible, jamais silencieuse.
    report.duplicate_upcs = {upc: n for upc, n in upcs.items() if n > 1}

    log.info(
        "Loaded %s: %d line(s) read, %d rejected, %d row(s) in base (%+d)",
        path.name,
        report.lines_read,
        report.rejected,
        report.rows_after,
        report.rows_added,
    )
    if report.duplicate_upcs:
        log.warning(
            "%d UPC(s) appear more than once in the source file: %s",
            len(report.duplicate_upcs),
            ", ".join(sorted(report.duplicate_upcs)[:5]),
        )
        log.warning(
            "Consequence: the table holds fewer rows than the file has lines. "
            "This is a property of the source data, not a loading bug."
        )
    return report

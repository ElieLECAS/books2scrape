"""Le contrat de données : ce qui est collecté, et sous quelle forme.

Des dataclasses plutôt qu'une bibliothèque de validation : à ce périmètre
elles se lisent mieux en revue de code, et les invariants réellement
critiques sont tenus par les contraintes SQL (cf. sql/schema.sql).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ListingEntry:
    """Un livre vu depuis une page de liste (Phase 1).

    `product_url` est le carburant de la Phase 2, et aussi la clé de reprise :
    c'est la seule information disponible AVANT d'avoir fait la requête.
    L'UPC, lui, n'existe qu'une fois la fiche téléchargée — l'utiliser pour
    la reprise obligerait à faire la requête pour savoir s'il faut la faire.
    """

    title: str
    price: float | None
    rating: int | None
    product_url: str
    listing_page: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Book:
    """Une fiche produit complète (Phase 2).

    Les trois champs absents des pages de liste — `upc`, `stock_qty`,
    `reviews_count` — sont la raison d'être du mini-brief.
    """

    upc: str
    title: str
    category: str | None
    price_excl_tax: float | None
    price_incl_tax: float | None
    tax: float | None
    stock_qty: int | None
    availability_raw: str | None
    rating: int | None
    reviews_count: int | None
    description: str | None
    product_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

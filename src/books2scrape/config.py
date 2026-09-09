"""Configuration centralisée du collecteur.

Tout ce qui est réglable vit ici et provient de `.env` (cf. `.env.example`) :
aucune valeur sensible n'est codée en dur, et le rythme des requêtes peut
être ajusté pour la démonstration sans toucher au code.

Note d'encodage : les messages destinés à la console restent en ASCII pur.
La console Windows n'est pas en UTF-8 par défaut et un accent dans un log
provoquerait un UnicodeEncodeError en pleine collecte. Les commentaires et
docstrings, eux, ne sont jamais imprimés : ils gardent leurs accents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

from . import __version__

# uv installe le projet en editable : __file__ pointe vers src/books2scrape/,
# donc parents[2] est la racine du dépôt, là où vivent .env et sql/.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
EXPORTS_DIR = PROJECT_ROOT / "exports"
SQL_DIR = PROJECT_ROOT / "sql"

# --- La cible ------------------------------------------------------------
BASE_URL = "https://books.toscrape.com/"

# Constaté en reconnaissance : l'URL des pages de liste est prévisible
# (page-1 à page-50), page-51 renvoie 404, et le site annonce lui-même
# "Page 1 of 50". On garde quand même le suivi du lien "next" comme
# garde-fou, au cas où le catalogue grossirait.
LISTING_URL_TEMPLATE = BASE_URL + "catalogue/page-{page}.html"
EXPECTED_LISTING_PAGES = 50
EXPECTED_BOOKS = 1000

# --- Fichiers de travail -------------------------------------------------
LISTING_FILE = DATA_DIR / "listing.jsonl"      # phase 1 : les 1000 URLs de fiches
BOOKS_FILE = DATA_DIR / "books.jsonl"          # phase 2 : append au fil de l'eau
FAILURES_FILE = DATA_DIR / "failures.jsonl"    # fiches sautées, avec la raison
LOG_FILE = LOGS_DIR / "scrape.log"
EXPORT_CSV = EXPORTS_DIR / "books.csv"
EXPORT_JSON = EXPORTS_DIR / "books.json"
SCHEMA_FILE = SQL_DIR / "schema.sql"


class ConfigError(RuntimeError):
    """Configuration absente ou invalide : on s'arrête tôt, avec un message clair."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    user_agent: str
    request_delay: float
    request_timeout: float
    db_connect_timeout: int
    max_consecutive_failures: int

    @property
    def safe_database_url(self) -> str:
        """L'URL privée de son mot de passe, pour pouvoir la journaliser."""
        parts = urlsplit(self.database_url)
        if parts.password is None:
            return self.database_url
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        netloc = f"{parts.username}:***@{host}" if parts.username else host
        return urlunsplit(parts._replace(netloc=netloc))


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is missing. Copy .env.example to .env and fill it in."
        )
    return value


def _number(name: str, default: str, cast):
    raw = os.getenv(name, default).strip() or default
    try:
        return cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: expected a number, got {raw!r}") from exc


def load_settings() -> Settings:
    """Lit .env puis l'environnement. Les variables déjà définies gagnent."""
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        database_url=_required("DATABASE_URL"),
        # Un User-Agent explicite : qui scrape, dans quel cadre, et comment
        # nous joindre. C'est la contrepartie minimale d'une collecte massive.
        user_agent=os.getenv("USER_AGENT", "").strip()
        or f"Bouquineo-Scraper/{__version__}",
        # 0.5 s entre deux requêtes : 1050 requêtes en ~12 min. Voir README
        # pour la justification complète (robots.txt est absent du site,
        # aucun Crawl-delay ne sert donc de référence).
        request_delay=_number("REQUEST_DELAY", "0.5", float),
        request_timeout=_number("REQUEST_TIMEOUT", "15", float),
        # Sans ce reglage, psycopg attend indefiniment un serveur muet :
        # constate sous Windows sur un port sans rien en ecoute, ou le SYN
        # est reessaye au lieu d'etre refuse. Minimum libpq : 2 s.
        db_connect_timeout=_number("DB_CONNECT_TIMEOUT", "10", int),
        # Échecs CONSÉCUTIFS, pas cumulés : c'est ce qui distingue "le site a
        # changé ou est tombé" de "trois fiches sont bizarres".
        max_consecutive_failures=_number("MAX_CONSECUTIVE_FAILURES", "20", int),
    )


def ensure_dirs() -> None:
    """Crée les dossiers de travail. Ils sont gitignorés, donc absents
    d'un clone neuf : c'est au code de les recréer."""
    for directory in (DATA_DIR, LOGS_DIR, EXPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

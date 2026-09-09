"""Accès PostgreSQL : connexion, application du schéma, comptages.

Le collecteur n'écrit jamais ici. Il produit un JSONL, et le chargement est
une étape séparée : on peut recharger vingt fois sans retaper sur le site,
et une base indisponible ne fait pas perdre les requêtes déjà payées.
"""

from __future__ import annotations

import logging

import psycopg

from .config import SCHEMA_FILE, Settings

log = logging.getLogger(__name__)


def connect(settings: Settings) -> psycopg.Connection:
    """Connexion à la base.

    Le conteneur publie 5432 sur l'hôte et le script tourne sur l'hôte : on
    vise donc localhost, pas un nom de service Docker.

    `connect_timeout` est indispensable — sans lui, un serveur qui ne répond
    pas laisse le script pendu sans fin ni message, ce qui est le pire des
    comportements en pleine collecte.
    """
    return psycopg.connect(
        settings.database_url,
        connect_timeout=settings.db_connect_timeout,
    )


def apply_schema(settings: Settings) -> None:
    """Rejoue sql/schema.sql.

    Le montage `docker-entrypoint-initdb.d` ne joue le schéma qu'au tout
    premier démarrage, sur un volume vide. Cette commande couvre tous les
    autres cas, ce qui rend le README fiable quel que soit l'état de la
    machine — le schéma est écrit en CREATE ... IF NOT EXISTS.
    """
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with connect(settings) as conn:
        # psycopg3 accepte plusieurs instructions dans un execute() tant
        # qu'aucun paramètre n'est passé (protocole simple).
        conn.execute(sql)
    log.info("Schema applied from %s", SCHEMA_FILE.name)


def server_version(settings: Settings) -> str:
    with connect(settings) as conn:
        row = conn.execute("SELECT version()").fetchone()
    return row[0] if row else "unknown"


def table_counts(settings: Settings) -> dict[str, int]:
    """Nombre de lignes par table. Sert au diagnostic et à la démo."""
    counts: dict[str, int] = {}
    with connect(settings) as conn:
        for table in ("categories", "books"):
            row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
            counts[table] = row[0] if row else 0
    return counts

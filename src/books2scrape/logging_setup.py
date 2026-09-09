"""Journalisation : un flux console lisible pour la démonstration, un fichier
complet pour l'analyse après coup.

La qualité des logs est un critère de la revue de code, et ils servent de
support pendant la démo : ils doivent dire ce qui se passe, combien il reste
à faire, et ce qui a été sauté.
"""

from __future__ import annotations

import logging
import sys

from .config import LOG_FILE, LOGS_DIR


def setup_logging(verbose: bool = False) -> None:
    """Configure la console et le fichier. Appelable plusieurs fois sans
    empiler les handlers."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # Console : concise, horodatage court, c'est ce que le jury va lire.
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    )

    # Fichier : tout, y compris le DEBUG et le module émetteur. C'est lui
    # qu'on relit quand une collecte de 12 minutes a mal tourné.
    logfile = logging.FileHandler(LOG_FILE, encoding="utf-8")
    logfile.setLevel(logging.DEBUG)
    logfile.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s [%(name)s] %(message)s")
    )

    root.addHandler(console)
    root.addHandler(logfile)

    # urllib3 journalise chaque connexion en DEBUG : illisible à 1000 requêtes.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

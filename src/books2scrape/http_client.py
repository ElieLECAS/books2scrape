"""Client HTTP : politesse et robustesse.

Trois responsabilités, et une seule place où le piège d'encodage du site
est neutralisé.

Le rythme (0,5 s par défaut) est un choix documenté, pas un hasard :
1050 requêtes en ~12 minutes. Le site n'expose PAS de robots.txt — vérifié,
il renvoie 404 — donc aucun `Crawl-delay` ne sert de référence et la
justification repose entièrement sur nous. 2 requêtes/seconde reste dans
l'ordre de grandeur d'un humain qui navigue vite, sur des pages statiques.
"""

from __future__ import annotations

import logging
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings

log = logging.getLogger(__name__)


class PoliteSession:
    """Session HTTP qui s'identifie, temporise et réessaie.

    À utiliser comme gestionnaire de contexte :

        with PoliteSession(settings) as http:
            soup = http.get_soup(url)
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.requests_made = 0
        self._last_request_at: float | None = None

        self.session = requests.Session()
        # User-Agent explicite : qui collecte, dans quel cadre, comment nous
        # joindre. C'est la contrepartie minimale d'une collecte de masse.
        self.session.headers["User-Agent"] = settings.user_agent

        # Réessais sur les erreurs TRANSITOIRES seulement. Un 404 n'est pas
        # transitoire : insister serait à la fois inutile et impoli.
        retry = Retry(
            total=3,
            backoff_factor=1.0,  # attentes 0 s, 1 s, 2 s
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def __enter__(self) -> PoliteSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    def _throttle(self) -> None:
        """Garantit `request_delay` secondes entre la fin d'une requête et le
        début de la suivante.

        On mesure depuis la fin de la requête précédente, pas depuis son
        début : le délai s'ajoute au temps de réponse du serveur au lieu de
        l'absorber, ce qui garde le rythme réellement en dessous de la cible
        même si le site ralentit.
        """
        if self._last_request_at is None:
            return
        remaining = self.settings.request_delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def get_soup(self, url: str) -> BeautifulSoup:
        """Récupère une page et la rend prête à interroger.

        PIÈGE D'ENCODAGE, neutralisé ici et nulle part ailleurs : l'en-tête
        HTTP du site est `Content-Type: text/html`, SANS charset. requests
        retombe alors sur ISO-8859-1 et `response.text` rend « Â£51.77 » au
        lieu de « £51.77 » — vérifié aux octets, le document est bien en
        UTF-8 (`c2 a3` pour £) et déclare `<meta charset=UTF-8>`.

        La correction est de passer les OCTETS à BeautifulSoup, qui lit la
        déclaration du document et décode correctement.
        """
        self._throttle()
        try:
            response = self.session.get(url, timeout=self.settings.request_timeout)
        finally:
            # Même en cas d'exception, la requête a été émise : on repart du
            # bon instant, sinon la temporisation sauterait après un échec.
            self._last_request_at = time.monotonic()
            self.requests_made += 1

        response.raise_for_status()
        return BeautifulSoup(response.content, "lxml")

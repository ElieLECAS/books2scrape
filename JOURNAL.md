# Journal de bord

Organisé par phase du brief plutôt que par horodatage : le contenu suit
l'ordre réel du travail (reconnaissance → collecteur de listes → collecteur
de fiches et robustesse → chargement → finalisation), à répartir sur les
deux journées selon l'avancement réel.

## Phase 1 — Reconnaissance

**Objectif du matin** : cartographier le site sans écrire de script de
production, comme l'impose le brief.

- `https://books.toscrape.com/robots.txt` renvoie une page **404** — le
  fichier n'existe pas. Ni interdiction, ni autorisation explicite ; surtout,
  **aucun `Crawl-delay` de référence** pour calibrer la temporisation. La
  justification du rythme des requêtes reposera entièrement sur le
  raisonnement, pas sur une consigne du site (détaillé dans le README).

- Pagination : `catalogue/page-N.html`, prévisible de 1 à 50 ;
  `page-51.html` renvoie 404 et le site annonce lui-même `Page 1 of 50`.
  Décision : parcourir des URLs **calculées** plutôt que suivre le lien
  `next` de proche en proche — une page en échec ne fait alors pas perdre
  le fil vers les pages suivantes, elle est simplement sautée.

- **Piège rencontré** : la note n'est pas un texte, elle est encodée dans
  une classe CSS (`class="star-rating Three"`). Un premier réflexe —
  compter les balises `<i class="icon-star">` — a été écarté après
  vérification : ces cinq `<i>` sont présents sur **tous** les livres,
  quelle que soit la note réelle. Un scraper qui les compterait obtiendrait
  la note maximale pour les 1000 livres, **sans lever la moindre erreur**.
  Seule la deuxième classe du `<p>` porte l'information ; elle a été
  extraite via un dictionnaire `{"One": 1, ..., "Five": 5}`.

- **Piège non annoncé par le brief** : dans les pages de liste, le titre
  affiché est tronqué (`"A Light in the Attic"` devient
  `"A Light in the ..."`). Seul l'attribut `title` du lien porte le titre
  complet. Vérifié en comparant le texte visible et l'attribut sur une
  douzaine de fiches.

- **Autre piège non annoncé** : sur la fiche produit, la description n'est
  pas un enfant du `<div id="product_description">`, mais son `<p>`
  **frère** dans le DOM. Un `.find(id=...).get_text()` naïf renvoie une
  chaîne vide sans erreur.

- **Encodage** : l'en-tête HTTP des pages ne déclare aucun `charset`
  (`Content-Type: text/html`, sans plus). `requests` retombe alors sur
  ISO-8859-1 pour décoder `response.text`, ce qui transforme `£51.77` en
  `Â£51.77`. Vérifié directement aux octets (`£` est bien encodé `c2 a3`,
  de l'UTF-8, et le document déclare `<meta charset="UTF-8">`). Correctif
  retenu : passer `response.content` (les octets bruts) à BeautifulSoup et
  le laisser lire la déclaration du document, plutôt que `response.text`.

- Observation chiffrée sur un échantillon de 12 fiches : prix hors taxe
  systématiquement égal au prix TTC, taxe toujours à 0,00 £, nombre d'avis
  toujours à 0. Confirmé plus tard sur les 1000 livres complets — voir
  `NOTE_OBSERVATION.md`.

## Phase 1 — Collecteur de pages de liste

- L'installation d'outils a réservé sa propre surprise, sans rapport avec
  le site : après `winget install --id=astral-sh.uv -e`, la commande `uv`
  restait introuvable dans le terminal en cours. Le PATH utilisateur avait
  bien été mis à jour au niveau système, mais un terminal déjà ouvert
  hérite de l'environnement qu'il avait au démarrage. **Débloqué** en
  redémarrant le terminal.

- Docker Desktop n'était pas démarré au moment de lancer
  `docker compose up -d` : le CLI répondait, mais le moteur (`dockerd`) ne
  répondait pas encore. **Débloqué** en démarrant Docker Desktop et en
  attendant que `docker info` réponde avant de relancer la commande.

- Écriture de `listing.py` : parcours des 50 pages avec `urljoin(page_url,
  href)` pour résoudre les liens relatifs — nécessaire car leur forme
  **change selon la page d'où on les lit** (`catalogue/page-2.html` depuis
  l'accueil, `page-3.html` depuis `/catalogue/page-2.html`). Une
  concaténation naïve aurait produit des 404 sur une partie du catalogue.

- Résultat validé : 50/50 pages, 1000 livres, 50 requêtes, logs annonçant
  la progression page par page.

## Phase 2 — Collecteur de fiches produit et robustesse

- Une seule fiche d'abord enrichie de bout en bout et comparée au
  navigateur, avant tout passage à l'échelle — conformément au brief.

- **Blocage sérieux** : en testant le comportement sur une base
  injoignable (mauvais port), le script restait **pendu indéfiniment**,
  sans message ni erreur. Cause : `psycopg.connect()` n'avait aucun
  `connect_timeout`, et sous Windows une connexion vers un port sans
  service en écoute fait réessayer le paquet SYN au lieu de le refuser
  immédiatement. **Débloqué** en ajoutant un réglage `DB_CONNECT_TIMEOUT`
  (10 s par défaut) passé explicitement à `psycopg.connect()`. Revérifié :
  échec propre en 7 secondes, avec un message actionnable
  (`Hint: run docker compose up -d`).

- Conception de la reprise : l'état de la collecte est le fichier
  `books.jsonl` lui-même, relu au démarrage (`already_collected()`), plutôt
  qu'un curseur ou un fichier de point de reprise séparé — un curseur
  distinct pourrait se désynchroniser si l'interruption tombe entre
  l'écriture d'une fiche et celle du curseur. Clé retenue : `product_url`,
  seule information connue **avant** d'émettre la requête (l'UPC n'existe
  qu'après avoir téléchargé la fiche).

- **Test de robustesse le plus dur effectué** : plutôt qu'un simple
  Ctrl+C, le processus a été tué brutalement (`taskkill /F /T`, sans aucun
  arrêt propre) après 499 fiches collectées. Résultat : **zéro perte,
  aucune ligne corrompue** — le `flush()` après chaque écriture a tenu. La
  relance a immédiatement annoncé `Resume: 499 fiche(s) already collected,
  501 to go` et repris exactement là, sans re-télécharger une seule fiche
  déjà obtenue.

- Une fausse alerte pendant ce même test : un script de vérification
  utilisant `str.splitlines()` a signalé deux lignes « corrompues ». En
  creusant, la cause n'était pas une corruption réelle mais un caractère
  **U+2028 (LINE SEPARATOR)** présent une fois dans la description d'un
  livre (*Batman: Europa*) — `splitlines()` coupe dessus, contrairement au
  code de collecte qui n'itère que sur `\n`. Revérifié avec le vrai lecteur
  du projet (`read_jsonl`) : les 1000 enregistrements se parsent sans un
  seul avertissement.

- Gestion des échecs : testée avec des URLs volontairement mortes. Une
  fiche en erreur est journalisée dans `failures.jsonl` (URL + raison) et
  le lot continue ; au-delà de 20 échecs **consécutifs** (et non cumulés —
  c'est ce qui distingue un site tombé d'une poignée de fiches ponctuellement
  anormales), la collecte s'arrête proprement avec un code de sortie dédié.

- Collecte réelle complète des 1000 fiches : **12 min 09 s, 1050 requêtes
  au total (50 + 1000), zéro échec**.

## Chargement PostgreSQL et finalisation

- Conception du chargement : `INSERT ... ON CONFLICT (upc) DO UPDATE`
  plutôt que `DO NOTHING`, pour que recharger le fichier mette aussi à jour
  les prix et le stock (le vrai besoin de veille), sans dupliquer. Testé
  sur les 1000 lignes réelles : premier chargement `+1000`, second
  chargement identique `+0`.

- Contrôle de cohérence après chargement : 1000 lignes, 1000 UPC distincts,
  1000 URLs distinctes, 50 catégories, aucun champ obligatoire manquant.

- **Erreur trouvée en relisant le `.gitignore`** : la règle générique
  `exports/*` excluait aussi `exports/books.csv`, qui est pourtant un
  livrable explicitement exigé par le brief. **Débloqué** en ajoutant une
  exception `!exports/books.csv` — vérifié ensuite que `git status`
  proposait bien de le suivre.

- En manipulant `docker compose exec` depuis Git Bash pour rejouer le
  schéma (`psql -f /docker-entrypoint-initdb.d/01_schema.sql`), la commande
  échouait avec un chemin absurde
  (`C:/Program Files/Git/docker-entrypoint-initdb.d/...`). Cause : Git Bash
  réinterprète tout chemin commençant par `/` comme un chemin Windows.
  **Débloqué** avec la variable d'environnement `MSYS_NO_PATHCONV=1` en
  préfixe de la commande.

## Reste à faire avant la remise

- Exécuter le Ctrl+C **manuellement**, en conditions réelles de démo (le
  test le plus dur effectué à ce stade a été un arrêt brutal par
  `taskkill`, qui prouve la persistance des données mais pas le message
  d'interruption propre ni le code de sortie 130).
- Committer par jalon et répartir l'historique sur les deux journées ;
  créer le dépôt GitHub public et y pousser le tout.
- Répéter la démonstration complète dans le temps imparti (10 minutes +
  questions), avec `sql/questions.sql` prêt à l'emploi pour répondre à la
  question centrale du brief.

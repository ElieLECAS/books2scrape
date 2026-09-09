# Bouquineo — veille concurrentielle sur books.toscrape.com

Bouquineo est un libraire en ligne qui suit le catalogue d'un concurrent.
Les pages de liste du concurrent n'affichent que le titre, le prix, la note
et une disponibilité vague ("In stock"). Trois informations manquent pour
répondre aux questions des achats — **le stock réel, l'UPC, le nombre
d'avis** — et elles ne vivent que sur les fiches produit, une par livre.

Ce dépôt contient le collecteur qui va les chercher (1000 fiches) et les
charge dans PostgreSQL, avec deux garanties non négociables à ce volume :
une interruption ne fait pas repartir de zéro, et un rechargement ne crée
aucun doublon.

**Question à laquelle la base permet de répondre** : *sur quels titres le
concurrent est-il en rupture ou en stock faible, et lesquels sont les mieux
notés de son catalogue ?* Voir [sql/questions.sql](sql/questions.sql).

## Sommaire

- [Installation depuis zéro](#installation-depuis-zéro)
- [Utilisation](#utilisation)
- [Technologies et justification](#technologies-et-justification)
- [Architecture](#architecture)
- [Ce que dit robots.txt](#ce-que-dit-robotstxt)
- [Rythme des requêtes](#rythme-des-requêtes)
- [Les deux clés (reprise et dédoublonnage)](#les-deux-clés-reprise-et-dédoublonnage)
- [Reprise sur interruption](#reprise-sur-interruption)
- [Schéma de base](#schéma-de-base)
- [Seuil retenu pour "stock faible"](#seuil-retenu-pour-stock-faible)
- [Dépannage](#dépannage)
- [Auteur](#auteur)

## Installation depuis zéro

### Prérequis

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (moteur démarré)
- Git
- `uv` — s'il n'est pas installé :
  ```powershell
  winget install --id=astral-sh.uv -e
  ```
  Redémarrez le terminal après l'installation (le PATH est mis à jour au
  niveau utilisateur, pas dans la session en cours). `uv` installe et épingle
  lui-même Python 3.12, aucune installation Python séparée n'est nécessaire.

### Étapes

```bash
git clone <url-de-ce-depot>
cd books2scrape

# 1. Configuration : copier le modèle et renseigner un mot de passe
cp .env.example .env
# éditer .env : POSTGRES_PASSWORD et DATABASE_URL doivent utiliser le MEME mot de passe

# 2. Démarrer PostgreSQL (applique le schéma automatiquement au premier démarrage)
docker compose up -d
docker compose ps          # attendre "healthy"

# 3. Installer les dépendances Python (uv le fait aussi automatiquement au premier `uv run`)
uv sync

# 4. Vérifier que tout est en ordre : configuration lue, base joignable
uv run books2scrape check
```

`uv run books2scrape check` doit afficher la version du serveur PostgreSQL et
`0 row(s)` pour les tables `categories` et `books`. Si la base ne répond pas,
voir [Dépannage](#dépannage).

## Utilisation

### Collecte complète (mode réel)

```bash
uv run books2scrape run
```

Enchaîne les quatre étapes : 50 pages de liste (~35 s) → 1000 fiches produit
(~12 min) → chargement PostgreSQL → export CSV. Chaque étape est aussi
disponible seule (voir ci-dessous), ce qui permet de recharger la base sans
re-scraper le site.

### Mode échantillon (démonstration rapide)

```bash
uv run books2scrape run --limit-pages 2 --limit 20
```

Ne parcourt que 2 pages de liste et ne collecte que 20 fiches. Utile pour
vérifier que la chaîne complète fonctionne sans attendre 12 minutes.

### Étapes séparées

```bash
uv run books2scrape scrape-listing --limit-pages N   # phase 1 : pages de liste
uv run books2scrape scrape-details --limit N         # phase 2 : fiches produit
uv run books2scrape load                             # charge books.jsonl -> PostgreSQL
uv run books2scrape export                           # exporte en CSV
```

`--limit-pages` et `--limit` sont optionnels : sans eux, la commande traite
la totalité (50 pages, ou toutes les fiches restantes).

### Démontrer la reprise sur interruption

```bash
uv run books2scrape scrape-details
# ... laisser tourner quelques dizaines de secondes ...
# Ctrl+C
uv run books2scrape scrape-details
```

La seconde exécution affiche `Resume: N fiche(s) already collected, M to go`
et reprend exactement où la première s'est arrêtée — aucune fiche déjà
collectée n'est re-téléchargée.

### Autres commandes

```bash
uv run books2scrape status      # etat de la collecte (fichiers + base), sans rien lancer
uv run books2scrape init-db     # rejoue sql/schema.sql (idempotent, utile si le volume Docker existait deja)
uv run books2scrape --help      # liste complete des commandes
uv run books2scrape -v <cmd>    # logs detailles (DEBUG) en console
```

Les logs complets (niveau DEBUG, avec le module émetteur) sont toujours
écrits dans `logs/scrape.log`, quel que soit le niveau affiché en console.

### Interroger la base

```bash
docker compose exec db psql -U bouquineo -d bouquineo
```

Les requêtes répondant à la question centrale sont dans
[sql/questions.sql](sql/questions.sql) : distribution du stock, ruptures,
stock faible, meilleures notes, croisement stock faible + bien noté, et
contrôles de cohérence (UPC distincts, doublons éventuels).

## Technologies et justification

| Domaine | Choix | Pourquoi |
|---|---|---|
| Gestionnaire de projet | `uv` | Imposé par le brief. Gère l'environnement virtuel, les dépendances et leur verrouillage (`uv.lock`, versionné) — un clone du dépôt installe exactement les mêmes versions, sans étape manuelle. |
| Langage | Python 3.12 | Épinglé via `.python-version`. |
| HTTP | `requests` + `urllib3.Retry` | Réessais automatiques uniquement sur les erreurs **transitoires** (429, 5xx) ; un 404 n'est jamais réessayé, insister serait à la fois inutile et impoli. |
| Parsing HTML | `beautifulsoup4` + `lxml` | Le brief autorise aussi `scrapy` ; il n'a pas été retenu car son architecture (callbacks, pipelines) cacherait la logique de reprise à l'intérieur du framework, alors qu'elle doit rester explicite et défendable en soutenance. |
| Base de données | PostgreSQL 16 (Docker) | Imposé par le brief. |
| Accès base | `psycopg` 3 (sans ORM) | Les upserts sont du SQL explicite (`ON CONFLICT ... DO UPDATE`), plus court et plus facile à auditer en revue de code qu'une couche d'abstraction supplémentaire à ce périmètre (deux tables). |
| Modèles de données | `dataclasses` (stdlib) | Préférées à `pydantic` : le contrat de données est simple (deux structures), une dataclass se lit aussi facilement sans dépendance de plus. Les invariants réellement critiques (note entre 1 et 5, stock ≥ 0) sont de toute façon posés en `CHECK` SQL, à la source de vérité. |
| CLI | `argparse` (stdlib) | Aucune dépendance supplémentaire pour huit sous-commandes. |
| Conteneurisation | Docker Compose, `postgres:16-alpine` | Imposé par le brief. Volume nommé + healthcheck + montage du schéma en initialisation. |

## Architecture

Le scraper tourne **sur la machine hôte** (via `uv run`), seul PostgreSQL est
conteneurisé. Trois raisons à ce découpage :

1. La démonstration de reprise repose sur un Ctrl+C net : interrompre un
   process local est sans ambiguïté, alors qu'interrompre un conteneur pose
   la question de ce qui a réellement été arrêté.
2. `uv` est une exigence du brief ; le faire tourner sur l'hôte le montre
   directement, plutôt que de l'enterrer derrière un `docker run`.
3. Les fichiers JSONL et le CSV sont des livrables : en local, ils sont
   directement dans le dépôt, consultables (`wc -l data/books.jsonl`)
   pendant la démonstration sans avoir à extraire un volume Docker.

Le pipeline est découpé en deux étages indépendants :

```
Phase 1 (50 requêtes)      Phase 2 (1000 requêtes)         Chargement
listing.jsonl        -->   books.jsonl                --> PostgreSQL --> books.csv
(les 1000 URLs)            (append, une ligne à            (upsert sur
                             la fois, videe a chaque         l'UPC)
                             ecriture)
```

Le scraper **n'écrit jamais directement en base** : il produit un fichier,
et un script de chargement séparé fait les upserts. Conséquence directe :
la base peut être rechargée autant de fois que nécessaire sans re-scraper
le site, et une base momentanément indisponible ne fait perdre aucune
requête déjà payée au site du concurrent.

## Ce que dit robots.txt

`https://books.toscrape.com/robots.txt` renvoie une page **404** — le
fichier n'existe pas. Il n'autorise donc explicitement rien, mais
n'interdit rien non plus : son absence n'est pas traitée ici comme une
interdiction de collecter. Elle a en revanche une conséquence directe sur
la temporisation ci-dessous : il n'y a **aucun `Crawl-delay` publié** dont
le rythme des requêtes pourrait s'inspirer. Le choix repose entièrement sur
le raisonnement qui suit.

## Rythme des requêtes

**0,5 seconde entre deux requêtes**, mesurée depuis la fin de la requête
précédente (le délai s'ajoute donc au temps de réponse du serveur, il ne
l'absorbe pas). Réglable via `REQUEST_DELAY` dans `.env`.

Le total de la collecte est de **1050 requêtes** : 50 pages de liste + 1000
fiches produit. La catégorie de chaque livre est lue dans le fil d'Ariane de
sa fiche produit ("Home > Books > Poetry") : elle est donc gratuite, et il
n'est pas nécessaire de parcourir en plus les 50 pages de catégorie.

À 0,5 s par requête, la collecte complète prend environ 12 minutes — mesuré
en pratique à **12 min 09 s** pour les 1050 requêtes. Deux requêtes par
seconde reste dans l'ordre de grandeur d'un humain qui navigue rapidement
sur des pages HTML statiques, sans authentification ni protection
anti-robot à contourner. Un débit plus rapide n'apporterait aucun bénéfice
mesurable (12 minutes n'est pas un problème à résoudre) et exposerait
inutilement le site du concurrent à une charge inhabituelle ; un débit plus
lent ferait déborder la fenêtre d'une journée de formation sans raison.

Un **User-Agent explicite** est envoyé sur chaque requête
(`USER_AGENT` dans `.env`), identifiant le projet et fournissant un contact.

## Les deux clés (reprise et dédoublonnage)

Le brief pose la question : lequel du titre ou de l'UPC sert à reconnaître
un livre déjà collecté ? Réponse : **ni l'un ni l'autre à lui seul** — deux
clés différentes servent deux usages différents.

| Usage | Clé retenue | Pourquoi |
|---|---|---|
| Reprise du scraping (fichier JSONL) | `product_url` | C'est la seule information connue **avant** d'émettre la requête. L'UPC n'existe qu'après avoir téléchargé la fiche : s'en servir pour décider si une requête est nécessaire obligerait à faire cette requête. |
| Dédoublonnage en base (PostgreSQL) | `upc` (clé primaire) | Identifiant métier stable, contrairement au titre — deux livres différents peuvent porter le même titre, ce qui est précisément le problème remonté par la responsable des achats. |

Le titre n'est utilisé ni pour l'une ni pour l'autre.

## Reprise sur interruption

L'état de la collecte **est** le fichier `data/books.jsonl` lui-même, relu
au démarrage de chaque exécution — il n'existe ni curseur ni fichier de
point de reprise séparé. Trois raisons à ce choix :

1. **Un seul état, donc aucune désynchronisation possible.** Un curseur
   écrit à part pourrait mentir si l'interruption survient entre l'écriture
   d'une fiche et celle du curseur ; ici, si la ligne est dans le fichier,
   la fiche est collectée, point.
2. **Résistant au désordre.** La reprise reste correcte même si l'ordre de
   parcours change ou si `--limit` varie d'une exécution à l'autre.
3. Chaque fiche est écrite **immédiatement** dans le fichier, avec un
   vidage du tampon à chaque ligne (`flush()`) — sans quoi le tampon
   interne de Python retiendrait les dernières dizaines de fiches et les
   perdrait au moment précis d'un Ctrl+C.

Une fiche qui échoue (page introuvable, structure inattendue) est
journalisée dans `data/failures.jsonl` avec son URL et la raison, puis la
collecte continue — un échec isolé ne fait jamais tomber le lot. Si
**20 échecs consécutifs** surviennent (réglable via
`MAX_CONSECUTIVE_FAILURES`), la collecte s'arrête : ce compteur est
consécutif et non cumulé, car c'est ce qui distingue un site qui a changé
de structure ou qui est tombé, d'une poignée de fiches ponctuellement
anormales.

La phase 1 (pages de liste), elle, n'est **pas** reprenable : elle écrit son
résultat en une seule fois à la fin de son parcours. C'est un choix
délibéré — elle ne coûte que 50 requêtes et ~35 secondes, contre 1000
requêtes et ~12 minutes pour la phase 2 ; ajouter de la complexité de
reprise là où l'enjeu est cette faible n'aurait apporté aucun bénéfice
pratique.

## Schéma de base

Deux tables (voir [sql/schema.sql](sql/schema.sql), appliqué automatiquement
au premier démarrage du conteneur, et rejouable à tout moment via
`uv run books2scrape init-db`) :

- **`categories`** — `id`, `name` (unique). Remplie à la volée pendant le
  chargement, à partir du fil d'Ariane des fiches.
- **`books`** — clé primaire `upc` ; `product_url` en contrainte `UNIQUE`
  supplémentaire (empêche un doublon même si le site venait à servir deux
  UPC pour une même page) ; `stock_qty` et `availability_raw` conservés
  côte à côte pour garder la trace du texte brut d'où le nombre est extrait ;
  contraintes `CHECK` sur la note (1 à 5) et les compteurs (≥ 0).

Le chargement (`load.py`) utilise `INSERT ... ON CONFLICT (upc) DO UPDATE`
plutôt que `DO NOTHING` : recharger le même fichier deux fois ne crée aucun
doublon (testé sur les 1000 lignes : second chargement à `+0`), et un
rechargement met bien à jour le stock et les prix, ce qui correspond au
vrai besoin de veille de Bouquineo.

## Seuil retenu pour "stock faible"

La distribution réelle du stock sur les 1000 livres collectés (voir
`sql/questions.sql`, requête 0) montre **aucune rupture** (le minimum
observé est 1, jamais 0) et une répartition qui monte vite :

```
stock 1  ->  98 titres
stock 2  ->  14 titres
stock 3  --> 196 titres   (à lui seul, c'est 20 % du catalogue)
```

Le seuil retenu est **stock ≤ 2** (112 titres, 11 % du catalogue). Inclure
le palier 3 ferait à lui seul basculer près d'un tiers du catalogue dans la
catégorie "stock faible", ce qui viderait l'indicateur de son utilité pour
les achats.

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `uv: command not found` juste après l'installation | Le PATH utilisateur a été mis à jour, mais pas le terminal déjà ouvert | Fermer et rouvrir le terminal |
| `books2scrape check` échoue avec un message PostgreSQL après quelques secondes (jamais indéfiniment : `DB_CONNECT_TIMEOUT` borne l'attente) | Le conteneur n'est pas démarré | `docker compose up -d` puis `docker compose ps` (attendre `healthy`) |
| `psql` échoue avec un chemin du type `C:/Program Files/Git/docker-entrypoint-initdb.d/...` | Git Bash convertit les chemins absolus de type Unix | Préfixer la commande avec `MSYS_NO_PATHCONV=1` |
| `run` échoue à l'étape `scrape-details` avec "listing.jsonl is empty or missing" | La phase 1 n'a jamais été lancée, ou son fichier a été supprimé | Lancer `scrape-listing` (ou `run` en entier) avant `scrape-details` |
| Remettre la base à zéro pour rejouer une démonstration | — | `docker compose down -v` (supprime le volume, rejoue le schéma au prochain `up`), ou `TRUNCATE books, categories RESTART IDENTITY;` pour ne vider que les données |

## Auteur

Elie Lecas — formation Simplon.

# Note d'observation — prix, taxe, avis

## Ce qui a été constaté

Chaque fiche produit de `books.toscrape.com` affiche trois montants distincts
— **Price (excl. tax)**, **Price (incl. tax)**, **Tax** — et un compteur
**Number of reviews**. Avant de bâtir quoi que ce soit dessus, ces champs ont
été observés d'abord à l'œil sur une dizaine de fiches ouvertes dans le
navigateur et dans `robots.txt`/le code source HTML, puis vérifiés
systématiquement sur les **1000 livres** une fois chargés en base :

```sql
SELECT count(*) AS lignes,
       count(*) FILTER (WHERE price_excl_tax = price_incl_tax) AS ht_egal_ttc,
       count(*) FILTER (WHERE tax = 0)                         AS taxe_nulle,
       min(tax) AS taxe_min, max(tax) AS taxe_max
FROM books;
```

| lignes | HT = TTC | taxe nulle | taxe min | taxe max |
|---|---|---|---|---|
| 1000 | **1000** | **1000** | 0.00 | 0.00 |

Exemples pris au hasard dans la base, représentatifs de l'ensemble :

| Titre | Prix HT | Prix TTC | Taxe |
|---|---|---|---|
| Crazy Rich Asians | 49.13 | 49.13 | 0.00 |
| Memoirs of a Geisha | 49.67 | 49.67 | 0.00 |
| We Are Robin, Vol. 1 | 53.90 | 53.90 | 0.00 |
| Frostbite | 29.99 | 29.99 | 0.00 |

Sur les 1000 livres, **sans une seule exception** : le prix hors taxe est
strictement égal au prix TTC, et la taxe affichée vaut toujours 0,00 £. Les
prix eux-mêmes varient bien d'un livre à l'autre (de 10,00 £ à 59,99 £) : ce
n'est donc pas un champ figé à une constante par erreur de lecture, c'est
la taxe spécifiquement qui n'a jamais de valeur non nulle.

Même constat systématique sur **Number of reviews** : les 1000 livres
affichent `0`, sans exception, alors que la note (1 à 5 étoiles) varie bien
d'un livre à l'autre — encore une fois, ce n'est pas un champ qui a été mal
lu, c'est la donnée source qui ne varie pas.

## Ce qu'on en conclut

**Sur les prix et la taxe** : les trois champs sont **redondants** sur ce
site. Les libellés « hors taxe », « TTC » et « taxe » suggèrent une
mécanique fiscale, mais elle n'a ici aucune réalité — une seule valeur porte
l'information, les deux autres n'apportent rien. Conséquence directe pour
Bouquineo : bâtir un calcul de marge ou une comparaison sur l'écart entre
prix HT et prix TTC produirait systématiquement zéro, quel que soit le
livre. Les trois champs sont néanmoins collectés et stockés tels quels
(`price_excl_tax`, `price_incl_tax`, `tax` dans la table `books`) : si le
site venait à changer un jour, ce serait visible immédiatement sans
modification du collecteur.

**Sur le nombre d'avis** : la responsable des achats demandait quels titres
du concurrent sont *réellement commentés* par ses clients. Sur les 1000
livres de ce catalogue, **cette question n'a pas de réponse** — le champ
existe et est correctement collecté, mais il ne contient jamais qu'un zéro.
Ce n'est pas une limite du collecteur, c'est une limite de la donnée
source : `books.toscrape.com` est un catalogue de démonstration qui n'a
jamais reçu de vrais avis clients. Le dire explicitement évite de produire
un faux classement (« aucun livre commenté » n'est pas la même chose que
« tous les livres sont à égalité à zéro avis ») et signale que, sur un
véritable site concurrent, ce même champ serait probablement porteur
d'information.

**Recommandation** : ne rien construire en aval — indicateur de marge,
classement par popularité — sur les champs `tax` et `reviews_count` tant
qu'ils restent figés à cette valeur constante sur le catalogue observé.

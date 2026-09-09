-- Reponses a la question centrale du brief :
--   "Sur quels titres le concurrent est-il en rupture ou en stock faible,
--    et lesquels sont les mieux notes de son catalogue ?"
--
-- Usage en demonstration :
--   docker compose exec -T db psql -U bouquineo -d bouquineo -f /dev/stdin < sql/questions.sql
-- ou, requete par requete, dans une session interactive :
--   docker compose exec db psql -U bouquineo -d bouquineo


-- 0. D'ABORD la distribution, ENSUITE le seuil.
--    Ne fige pas une definition de "stock faible" avant d'avoir vu les 1000
--    valeurs : l'echantillon de reconnaissance ne montrait que du 19-22, ce
--    qui ne dit rien du catalogue complet.
SELECT stock_qty, count(*) AS nb_titres
FROM books
GROUP BY stock_qty
ORDER BY stock_qty;


-- 1. Ruptures : stock reel a zero.
--    Rappel : cette information n'existe PAS sur les pages de liste, qui
--    affichent "In stock" sans plus. Elle vient de la fiche produit.
SELECT b.title, c.name AS categorie, b.stock_qty, b.price_incl_tax
FROM books b
LEFT JOIN categories c ON c.id = b.category_id
WHERE b.stock_qty = 0
ORDER BY b.title;


-- 2. Stock faible. Ajuste le seuil apres avoir lu la requete 0, et dis dans
--    le README quel seuil tu as retenu et pourquoi.
SELECT b.title, c.name AS categorie, b.stock_qty, b.price_incl_tax
FROM books b
LEFT JOIN categories c ON c.id = b.category_id
WHERE b.stock_qty > 0 AND b.stock_qty <= 3
ORDER BY b.stock_qty, b.title;


-- 3. Les mieux notes du catalogue.
--    La note vient d'une classe CSS ("star-rating Three"), convertie en
--    entier a la collecte : c'est ce qui rend ce tri possible.
SELECT b.rating, c.name AS categorie, b.title, b.stock_qty, b.price_incl_tax
FROM books b
LEFT JOIN categories c ON c.id = b.category_id
WHERE b.rating = 5
ORDER BY c.name, b.title
LIMIT 50;


-- 4. Le croisement qui interesse vraiment les achats : bien note ET peu
--    disponible chez le concurrent. C'est la fenetre commerciale.
SELECT b.title, c.name AS categorie, b.rating, b.stock_qty, b.price_incl_tax
FROM books b
LEFT JOIN categories c ON c.id = b.category_id
WHERE b.rating >= 4 AND b.stock_qty <= 5
ORDER BY b.rating DESC, b.stock_qty;


-- 5. Controles de coherence a montrer en demonstration.
--    Le nombre d'UPC distincts doit egaler le nombre de lignes : c'est la
--    preuve que le rechargement ne duplique rien.
SELECT
    count(*)                                  AS lignes,
    count(DISTINCT upc)                       AS upc_distincts,
    count(DISTINCT product_url)               AS urls_distinctes,
    count(*) FILTER (WHERE stock_qty IS NULL) AS stock_manquant,
    count(*) FILTER (WHERE rating IS NULL)    AS note_manquante,
    count(*) FILTER (WHERE upc IS NULL)       AS upc_manquant
FROM books;


-- 6. Ce que la donnee source ne permet PAS de repondre.
--    La responsable des achats demandait quels titres sont "reellement
--    commentes". Verifie ici : si reviews_count est a 0 partout, la question
--    n'a pas de reponse sur ce catalogue, et ce n'est pas un defaut du
--    collecteur. Voir NOTE_OBSERVATION.md.
SELECT reviews_count, count(*) AS nb_titres
FROM books
GROUP BY reviews_count
ORDER BY reviews_count;


-- 7. Meme controle sur les prix : si tax est nulle et HT = TTC partout, les
--    trois champs sont redondants et aucun calcul de marge ne tient dessus.
SELECT
    count(*)                                                AS lignes,
    count(*) FILTER (WHERE price_excl_tax = price_incl_tax) AS ht_egal_ttc,
    count(*) FILTER (WHERE tax = 0)                         AS taxe_nulle,
    min(tax)                                                AS taxe_min,
    max(tax)                                                AS taxe_max
FROM books;

-- Bouquineo - schema de veille concurrentielle
-- Idempotent : rejouable sans erreur (monte dans docker-entrypoint-initdb.d
-- au premier demarrage, et applicable a la main via `init-db`).

CREATE TABLE IF NOT EXISTS categories (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS books (
    -- L'UPC est la cle metier : le titre ne l'est pas (deux livres peuvent
    -- porter le meme titre, c'est le probleme signale par les achats).
    upc              TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    category_id      INTEGER REFERENCES categories (id),

    -- Les trois champs sont collectes tels quels malgre leur redondance
    -- constatee (cf. NOTE_OBSERVATION.md) : s'ils changent, on le verra.
    price_excl_tax   NUMERIC(10, 2),
    price_incl_tax   NUMERIC(10, 2),
    tax              NUMERIC(10, 2),

    -- stock_qty vient de la fiche produit, absent des pages de liste.
    -- availability_raw garde le texte source pour pouvoir prouver l'extraction.
    stock_qty        INTEGER CHECK (stock_qty >= 0),
    availability_raw TEXT,

    rating           SMALLINT CHECK (rating BETWEEN 1 AND 5),
    reviews_count    INTEGER CHECK (reviews_count >= 0),
    description      TEXT,

    -- Cle de reprise du scraping : seule info connue AVANT la requete.
    -- UNIQUE en plus de la PK : bloque le doublon meme si le site servait
    -- deux UPC pour une meme page.
    product_url      TEXT NOT NULL UNIQUE,

    scraped_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index dictes par la question centrale du brief :
-- "quels titres en rupture ou stock faible, et lesquels sont les mieux notes"
CREATE INDEX IF NOT EXISTS idx_books_stock_qty ON books (stock_qty);
CREATE INDEX IF NOT EXISTS idx_books_rating    ON books (rating DESC);
CREATE INDEX IF NOT EXISTS idx_books_category  ON books (category_id);

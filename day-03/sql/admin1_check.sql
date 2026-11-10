-- Does each facility's stated Admin1 match the county its coordinates fall in?
-- Names are compared after lower-casing and stripping non-letters, "county"
-- and "city", so "Nairobi City" matches "Nairobi" and "Elgeyo-Marakwet"
-- matches "Elgeyo Marakwet".
WITH located AS (
    SELECT
        f.admin1 AS stated,
        c.shapeName AS located_in
    FROM facilities AS f
    JOIN counties AS c
        ON ST_Within(f.geometry, c.geometry)
),
normalised AS (
    SELECT
        stated,
        located_in,
        regexp_replace(lower(coalesce(stated, '')), '[^a-z]|county|city', '', 'g') AS stated_key,
        regexp_replace(lower(located_in), '[^a-z]|county|city', '', 'g') AS located_key
    FROM located
)
SELECT
    stated,
    located_in,
    stated_key = located_key AS agrees,
    count(*) AS n
FROM normalised
GROUP BY ALL
ORDER BY n DESC;

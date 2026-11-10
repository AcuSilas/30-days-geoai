-- Nearest other facility for every Kenyan facility, by brute force:
-- measure every pair, keep the closest. x_m and y_m are metres (EPSG:21037),
-- so straight-line (Euclidean) distance is valid.
WITH pairs AS (
    SELECT
        a.facility_id,
        b.facility_id AS other_id,
        sqrt(pow(a.x_m - b.x_m, 2) + pow(a.y_m - b.y_m, 2)) AS dist_m
    FROM facilities AS a
    JOIN facilities AS b
        ON a.facility_id <> b.facility_id
)
SELECT
    facility_id,
    arg_min(other_id, dist_m) AS nearest_id,
    min(dist_m) AS dist_m
FROM pairs
GROUP BY facility_id
ORDER BY facility_id;

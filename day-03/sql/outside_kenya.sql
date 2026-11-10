-- Facilities with Kenya labels but falling outside Kenya

SELECT
  f.facility_id,
  f.name,
  f.admin1,
  f.lon,
  f.lat,
f.ll_source
FROM facilities AS f
WHERE NOT EXISTS (
  SELECT 1
  FROM counties AS c
  WHERE ST_within(f.geometry, c.geometry)
)
ORDER BY f.admin1, f.name;

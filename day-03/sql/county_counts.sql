-- Public health facilities per County, by point-in-poygon spatial join
-- LEFT JOIN keeps counties with zero facilities in the result

SELECT
  c.shapeName AS county,
  count(f.facility_id) AS n_facilities
FROM counties as c
LEFT JOIN facilities AS f
  ON ST_Within(f.geometry, c.geometry)
GROUP BY c.shapeName
ORDER BY n_facilities DESC;

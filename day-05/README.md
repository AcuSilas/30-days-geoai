# Day 5: Sentinel-2 through STAC and Cloud-Optimized GeoTIFFs

**Track:** Earth observation / GIS · **Level:** Medium to hard · **Time:** ~3.5 hours

Two years of Sentinel-2 imagery over central Machakos, searched through a STAC catalog and
read straight from Cloud-Optimized GeoTIFFs on Microsoft's Planetary Computer, with no
files downloaded by hand. The result: cloud-masked monthly NDVI composites, vegetation
seasonality by land cover, and its relationship with Day 2's rainfall.

![Monthly NDVI composites](figures/ndvi_monthly_composites.png)

## What I built

- A STAC search for Sentinel-2 L2A scenes (Oct 2024 to Sep 2026, scene cloud under 50%)
- A per-scene check of the processing baseline, and a reflectance conversion that removes
  the +1000 offset ESA has applied since baseline 04.00
- A lazy `odc-stac` load of red, near-infrared and the scene classification layer at 100 m
  in UTM zone 37S, with clouds and shadows masked pixel by pixel
- Monthly median NDVI composites, with the number of clear looks behind each
- ESA WorldCover loaded onto the same grid (mode resampling), NDVI by land cover, and a
  comparison with CHIRPS rainfall from Day 2
- An exported Cloud-Optimized GeoTIFF of the clearest month

## Results

_Fill in with your numbers._

| Check | Result |
| --- | --- |
| Scenes found / distinct dates / MGRS tiles | _n / n / tiles_ |
| Processing baselines | _list_ |
| Median NDVI on the clearest day, without vs with the offset fix | _x vs y_ |
| Months with fewest clear looks | _months, and why_ |
| Land cover in the area (WorldCover) | _% cropland, grassland, ..._ |

**The offset trap.** _One or two sentences with your numbers: how far NDVI falls if the
+1000 offset is left in, and why a constant offset doesn't cancel in a ratio._

![NDVI by land cover vs rainfall](figures/ndvi_vs_rainfall.png)

_Interpretation: how each land-cover class responds to the long and short rains._

### Vegetation response to rainfall (cropland)

_Paste `ndvi_rain_lag.csv` here as a table._

_Caveat: 24 monthly points, and two rainy seasons a year make correlations at several lags
look strong. A description of this landscape, not a law._

## Reproduce

```bash
uv sync
uv run day-02/get_data.py     # CHIRPS cube, if not already built
uv run day-05/analysis.py     # streams from Planetary Computer; run from the repo root
```

The exported COG (`data/day-05/ndvi_machakos_YYYY_MM.tif`) is recreated by the last cell.

## Pitfalls

| Pitfall | Symptom | Fix |
| --- | --- | --- |
| Ignoring the +1000 offset (baseline 04.00+) | NDVI biased low, silently | Subtract 1000 per scene, by baseline |
| Deciding the offset by date | Reprocessed scenes mis-corrected | Use `s2:processing_baseline` |
| 0 treated as reflectance | Fake −0.1 values at edges | `where(dn > 0)` first |
| Trusting scene cloud cover | Clouds over the area in "clear" scenes | SCL mask per pixel, then a median |
| Averaging categorical rasters | Meaningless land-cover codes | `resampling="mode"` |
| Computing too early | Repeated downloads | Stay lazy; `.compute()` once |
| Full resolution for a large area | Gigabytes over a home connection | Coarser resolution, read from COG overviews |
| Mean composites | Missed clouds drag values down | Median, plus a count of looks |
| Expired access tokens | 403 errors mid-load | `patch_url=planetary_computer.sign`; rerun |
| Over-reading a lag correlation | Overconfident claims | Report n and the seasonal cycle |
| Small rasters written as COG | No overviews | Smaller `blocksize` |

## Cheatsheet

```python
import odc.stac, planetary_computer, pystac_client

catalog = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
items = catalog.search(collections=["sentinel-2-l2a"], bbox=(w, s, e, n),
                       datetime="2025-01-01/2025-12-31",
                       query={"eo:cloud_cover": {"lt": 50}}).item_collection()
item.properties["s2:processing_baseline"]        # decides the offset
item.assets["B04"].href                           # one band, as a COG

ds = odc.stac.load(items, bands=["B04", "B08", "SCL"], crs="EPSG:32737", resolution=100,
                   bbox=(w, s, e, n), groupby="solar_day", chunks={"x": 512, "y": 512},
                   patch_url=planetary_computer.sign)   # lazy until .compute()
other = odc.stac.load(other_items, bands=["map"], like=ds, resampling="mode")  # same grid
```

```python
reflectance = ((dn.where(dn > 0) - 1000) / 10_000).clip(min=0)   # baseline >= 04.00
ndvi = (nir - red) / (nir + red)
clear = scl.isin([4, 5, 6, 7])                    # vegetation, soil, water, unclassified
monthly = ndvi.resample(time="MS").median()       # composites
looks = ndvi.notnull().resample(time="MS").sum()  # reliability of each composite
da.rio.to_raster("out.tif", driver="COG", blocksize=128, compress="deflate")
```

| Sentinel-2 band | Name | Resolution |
| --- | --- | --- |
| B02, B03, B04 | Blue, green, red | 10 m |
| B08 | Near-infrared | 10 m |
| B05–B07, B8A | Red edge, narrow NIR | 20 m |
| B11, B12 | Shortwave infrared | 20 m |
| SCL | Scene classification | 20 m |

| NDVI | Typical surface |
| --- | --- |
| below 0 | Water |
| 0.1–0.2 | Bare soil, rock, built-up |
| 0.2–0.5 | Grassland, shrubs, growing crops |
| 0.6–0.9 | Dense, healthy vegetation |

## What I learned

_My answers to the check questions, in my own words._

1. The STAC hierarchy, with today's data as the example
2. The two COG features that make window reads possible
3. Why a +1000 offset lowers NDVI, with numbers, and what my data showed
4. Why decide by processing baseline, not date
5. Months with fewest clear looks, and why it matters
6. Mode for land cover, average or median for NDVI
7. NDVI decisions that would change a malaria model's covariate, and how to document them

## Data and credits

- Sentinel-2 L2A: contains modified Copernicus Sentinel data (2024–2026), processed by ESA,
  accessed via [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/).
- Land cover: ESA WorldCover (Zanaga et al.), CC BY 4.0, via Planetary Computer.
- Rainfall: CHIRPS v2.0 (Funk et al. 2015), via Day 2.
- Figures use the AHADI house style from `src/geokit/style.py`.

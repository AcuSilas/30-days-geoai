# %% Setup: run from the repo root
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import odc.stac
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import rioxarray  # noqa: F401  (registers the .rio accessor used for the COG export)
import xarray as xr

from geokit import style

style.use()  # AHADI house style for every figure below

CHIRPS = Path("data/day-02/chirps_kenya_monthly.nc")
DATA = Path("data/day-05")
OUT = Path("day-05")
FIGS = OUT / "figures"
for folder in (DATA, FIGS):
    folder.mkdir(parents=True, exist_ok=True)

CATALOG = "https://planetarycomputer.microsoft.com/api/stac/v1"
AOI = (37.15, -1.65, 37.55, -1.25)  # west, south, east, north: central Machakos, ~44 km
START, END = "2024-10-01", "2026-09-30"
CRS = "EPSG:32737"  # WGS 84 / UTM zone 37S, metres
RES = 100  # metres; coarse on purpose, see "Overviews"
MAX_CLOUD = 50  # % cloud over the whole scene, as reported by ESA
CLEAR_SCL = [4, 5, 6, 7]  # vegetation, bare soil, water, unclassified
LANDCOVER = {10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up"}
LANDCOVER_COLOURS = {  # one fixed colour per class, so every figure agrees
    "Tree cover": style.NAVY,
    "Shrubland": style.DARK_YELLOW,
    "Grassland": style.LIGHT_GREEN,
    "Cropland": style.GOLDEN_YELLOW,
    "Built-up": style.GRAY_BLUE,
}

odc.stac.configure_rio(cloud_defaults=True)  # GDAL settings for reading over HTTP

# %% Search the catalog: metadata only, no pixels yet
catalog = pystac_client.Client.open(CATALOG)
items = catalog.search(
    collections=["sentinel-2-l2a"],
    bbox=AOI,
    datetime=f"{START}/{END}",
    query={"eo:cloud_cover": {"lt": MAX_CLOUD}},
).item_collection()

scenes = pd.DataFrame(
    [
        {
            "date": item.datetime.date(),
            "tile": item.properties["s2:mgrs_tile"],
            "platform": item.properties["platform"],
            "cloud_pct": item.properties["eo:cloud_cover"],
            "baseline": item.properties["s2:processing_baseline"],
        }
        for item in items
    ]
)
print(f"{len(scenes)} scenes on {scenes['date'].nunique()} dates")
print(scenes.groupby(["tile", "platform"]).size().to_string())
print("processing baselines:", sorted(scenes["baseline"].unique()))

# %% Decide the offset from the processing baseline, never from the date
if (scenes["baseline"].astype(float) < 4.0).any():
    raise ValueError("pre-04.00 scenes found: their pixels have no offset, harmonise per scene")


def to_reflectance(dn: xr.DataArray) -> xr.DataArray:
    """Baseline >= 04.00 digital numbers to surface reflectance. 0 means no data."""
    return ((dn.where(dn > 0) - 1000) / 10_000).clip(min=0)


# %% Load lazily: a recipe for an array, not the array itself
ds = odc.stac.load(
    items,
    bands=["B04", "B08", "SCL"],
    crs=CRS,
    resolution=RES,
    bbox=AOI,
    groupby="solar_day",  # merge tiles captured on the same pass
    chunks={"x": 512, "y": 512},
    patch_url=planetary_computer.sign,  # sign each file at read time; tokens expire
)
print(ds)

# %% The offset trap, on one clear day
clear = ds["SCL"].isin(CLEAR_SCL)
best_day = clear.mean(("x", "y")).compute().idxmax("time")
day = ds.sel(time=best_day).compute()
ok = day["SCL"].isin(CLEAR_SCL) & (day["B04"] > 0)
raw = (day["B08"].astype("float64") - day["B04"]) / (day["B08"] + day["B04"].astype("float64"))
red, nir = to_reflectance(day["B04"]), to_reflectance(day["B08"])
fixed = (nir - red) / (nir + red)
print(
    f"{pd.Timestamp(best_day.values):%Y-%m-%d}: median NDVI without the offset fix "
    f"{float(raw.where(ok).median()):.3f}, with it {float(fixed.where(ok).median()):.3f}"
)

# %% NDVI for every pass, clouds masked (this is where the downloading happens)
red = to_reflectance(ds["B04"]).where(clear)
nir = to_reflectance(ds["B08"]).where(clear)
ndvi = ((nir - red) / (nir + red)).rename("ndvi")
ndvi = ndvi.where(np.isfinite(ndvi)).compute()
print(f"NDVI cube: {dict(ndvi.sizes)}")

# %% Monthly median composites, and how many clear looks built each pixel
monthly = ndvi.resample(time="MS").median()
looks = ndvi.notnull().resample(time="MS").sum()
looks_median = looks.median(("x", "y")).to_series()
print(looks_median.astype(int).to_string())

# %% Figure 1: the last 12 monthly composites
last12 = monthly.isel(time=slice(-12, None))
fig, axes = plt.subplots(3, 4, figsize=(14, 11), constrained_layout=True)
for ax, month in zip(axes.flat, last12["time"].values, strict=True):
    image = last12.sel(time=month).plot.imshow(
        ax=ax, cmap=style.VEGETATION, vmin=0, vmax=0.8, add_colorbar=False
    )
    n = int(looks_median[pd.Timestamp(month)])
    ax.set_title(f"{pd.Timestamp(month):%b %Y} ({n} clear looks)")
    ax.set_axis_off()
fig.colorbar(image, ax=axes, shrink=0.5, label="NDVI (monthly median)")
fig.suptitle("Central Machakos, Sentinel-2 NDVI monthly composites")
fig.savefig(FIGS / "ndvi_monthly_composites.png", dpi=200)
plt.show()

# %% Land cover from ESA WorldCover, on exactly the same grid
wc_items = catalog.search(collections=["esa-worldcover"], bbox=AOI).item_collection()

def item_year(item) -> int:
    """Year of a STAC item: its datetime, or the start of its date range."""
    return (item.datetime or item.common_metadata.start_datetime).year

latest = max(item_year(item) for item in wc_items)
wc_items = [item for item in wc_items if item_year(item) == latest]
landcover = (
    odc.stac.load(
        wc_items,
        bands=["map"],
        like=ds,  # same CRS, resolution and extent as the NDVI cube
        resampling="mode",  # categories: take the most common class, never an average
        patch_url=planetary_computer.sign,
    )["map"]
    .isel(time=0)
    .compute()
)
names = landcover.to_series().map(LANDCOVER).fillna("Other")
share = names.value_counts(normalize=True).mul(100).round(1)
print(f"WorldCover {latest}, % of pixels:\n{share.to_string()}")

# %% NDVI through the seasons, by land cover, against rainfall from Day 2
series = {
    name: monthly.where(landcover == code).median(("x", "y")).to_series()
    for code, name in LANDCOVER.items()
    if int((landcover == code).sum()) >= 500
}
west, south, east, north = AOI
rain = (
    xr.open_dataarray(CHIRPS)
    .sel(lon=slice(west, east), lat=slice(south, north))
    .mean(("lat", "lon"))
    .sel(time=slice(START, END))
    .to_series()
)

fig, ax = plt.subplots(figsize=(12, 5), constrained_layout=True)
ax_rain = ax.twinx()
ax_rain.bar(rain.index, rain.values, width=20, color=style.LIGHT_BLUE, label="Rainfall (CHIRPS)")
ax_rain.spines["right"].set_visible(True)  # the house style hides it; this axis needs it
ax_rain.set_ylabel("Rainfall (mm/month)")
for name, values in series.items():
    ax.plot(values.index, values.values, marker="o", color=LANDCOVER_COLOURS[name], label=name)
ax.set_zorder(ax_rain.get_zorder() + 1)
ax.patch.set_visible(False)
ax.set_ylabel("Median NDVI")
lines, labels = ax.get_legend_handles_labels()
bars, bar_labels = ax_rain.get_legend_handles_labels()
ax.legend(
    lines + bars, labels + bar_labels, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncols=6
)
ax.set_title("NDVI by land cover vs Rainfall, central Machakos")
fig.savefig(FIGS / "ndvi_vs_rainfall.png", dpi=200)
plt.show()

# %% How long does vegetation take to respond?
if "Cropland" in series:
    crop = series["Cropland"]
    lags = pd.Series({lag: crop.corr(rain.shift(lag)) for lag in range(4)}, name="r")
    lags.index.name = "rain_lag_months"
    print(lags.round(2).to_string())
    lags.round(3).to_csv(OUT / "ndvi_rain_lag.csv")

# %% Export the clearest month as a Cloud-Optimized GeoTIFF
clearest = looks_median.idxmax()
composite = monthly.sel(time=clearest).astype("float32").rio.write_crs(CRS)
cog = DATA / f"ndvi_machakos_{clearest:%Y_%m}.tif"
composite.rio.write_nodata(np.nan, inplace=True)
composite.rio.to_raster(cog, driver="COG", blocksize=128, compress="deflate")
with rasterio.open(cog) as src:
    print(cog.name, "| tiled:", src.profile["tiled"], "| overviews:", src.overviews(1))

# %% Setup:
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import odc.stac
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import rioxarray
import xarray as xr
from dask.config import PATH

CHIRPS = Path("data/day-02/chirps_kenya_monthly.nc")
DATA = Path("data/day-05")
OUT = Path("day-05")
FIGS = OUT / "figures"
for folder in (DATA, FIGS):
  folder.mkdir(parents=True, exist_ok=True)

CATALOG = "https://planetarycomputer.microsoft.com/api/stac/v1"
AOI = (37.15, -1.65, 37.55, -1.25)
START, END = "2024-10-01", "2026-09-30"
CRS = "EPSG:32737"
RES = 100
MAX_CLOUD = 50
CLEAR_SCL = [4, 5, 6, 7]
LANDCOVER = {10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up"}

odc.stac.configure_rio(cloud_defaults=True)

# %% Search the catalog: metadata only
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

# %% Load lazy
ds = odc.stac.load(
  items,
  bands=["B04", "B08", "SCL"],
  crs=CRS,
  resolution=RES,
  bbox=AOI,
  groupby="solar_day",
  chunks={"x": 512, "y": 512},
  patch_url=planetary_computer.sign,
)
print(ds)

#%% The offset trap
clear = ds[]

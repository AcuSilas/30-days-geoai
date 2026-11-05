"""Download CHIRPS v2 monthly rainfall for Kenya and Kenya's county boundaries.

Source: Digital Earth Africa's copy of the CHIRPS-2.0 Africa monthly product, stored
as Cloud-Optimized GeoTIFFs (COGs) in a public AWS S3 bucket in Cape Town. Because
the files are COGs, we read only the Kenya window of each month over HTTP instead of
downloading the whole continent. Months missing from the bucket are fetched directly
from the Climate Hazards Center, one at a time. Everything is stacked into one cube.
"""

import gzip
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
import rioxarray
import xarray as xr
from rasterio.io import MemoryFile

# GDAL settings for fast, resilient reads over HTTP
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

DATA = Path(__file__).resolve().parents[1] / "data" / "day-02"
MONTHLY_DIR = DATA / "chirps_kenya"

# Kenya's bounding box plus a small buffer, in degrees
WEST, EAST, SOUTH, NORTH = 33.5, 42.5, -5.0, 5.5
BUCKET = "https://deafrica-input-datasets.s3.af-south-1.amazonaws.com"
PREFIX = "rainfall_chirps_monthly/"
S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
DATE_IN_KEY = re.compile(r"((?:19|20)\d{2})[._/-]?(0[1-9]|1[0-2])")
CHC = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_monthly/tifs"
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/KEN/ADM1/"


def list_monthly_files() -> dict[pd.Timestamp, str]:
    """List the bucket's monthly CHIRPS GeoTIFFs as {first day of month: url}."""
    params = {"list-type": "2", "prefix": PREFIX}
    found: dict[pd.Timestamp, str] = {}
    while True:
        r = requests.get(BUCKET, params=params, timeout=60)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for key in root.iterfind("s3:Contents/s3:Key", S3_NS):
            name = key.text or ""
            match = DATE_IN_KEY.search(name.removeprefix(PREFIX))
            if name.lower().endswith(".tif") and match:
                month = pd.Timestamp(int(match[1]), int(match[2]), 1)
                found[month] = f"{BUCKET}/{name}"
        token = root.findtext("s3:NextContinuationToken", namespaces=S3_NS)
        if not token:
            return found
        params["continuation-token"] = token


def crop_to_kenya(da: xr.DataArray) -> xr.DataArray:
    """Clip a continental CHIRPS map to Kenya, in lat/lon at 0.05 degrees."""
    da = da.squeeze("band", drop=True)
    da = da.rio.clip_box(WEST, SOUTH, EAST, NORTH, crs="EPSG:4326").load()
    if da.rio.crs.to_epsg() != 4326:
        da = da.rio.reproject("EPSG:4326", resolution=0.05)
    return da


def save(da: xr.DataArray, dest: Path) -> None:
    """Write atomically: to .part first, renamed only once complete."""
    tmp = dest.with_name(dest.name + ".part")
    da.rio.to_raster(tmp, driver="GTiff", compress="deflate")
    tmp.rename(dest)
    print(f"{dest.stem} saved")


def get_month(item: tuple[pd.Timestamp, str], retries: int = 4) -> str:
    """Read the Kenya window of one monthly COG from the DE Africa bucket."""
    month, url = item
    dest = MONTHLY_DIR / f"{month:%Y-%m}.tif"
    if dest.exists():
        return "skip"
    for attempt in range(retries):
        try:
            da = crop_to_kenya(rioxarray.open_rasterio(url, masked=True))
            break
        except OSError as err:  # network and GDAL read errors
            wait = 5 * 2**attempt
            print(f"{month:%Y-%m}: retry {attempt + 1}/{retries} in {wait}s ({err})")
            time.sleep(wait)
    else:
        raise RuntimeError(f"failed after {retries} attempts: {url}")
    save(da, dest)
    return "saved"


def fill_from_chc(month: pd.Timestamp, pause: float = 10.0) -> str:
    """Fetch a month missing from the bucket directly from CHC, politely.

    CHC is a small academic server that rate-limits heavy users, so this runs one
    request at a time with a pause first, and gives up quietly if refused.
    """
    dest = MONTHLY_DIR / f"{month:%Y-%m}.tif"
    if dest.exists():
        return "skip"
    time.sleep(pause)
    try:
        r = requests.get(f"{CHC}/chirps-v2.0.{month:%Y.%m}.tif.gz", timeout=300)
    except requests.RequestException as err:
        print(f"{month:%Y-%m}: CHC unreachable ({err}); rerun later")
        return "refused"
    if r.status_code in (403, 429):
        print(f"{month:%Y-%m}: CHC refused ({r.status_code}); rerun later")
        return "refused"
    if r.status_code == 404:
        return "missing"
    r.raise_for_status()
    with MemoryFile(gzip.decompress(r.content)) as mem, mem.open() as src:
        da = crop_to_kenya(rioxarray.open_rasterio(src, masked=True))
    save(da, dest)
    return "saved"


def build_cube() -> Path:
    """Stack the monthly Kenya GeoTIFFs into one time x lat x lon NetCDF."""
    files = sorted(MONTHLY_DIR.glob("*.tif"))
    arrays = [rioxarray.open_rasterio(f).squeeze("band", drop=True).load() for f in files]
    times = pd.Index(pd.to_datetime([f.stem for f in files]), name="time")
    cube = xr.concat(arrays, dim=times, join="exact")  # every month must share one grid
    cube = cube.where(cube >= 0)  # nodata (-9999) becomes NaN
    cube = cube.rename({"x": "lon", "y": "lat"}).sortby("lat")
    cube = cube.drop_vars("spatial_ref", errors="ignore").rename("precipitation")
    # Make any remaining gaps explicit: a missing month becomes an all-NaN map
    full = pd.date_range(times.min(), times.max(), freq="MS", name="time")
    missing = [f"{m:%Y-%m}" for m in full if m not in times]
    cube = cube.reindex(time=full)
    cube.attrs = {
        "units": "mm/month",
        "source": "CHIRPS v2.0 monthly, CHC UCSB, via DE Africa (gaps filled from CHC)",
        "missing_months": ", ".join(missing) or "none",
    }
    print(f"cube months: {len(full)}, still missing: {missing or 'none'}")
    out = DATA / "chirps_kenya_monthly.nc"
    cube.to_netcdf(out)
    return out


if __name__ == "__main__":
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)

    available = list_monthly_files()
    if not available:
        raise SystemExit(f"no monthly .tif files found under {BUCKET}/{PREFIX}")
    wanted = {m: u for m, u in sorted(available.items()) if m >= pd.Timestamp("1991-01-01")}
    first, last = min(wanted), max(wanted)
    print(f"{len(wanted)} months available, {first:%Y-%m} to {last:%Y-%m}")
    print("example file:", wanted[first])

    expected = pd.date_range(first, last, freq="MS")
    gaps = [m for m in expected if m not in wanted]
    print(f"gaps in the bucket: {[f'{m:%Y-%m}' for m in gaps] or 'none'}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(get_month, wanted.items()))
    print(f"saved {results.count('saved')}, skipped {results.count('skip')}")

    # Fill the bucket's gaps from CHC: sequential, never parallel
    for month in gaps:
        print(f"{month:%Y-%m} from CHC: {fill_from_chc(month)}")
    print("cube:", build_cube())

    boundaries = DATA / "kenya_adm1.geojson"
    if not boundaries.exists():
        meta = requests.get(GEOBOUNDARIES_API, timeout=60).json()
        r = requests.get(meta["gjDownloadURL"], timeout=120)
        r.raise_for_status()
        boundaries.write_bytes(r.content)
        print("boundaries:", boundaries)

"""Download the sub-Saharan Africa public health facility list and write GeoParquet.

Source: Maina et al. (2019), Scientific Data 6:134, distributed on the Humanitarian
Data Exchange (HDX) as one ~5 MB Excel file, fetched once and cached.
"""

import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "day-03"
RAW = DATA / "ssa_health_facilities.xlsx"
DAY2_COUNTIES = ROOT / "data" / "day-02" / "kenya_adm1.geojson"
HDX_URL = (
    "https://data.humdata.org/dataset/eb1ba830-9464-43c8-9370-28cee0c99f5d/"
    "resource/758d5c17-88f4-42b2-9d4b-4bfe32d4acf7/download/"
    "sub-saharan_health_facilities.xlsx"
)
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/KEN/ADM1/"
KENYA_CRS = "EPSG:21037"  # Arc 1960 / UTM zone 37S: Kenya's projected CRS, in metres

# Start of each cleaned source column name -> our column name
COLUMNS = {
    "country": "country",
    "admin1": "admin1",
    "facility_n": "name",
    "facility_t": "facility_type",
    "ownership": "ownership",
    "lat": "lat",
    "long": "lon",
    "ll_source": "ll_source",
}


def download(url: str, dest: Path) -> Path:
    """Fetch url to dest once; later runs reuse the cached file."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(r.content)
    tmp.rename(dest)
    return dest


def standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Turn headers into snake_case, then map them onto our schema."""
    df = df.copy()
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )
    rename = {}
    for prefix, new in COLUMNS.items():
        matches = [c for c in df.columns if c.startswith(prefix)]
        if len(matches) != 1:
            raise KeyError(f"{prefix!r} matched {matches}; columns are {list(df.columns)}")
        rename[matches[0]] = new
    return df.rename(columns=rename)[list(COLUMNS.values())]


def split_valid(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate usable rows from rejected ones, recording why each was rejected."""
    df = df.assign(
        lat=pd.to_numeric(df["lat"], errors="coerce"),
        lon=pd.to_numeric(df["lon"], errors="coerce"),
    )
    missing = df["lat"].isna() | df["lon"].isna()
    # (0, 0) is "Null Island" in the Gulf of Guinea: missing coordinates saved as zeros
    null_island = (df["lat"] == 0) & (df["lon"] == 0)
    # A generous box around sub-Saharan Africa and its islands
    in_box = df["lat"].between(-35, 28) & df["lon"].between(-26, 64)
    reason = pd.Series(None, index=df.index, dtype="object")
    reason[missing] = "missing coordinates"
    reason[null_island] = "coordinates are (0, 0)"
    reason[~missing & ~null_island & ~in_box] = "outside sub-Saharan Africa box"
    rejected = df[reason.notna()].assign(reason=reason[reason.notna()])
    return df[reason.isna()], rejected


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    download(HDX_URL, RAW)

    t0 = time.perf_counter()
    raw = pd.read_excel(RAW)
    print(f"read {len(raw):,} rows from Excel in {time.perf_counter() - t0:.1f}s")

    df = standardise_columns(raw)
    df.insert(0, "facility_id", range(len(df)))  # stable id: the source row number
    valid, rejected = split_valid(df)
    print(f"valid: {len(valid):,}; rejected: {len(rejected):,}")
    if len(rejected):
        print(rejected.groupby(["country", "reason"]).size().to_string())
    rejected.to_csv(DATA / "rejected_rows.csv", index=False)

    ssa = gpd.GeoDataFrame(
        valid, geometry=gpd.points_from_xy(valid["lon"], valid["lat"]), crs="EPSG:4326"
    )
    ssa.to_parquet(DATA / "ssa_facilities.parquet", write_covering_bbox=True)

    kenya = ssa[ssa["country"] == "Kenya"].copy()
    if kenya.empty:
        raise SystemExit(f"no Kenya rows; countries are {sorted(ssa['country'].unique())}")
    metres = kenya.to_crs(KENYA_CRS).geometry
    kenya["x_m"], kenya["y_m"] = metres.x, metres.y
    kenya.to_parquet(DATA / "kenya_facilities.parquet", write_covering_bbox=True)
    print(f"Kenya: {len(kenya):,} facilities")

    if not DAY2_COUNTIES.exists():
        meta = requests.get(GEOBOUNDARIES_API, timeout=60).json()
        download(meta["gjDownloadURL"], DAY2_COUNTIES)
    counties = gpd.read_file(DAY2_COUNTIES)[["shapeName", "shapeISO", "geometry"]]
    counties.to_parquet(DATA / "kenya_counties.parquet", write_covering_bbox=True)
    print(f"counties: {len(counties)}")

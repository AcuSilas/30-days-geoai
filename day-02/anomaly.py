"""Reusable functions for monthly rainfall anomalies."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import regionmask
import xarray as xr


def load_chirps(path: Path) -> xr.DataArray:
    """Open the Kenya CHIRPS cube built by get_data.py (mm/month) and check it."""
    pr = xr.open_dataarray(path)
    if pr.attrs.get("units") != "mm/month":
        raise ValueError(f"unexpected units: {pr.attrs.get('units')}")
    if not pr.indexes["lat"].is_monotonic_increasing:
        raise ValueError("latitude must run south to north")
    return pr

def monthly_climatology(
    pr: xr.DataArray, start: str = "1991-01-01", end: str = "2020-12-31"
) -> tuple[xr.DataArray, xr.DataArray]:
    """Per-pixel mean and standard deviation for each calendar month.

    Defaults to the WMO 1991-2020 normal period.
    """
    base = pr.sel(time=slice(start, end))
    n_years = base.sizes["time"] / 12
    if n_years < 30:
        raise ValueError(f"baseline has only {n_years:.1f} years of data")
    by_month = base.groupby("time.month")
    return by_month.mean("time"), by_month.std("time")


def standardized_anomaly(
    pr: xr.DataArray,
    clim_mean: xr.DataArray,
    clim_std: xr.DataArray,
    min_std: float = 1.0,
    min_mean: float = 10.0,
) -> xr.DataArray:
    """(rainfall - monthly mean) / monthly std, for every pixel and month.
    NaN where the month is normally near-dry (mean < min_mean mm) or barely
    varies (std < min_std mm): there, a few mm of rain gives a huge but
    meaningless z-score.
    """
    valid = (clim_std >= min_std) & (clim_mean >= min_mean)
    anom = pr.groupby("time.month") - clim_mean
    z = anom.groupby("time.month") / clim_std.where(valid)
    return z.drop_vars("month").rename("z_anomaly")


def percent_of_normal(
    pr: xr.DataArray, clim_mean: xr.DataArray, min_mean: float = 5.0
) -> xr.DataArray:
    """Rainfall as % of the monthly normal; NaN where the normal is under min_mean mm."""
    safe_mean = clim_mean.where(clim_mean >= min_mean)
    pct = pr.groupby("time.month") / safe_mean * 100
    return pct.drop_vars("month").rename("pct_of_normal")

def county_means(
    da: xr.DataArray, counties: gpd.GeoDataFrame, name_col: str = "shapeName"
) -> xr.DataArray:
    """Area-weighted mean of da over each polygon, by pixel-centre masking."""
    regions = regionmask.from_geopandas(counties, names=name_col, overlap=False)
    mask = regions.mask_3D(da.lon, da.lat)  # region x lat x lon, True inside
    n_pixels = mask.sum(("lat", "lon"))
    if int(n_pixels.min()) == 0:
        empty = list(mask.names.values[(n_pixels == 0).values])
        raise ValueError(f"counties with no pixel centres: {empty}")
    weights = mask * np.cos(np.deg2rad(da.lat))
    return da.weighted(weights).mean(("lat", "lon"))

def seasonal_anomaly(
    pr: xr.DataArray, months: list[int], start: int = 1991, end: int = 2020
) -> xr.DataArray:
    """Standardized anomaly of seasonal rainfall totals, one value per pixel per year.

    Only for seasons inside one calendar year (e.g. MAM, OND). A season with any
    missing month is NaN rather than an undercount.
    """
    season = pr.sel(time=pr.time.dt.month.isin(months))
    totals = season.groupby("time.year").sum("time", min_count=len(months))
    base = totals.sel(year=slice(start, end))
    z = (totals - base.mean("year")) / base.std("year")
    return z.rename("z_season")

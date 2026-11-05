# %% Setup: always run from the repo root
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, "day-02")
import anomaly as an

DATA = Path("data/day-02")
FIGS = Path("day-02/figures")

# %% Load and inspect
pr = an.load_chirps(DATA / "chirps_kenya_monthly.nc")
print(pr)
print("first, last:", pr.time.values[[0, -1]])
print("min, max mm:", float(pr.min()), float(pr.max()))
print("missing months:", pr.attrs["missing_months"])  # all-NaN maps, by design

# No missing months?
expected = pd.date_range(pr.time.values[0], pr.time.values[-1], freq="MS")
assert len(expected) == pr.sizes["time"], "gap in the monthly series"

# %% Look at one month
pr.sel(time="2023-11").squeeze().plot(cmap="YlGnBu", robust=True)
plt.title("CHIRPS rainfall, November 2023 (mm)")
plt.show()

# %% Climatology
clim_mean, clim_std = an.monthly_climatology(pr)
print(clim_mean.sizes)  # predict: month 12, lat ~210, lon ~180

clim_mean.plot(col="month", col_wrap=4, cmap="YlGnBu", robust=True)
plt.suptitle("1991-2020 mean monthly rainfall (mm)", y=1.02)
plt.savefig(FIGS / "climatology_by_month.png", dpi=150, bbox_inches="tight")
plt.show()

# %% Anomalies
z = an.standardized_anomaly(pr, clim_mean, clim_std)
pct = an.percent_of_normal(pr, clim_mean)

# Sanity check: over the baseline, z should average ~0 with std ~1
base_z = z.sel(time=slice("1991", "2020"))
print("baseline mean:", float(base_z.mean()), "std:", float(base_z.std()))

# %% County averages
counties = gpd.read_file(DATA / "kenya_adm1.geojson")
print(len(counties), "units;", counties.crs)

county_z = an.county_means(z, counties)
df = (
    county_z.to_dataframe(name="z_anomaly")
    .reset_index()[["time", "names", "z_anomaly"]]
    .rename(columns={"names": "county"})
)
df.to_csv(DATA / "county_z_anomaly.csv", index=False)
df.tail()

# %% Small multiples: last 12 months
last = df["time"].max()
recent = df[df["time"] > last - pd.DateOffset(months=12)]
fig, axes = plt.subplots(3, 4, figsize=(14, 12), constrained_layout=True)
for ax, (month, g) in zip(axes.flat, recent.groupby("time"), strict=True):
    counties.merge(g, left_on="shapeName", right_on="county").plot(
        column="z_anomaly", cmap="BrBG", vmin=-2.5, vmax=2.5, ax=ax,
        edgecolor="white", linewidth=0.2, missing_kwds={"color": "lightgrey"},
    )
    ax.set_title(month.strftime("%b %Y"))
    ax.set_axis_off()
sm = plt.cm.ScalarMappable(cmap="BrBG", norm=plt.Normalize(-2.5, 2.5))
fig.colorbar(sm, ax=axes, shrink=0.5, label="Standardized anomaly vs 1991-2020 (σ)")
fig.suptitle("Kenya county rainfall anomalies, last 12 months (CHIRPS v2)")
fig.savefig(FIGS / "county_anomalies_last12.png", dpi=200)
plt.show()

# %% Validation, by season: do known droughts and floods show up?
pick = ["Mandera", "Wajir", "Marsabit"]
seasons = {
    "MAM long rains": ([3, 4, 5], (2020.5, 2022.5)),  # failed: 2021, 2022
    "OND short rains": ([10, 11, 12], (2019.5, 2022.5)),  # failed: 2020-2022
}
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, constrained_layout=True)
for ax, (label, (months, drought)) in zip(axes, seasons.items(), strict=True):
    zs = an.county_means(an.seasonal_anomaly(pr, months), counties)
    table = zs.to_dataframe(name="z").reset_index()
    table = table.pivot(index="year", columns="names", values="z")
    table.loc[2019:, pick].plot(ax=ax, marker="o")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvspan(*drought, color="tan", alpha=0.25, label="2020-22 drought")
    ax.set_title(label)
    ax.set_ylabel("Seasonal z")
    ax.legend(loc="upper left")
fig.suptitle("Seasonal rainfall anomalies in north-eastern Kenya (vs 1991-2020)")
fig.savefig(FIGS / "validation_northeast.png", dpi=200, bbox_inches="tight")
plt.show()

# %% Diagnose: real extremes or dry-month artefacts?
def county_table(da, name):
    return an.county_means(da, counties).to_dataframe(name=name).reset_index()

rain = county_table(pr, "rain_mm")
rain["month"] = rain["time"].dt.month
normal = county_table(clim_mean, "normal_mm")[["month", "names", "normal_mm"]]
spread = county_table(clim_std, "std_mm")[["month", "names", "std_mm"]]

diag = rain.merge(normal, on=["month", "names"]).merge(spread, on=["month", "names"])
diag["pct_of_normal"] = 100 * diag["rain_mm"] / diag["normal_mm"]
suspects = diag["names"].isin(["Wajir", "Mandera", "Turkana"]) & diag["time"].isin(
    pd.to_datetime(["2026-02-01", "2026-03-01", "2026-08-01", "2026-09-01"])
)
print(diag[suspects].round(1).to_string(index=False))

top = pr.where(pr >= 1000, drop=True).stack(p=("time", "lat", "lon")).dropna("p")
print(diag[suspects].to_string(index=False, float_format="%.1f"))
# %% How dry can z even go? Floor = z for a season with zero rain
season = pr.sel(time=pr.time.dt.month.isin([10, 11, 12]))
totals = season.groupby("time.year").sum("time", min_count=3).sel(year=slice(1991, 2020))
floor = an.county_means(-totals.mean("year") / totals.std("year"), counties)
floor_table = floor.to_dataframe(name="z_floor").reset_index()
print(floor_table[floor_table["names"].isin(pick)][["names", "z_floor"]].round(2))

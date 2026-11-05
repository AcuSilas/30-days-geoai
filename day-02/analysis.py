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

# %% Validation: do known droughts and floods show up?
pick = ["Mandera", "Wajir", "Marsabit"]
ts = df[df["county"].isin(pick) & (df["time"] >= "2019-01")]
ts = ts.pivot(index="time", columns="county", values="z_anomaly")
smooth = ts.rolling(3, min_periods=2).mean()

fig, ax = plt.subplots(figsize=(11, 4))
for county in smooth.columns:
    ax.plot(smooth.index, smooth[county], label=county)
ax.axhline(0, color="black", linewidth=0.8)
ax.axvspan(
    pd.Timestamp("2020-10-01"), pd.Timestamp("2022-12-31"),
    color="tan", alpha=0.25, label="2020-22 drought",
)
ax.set_ylabel("3-month mean z")
ax.set_title("Rainfall anomalies in north-eastern Kenya")
ax.legend()
fig.savefig(FIGS / "validation_northeast.png", dpi=200, bbox_inches="tight")
plt.show()

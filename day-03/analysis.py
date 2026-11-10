# %% Setup: run from the repo root
import time
from collections.abc import Callable
from pathlib import Path

import duckdb
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

DATA = Path("data/day-03")
SQL = Path("day-03/sql")
FIGS = Path("day-03/figures")
FIGS.mkdir(parents=True, exist_ok=True)
FAC = (DATA / "kenya_facilities.parquet").as_posix()
CTY = (DATA / "kenya_counties.parquet").as_posix()

con = duckdb.connect()
con.install_extension("spatial")
con.load_extension("spatial")
con.sql(f"CREATE OR REPLACE VIEW facilities AS SELECT * FROM '{FAC}'")
con.sql(f"CREATE OR REPLACE VIEW counties AS SELECT * FROM '{CTY}'")


def run(name: str) -> pd.DataFrame:
    """Run day-03/sql/<name>.sql against the views and return a DataFrame."""
    return con.sql((SQL / f"{name}.sql").read_text()).df()


def best_of(fn: Callable[[], object], n: int = 3) -> float:
    """Fastest of n timed runs, in seconds: the least noisy estimate."""
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times)


# %% What does DuckDB see? The geometry column should be GEOMETRY, not BLOB
print(con.sql("DESCRIBE facilities"))

# %% Formats: same data, different files
ssa = gpd.read_parquet(DATA / "ssa_facilities.parquet")
ssa.to_file(DATA / "ssa_facilities.gpkg", driver="GPKG")
ssa.drop(columns="geometry").to_csv(DATA / "ssa_facilities.csv", index=False)

pq = (DATA / "ssa_facilities.parquet").as_posix()
formats = {
    "Excel (.xlsx)": (
        DATA / "ssa_health_facilities.xlsx",
        lambda: pd.read_excel(DATA / "ssa_health_facilities.xlsx"),
        1,  # slow: time it once
    ),
    "CSV": (DATA / "ssa_facilities.csv", lambda: pd.read_csv(DATA / "ssa_facilities.csv"), 3),
    "GeoPackage": (
        DATA / "ssa_facilities.gpkg",
        lambda: gpd.read_file(DATA / "ssa_facilities.gpkg"),
        3,
    ),
    "GeoParquet, all columns": (
        DATA / "ssa_facilities.parquet",
        lambda: gpd.read_parquet(DATA / "ssa_facilities.parquet"),
        3,
    ),
    "GeoParquet, 2 columns (DuckDB)": (
        DATA / "ssa_facilities.parquet",
        lambda: con.sql(f"SELECT country, facility_type FROM '{pq}'").df(),
        3,
    ),
}
format_table = pd.DataFrame(
    [
        (label, path.stat().st_size / 1e6, best_of(reader, n))
        for label, (path, reader, n) in formats.items()
    ],
    columns=["format", "size_mb", "read_seconds"],
)
print(format_table.round(3).to_string(index=False))

# %% Facilities per county: a spatial join in SQL
counts = run("county_counts")
print(counts.head(10).to_string(index=False))
print("facilities located in a county:", counts["n_facilities"].sum())

# %% Data quality 1: facilities that land in no county
outside = run("outside_kenya")
print(f"{len(outside)} facilities fall outside every county")
print(outside.head(15).to_string(index=False))

# %% Data quality 2: does the stated Admin1 match the location?
check = run("admin1_check")
rate = check.loc[check["agrees"], "n"].sum() / check["n"].sum()
print(f"Admin1 matches the location for {rate:.1%} of located facilities")
print(check[~check["agrees"]].head(15).to_string(index=False))


# %% Nearest neighbour, two ways
def kdtree_nn(df: pd.DataFrame) -> pd.DataFrame:
    """Nearest other facility for each row, using a KD-tree on metre coordinates."""
    xy = df[["x_m", "y_m"]].to_numpy()
    dist, idx = cKDTree(xy).query(xy, k=2)  # k=1 would just find each point itself
    ids = df["facility_id"].to_numpy()
    return pd.DataFrame({"facility_id": ids, "nearest_id": ids[idx[:, 1]], "dist_m": dist[:, 1]})


ke = pd.read_parquet(FAC, columns=["facility_id", "name", "facility_type", "x_m", "y_m"])
nn_sql = run("nearest_neighbour")
nn_kd = kdtree_nn(ke)

both = nn_sql.merge(nn_kd, on="facility_id", suffixes=("_sql", "_kd"))
assert len(both) == len(ke), "a facility is missing from one method"
assert np.allclose(both["dist_m_sql"], both["dist_m_kd"]), "the two methods disagree"
print(nn_kd["dist_m"].describe(percentiles=[0.1, 0.5, 0.9]).round(0))

# %% Data quality 3: facilities sharing the same spot
dupes = nn_kd[nn_kd["dist_m"] < 1].merge(ke, on="facility_id")
print(f"{len(dupes)} facilities have another facility within 1 m")
print(dupes[["facility_id", "name", "facility_type", "nearest_id"]].head(20).to_string(index=False))


# %% Benchmark: same answers, different engines
def geopandas_counts() -> pd.Series:
    facilities = gpd.read_parquet(FAC)
    counties = gpd.read_parquet(CTY)
    joined = gpd.sjoin(facilities, counties[["shapeName", "geometry"]], predicate="within")
    return joined.groupby("shapeName").size()


located = geopandas_counts()
sql_located = counts.set_index("county")["n_facilities"]
assert located.reindex(sql_located.index, fill_value=0).equals(sql_located), "counts differ"

bench = pd.DataFrame(
    [
        ("county counts", "DuckDB SQL", best_of(lambda: run("county_counts"))),
        ("county counts", "geopandas sjoin", best_of(geopandas_counts)),
        ("nearest neighbour", "DuckDB brute force", best_of(lambda: run("nearest_neighbour"))),
        ("nearest neighbour", "SciPy KD-tree", best_of(lambda: kdtree_nn(ke))),
    ],
    columns=["task", "method", "seconds"],
)
print(bench.round(3).to_string(index=False))
bench.to_csv("day-03/benchmark.csv", index=False)
format_table.to_csv("day-03/formats.csv", index=False)

# %% Figure: where the facilities are, and how far apart
county_map = gpd.read_parquet(CTY).merge(counts, left_on="shapeName", right_on="county")
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6), constrained_layout=True)
county_map.plot(
    column="n_facilities",
    cmap="viridis",
    legend=True,
    ax=ax1,
    edgecolor="white",
    linewidth=0.3,
    legend_kwds={"label": "Public health facilities", "shrink": 0.7},
)
ax1.set_title("Facilities per county (raw counts)")
ax1.set_axis_off()

km = nn_kd["dist_m"].clip(lower=10) / 1000  # 0 m duplicates land in the first bin
ax2.hist(km, bins=np.logspace(-2, 2.5, 50), color="#2f6690")
ax2.set_xscale("log")
ax2.set_xlabel("Distance to the nearest other facility (km, log scale)")
ax2.set_ylabel("Facilities")
for q, style in ((0.5, "--"), (0.9, ":")):
    v = km.quantile(q)
    label = f"{q:.0%} of facilities within {v:.1f} km"
    ax2.axvline(v, color="black", linestyle=style, linewidth=1, label=label)
n_close = int((km <= 0.01).sum())  # within 10 m of another facility
ax2.annotate(
    f"{n_close} within 10 m",
    xy=(0.011, n_close),
    xytext=(0.03, n_close + 0.25 * ax2.get_ylim()[1]),
    arrowprops={"arrowstyle": "->"},
)
ax2.legend(loc="upper left", frameon=False)
ax2.set_title("How far apart are facilities?")
fig.suptitle("Kenya's public health facilities (Maina et al. 2019)")
fig.savefig(FIGS / "kenya_facilities.png", dpi=200)
plt.show()

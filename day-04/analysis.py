# %% Setup: run from the repo root
from pathlib import Path

import geopandas as gpd
import h3
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pydeck as pdk
import rasterio
from matplotlib.colors import LogNorm
from rasterio.mask import mask
from shapely.geometry import Polygon

POP = Path("data/day-04/ken_pop_2026_100m.tif")
FAC = Path("data/day-03/kenya_facilities.parquet")
CTY = Path("data/day-03/kenya_counties.parquet")
OUT = Path("day-04")
FIGS = OUT / "figures"
FIGS.mkdir(parents=True, exist_ok=True)

RESOLUTIONS = (7, 8, 9)
ACCESS_KM = 2.0  # "a facility within about 2 km"

counties = gpd.read_parquet(CTY)
facilities = gpd.read_parquet(FAC)

# %% Inspect the raster before using it
with rasterio.open(POP) as src:
    print("CRS:", src.crs, "| pixel size:", src.res, "| shape:", src.shape)
    print("nodata:", src.nodata, "| dtype:", src.dtypes[0])


# %% Total population, read block by block
def raster_total(path: Path) -> float:
    """Sum a raster without loading it all into memory, skipping nodata."""
    total = 0.0
    with rasterio.open(path) as src:
        for _, window in src.block_windows(1):
            block = src.read(1, window=window, masked=True)
            total += float(block.filled(0).sum(dtype="float64"))
    return total


kenya_total = raster_total(POP)
print(f"Kenya total population: {kenya_total:,.0f}")


# %% Population per county (zonal sums), and facilities per 10,000 people
def zonal_sum(path: Path, gdf: gpd.GeoDataFrame, name_col: str = "shapeName") -> pd.Series:
    """Sum raster values whose pixel centres fall inside each polygon."""
    sums = {}
    with rasterio.open(path) as src:
        shapes = gdf.to_crs(src.crs)
        for name, geom in zip(shapes[name_col], shapes.geometry, strict=True):
            data, _ = mask(src, [geom], crop=True, filled=False)  # reads only this window
            sums[name] = float(data.filled(0).sum(dtype="float64"))
    return pd.Series(sums, name="population")


county_pop = zonal_sum(POP, counties)
gap = 100 * (kenya_total - county_pop.sum()) / kenya_total
print(f"counties hold {county_pop.sum():,.0f} people; {gap:.2f}% of the raster total is outside")

located = gpd.sjoin(facilities, counties[["shapeName", "geometry"]], predicate="within")
county_fac = located.groupby("shapeName").size().rename("facilities")
per_capita = pd.concat([county_pop, county_fac], axis=1).fillna({"facilities": 0})
per_capita["per_10k"] = 1e4 * per_capita["facilities"] / per_capita["population"]
per_capita["people_per_facility"] = per_capita["population"] / per_capita["facilities"]
per_capita = per_capita.sort_values("per_10k")
print(per_capita.round(1).head(5).to_string())
print(per_capita.round(1).tail(5).to_string())
per_capita.round(2).to_csv(OUT / "county_per_capita.csv", index_label="county")


# %% Figure 1: raw counts vs facilities per 10,000 people
county_map = counties.merge(per_capita, left_on="shapeName", right_index=True)
fig, axes = plt.subplots(1, 2, figsize=(12, 6), constrained_layout=True)
panels = [
    ("facilities", "Facilities per county (raw counts)", "viridis"),
    ("per_10k", "Facilities per 10,000 people", "viridis"),
]
for ax, (column, title, cmap) in zip(axes, panels, strict=True):
    county_map.plot(
        column=column,
        cmap=cmap,
        legend=True,
        ax=ax,
        edgecolor="white",
        linewidth=0.3,
        legend_kwds={"shrink": 0.6},
    )
    ax.set_title(title)
    ax.set_axis_off()
fig.suptitle("Same facilities, different story: counts vs per-person rates (WorldPop 2026)")
fig.savefig(FIGS / "counts_vs_per_capita.png", dpi=200)
plt.show()


# %% Nairobi: populated pixels as points
nairobi = counties[counties["shapeName"] == "Nairobi"]
assert len(nairobi) == 1, "expected exactly one county called Nairobi"
with rasterio.open(POP) as src:
    data, transform = mask(src, list(nairobi.to_crs(src.crs).geometry), crop=True, filled=False)
band = data[0]
rows, cols = np.nonzero(~np.ma.getmaskarray(band) & (band.filled(0) > 0))
xs, ys = rasterio.transform.xy(transform, rows, cols)  # pixel centres
pixels = pd.DataFrame({"lon": xs, "lat": ys, "pop": band.data[rows, cols].astype("float64")})
print(f"{len(pixels):,} populated pixels; {pixels['pop'].sum():,.0f} people in Nairobi")

nbi_fac = located[located["shapeName"] == "Nairobi"][["facility_id", "name", "lon", "lat"]]
print(f"{len(nbi_fac)} public facilities in Nairobi")


# %% Aggregate to H3 hexagons at three resolutions
def to_h3(df: pd.DataFrame, res: int) -> list[str]:
    """H3 cell id for every row's lat/lon at one resolution."""
    return [h3.latlng_to_cell(lat, lon, res) for lat, lon in zip(df["lat"], df["lon"], strict=True)]


hexes = {}
for res in RESOLUTIONS:
    pop_h = pixels.assign(cell=to_h3(pixels, res)).groupby("cell")["pop"].sum()
    fac_h = nbi_fac.assign(cell=to_h3(nbi_fac, res)).groupby("cell").size().rename("facilities")
    hexes[res] = pd.concat([pop_h, fac_h], axis=1).fillna(0)
    assert np.isclose(hexes[res]["pop"].sum(), pixels["pop"].sum()), "population was lost"


# %% The modifiable areal unit problem (MAUP), measured
def share_unserved(table: pd.DataFrame, k: int) -> float:
    """Share of people whose hexagon has no facility within k rings of neighbours."""
    has_facility = set(table.index[table["facilities"] > 0])
    served = [any(n in has_facility for n in h3.grid_disk(cell, k)) for cell in table.index]
    return 1 - table.loc[served, "pop"].sum() / table["pop"].sum()


maup = []
for res, table in hexes.items():
    spacing_km = np.sqrt(3) * h3.average_hexagon_edge_length(res, unit="km")  # centre to centre
    k = max(1, round(ACCESS_KM / spacing_km))
    maup.append(
        {
            "resolution": res,
            "hex_area_km2": round(h3.average_hexagon_area(res, unit="km^2"), 3),
            "hexagons": len(table),
            "pct_unserved_same_hex": round(100 * share_unserved(table, 0), 1),
            "rings_for_2km": k,
            "pct_unserved_within_2km": round(100 * share_unserved(table, k), 1),
        }
    )
maup = pd.DataFrame(maup)
print(maup.to_string(index=False))
maup.to_csv(OUT / "maup.csv", index=False)


# %% Figure 2: the same people, three hexagon sizes
def hex_frame(table: pd.DataFrame) -> gpd.GeoDataFrame:
    """Hexagon polygons with their attributes, ready to plot."""
    polygons = [Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(c)]) for c in table.index]
    return gpd.GeoDataFrame(table.reset_index(names="cell"), geometry=polygons, crs="EPSG:4326")


fig, axes = plt.subplots(1, 3, figsize=(15, 5.5), constrained_layout=True)
norm = LogNorm(vmin=10, vmax=max(t["pop"].max() for t in hexes.values()))
for ax, (res, table) in zip(axes, hexes.items(), strict=True):
    frame = hex_frame(table[table["pop"] > 0])
    frame.plot(column="pop", cmap="magma", norm=norm, ax=ax, linewidth=0)
    nairobi.boundary.plot(ax=ax, color="black", linewidth=0.6)
    area = h3.average_hexagon_area(res, unit="km^2")
    ax.set_title(f"Resolution {res}: about {area:.2f} km² per hexagon")
    ax.set_axis_off()
sm = plt.cm.ScalarMappable(cmap="magma", norm=norm)
fig.colorbar(sm, ax=axes, shrink=0.6, label="People per hexagon (log scale)")
fig.suptitle("Nairobi's population on H3 hexagons (WorldPop 2026)")
fig.savefig(FIGS / "nairobi_h3_resolutions.png", dpi=200)
plt.show()


# %% Interactive map (resolution 8): open day-04/nairobi_h3.html in a browser
t8 = hexes[8].reset_index(names="cell")
t8["people"] = t8["pop"].round().astype(int)
t8["facilities"] = t8["facilities"].astype(int)
shade = LogNorm(vmin=10, vmax=t8["pop"].max())(t8["pop"].clip(lower=10))
t8["colour"] = [[int(255 * c) for c in plt.cm.magma(v)[:3]] + [170] for v in shade]

hex_layer = pdk.Layer(
    "H3HexagonLayer",
    t8,
    get_hexagon="cell",
    get_fill_color="colour",
    pickable=True,
    stroked=False,
)
fac_layer = pdk.Layer(
    "ScatterplotLayer",
    nbi_fac,
    get_position=["lon", "lat"],
    get_radius=80,
    get_fill_color=[30, 200, 255],
    pickable=True,
)
deck = pdk.Deck(
    layers=[hex_layer, fac_layer],
    initial_view_state=pdk.ViewState(latitude=-1.29, longitude=36.82, zoom=10.5),
    tooltip={"text": "{name}\npeople: {people}\nfacilities: {facilities}"},
)
deck.to_html(str(OUT / "nairobi_h3.html"), open_browser=False)
print("wrote", OUT / "nairobi_h3.html")

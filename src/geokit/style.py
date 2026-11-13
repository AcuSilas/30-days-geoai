"""AHADI house style for matplotlib figures: brand colours, colour maps and defaults.

Colours come from AHADI's brand palette. Use them through the named constants and
colour maps below rather than typing hex codes into analysis scripts.

    from geokit import style

    style.use()                                    # once, at the top of a script
    ax.imshow(ndvi, cmap=style.VEGETATION)         # continuous data
    ax.plot(x, y, color=style.NAVY)                # a single series
"""

import matplotlib as mpl
import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib.colors import LinearSegmentedColormap

# Brand palette
NAVY = "#0F2333"
BRIGHT_BLUE = "#5EAADD"
GOLDEN_YELLOW = "#FFC225"
LIGHT_BLUE = "#AADEE9"
LIGHT_GREEN = "#B3CB72"
DARK_YELLOW = "#AA9B33"
GRAY_BLUE = "#628DA5"

# Neutrals and tints
PALE_YELLOW = "#FFF3D3"  # tint of golden yellow
PALE_BLUE = "#DFEEF8"  # tint of bright blue
LIGHTEST_GRAY = "#F8FBFD"
LIGHT_GRAY = "#F2F2F3"
MID_GRAY = "#DAD9D9"
TEXT_GRAY = "#5B5E67"

# Distinct colours for categories, in order of use
CATEGORICAL = [NAVY, BRIGHT_BLUE, GOLDEN_YELLOW, GRAY_BLUE, LIGHT_GREEN, DARK_YELLOW, LIGHT_BLUE]

# Continuous colour maps, light to dark so they also read in greyscale
SEQUENTIAL = LinearSegmentedColormap.from_list(
    "ahadi_sequential", [LIGHTEST_GRAY, LIGHT_BLUE, BRIGHT_BLUE, GRAY_BLUE, NAVY]
)  # counts, rates, population
VEGETATION = LinearSegmentedColormap.from_list(
    "ahadi_vegetation", [PALE_YELLOW, GOLDEN_YELLOW, LIGHT_GREEN, GRAY_BLUE, NAVY]
)  # NDVI: dry and bare to dense and green
DIVERGING = LinearSegmentedColormap.from_list(
    "ahadi_diverging", [DARK_YELLOW, GOLDEN_YELLOW, LIGHT_GRAY, BRIGHT_BLUE, NAVY]
)  # anomalies: drier than normal, normal, wetter than normal

COLORMAPS = (SEQUENTIAL, VEGETATION, DIVERGING)


def use() -> None:
    """Apply the house style to every figure made after this call."""
    for cmap in COLORMAPS:
        if cmap.name not in mpl.colormaps:
            mpl.colormaps.register(cmap)
    plt.rcParams.update(
        {
            "axes.prop_cycle": cycler(color=CATEGORICAL),
            "image.cmap": SEQUENTIAL.name,
            "font.family": "sans-serif",
            "font.sans-serif": ["Aptos", "Calibri", "Arial", "DejaVu Sans"],
            "text.color": NAVY,
            "axes.titlecolor": NAVY,
            "axes.titleweight": "bold",
            "axes.labelcolor": TEXT_GRAY,
            "axes.edgecolor": MID_GRAY,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": TEXT_GRAY,
            "ytick.color": TEXT_GRAY,
            "grid.color": LIGHT_GRAY,
            "legend.frameon": False,
            "figure.facecolor": "white",
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
        }
    )


def swatches(path: str | None = None) -> plt.Figure:
    """Show the palette and colour maps on one figure; save it if a path is given."""
    use()
    fig, axes = plt.subplots(len(COLORMAPS) + 1, 1, figsize=(8, 4.2), constrained_layout=True)
    for i, colour in enumerate(CATEGORICAL):
        axes[0].add_patch(plt.Rectangle((i, 0), 0.95, 1, color=colour))
        axes[0].text(i + 0.47, -0.25, colour, ha="center", va="top", fontsize=7)
    axes[0].set_xlim(0, len(CATEGORICAL))
    axes[0].set_ylim(-0.6, 1)
    axes[0].set_title("Categorical", loc="left")
    for ax, cmap in zip(axes[1:], COLORMAPS, strict=True):
        ax.imshow([list(range(256))], cmap=cmap, aspect="auto")
        ax.set_title(cmap.name, loc="left")
    for ax in axes:
        ax.set_axis_off()
    if path:
        fig.savefig(path)
    return fig

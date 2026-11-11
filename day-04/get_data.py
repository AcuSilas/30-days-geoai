"""Download WorldPop's population estimate for Kenya (100 m, constrained, R2025A).

The download link is discovered through WorldPop's REST API rather than hard-coded, with the documented file pattern as a fallback. One file, fetched once and cached.
"""  # noqa: E501

from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "day-04"
YEAR = 2026
API = "https://hub.worldpop.org/rest/data/pop/G2_CN_POP_R25A_100m"
PATTERN = (

  "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/{year}/KEN/v1/"
    "100m/constrained/ken_pop_{year}_CN_100m_R2025A_v1.tif"

)

def find_url(year: int) -> str:
  """Ask the WorldPop API for Kenya's file for one year; fall back to the known pattern."""
  try:
    r = requests.get(API, params={"iso3": "KEN"}, timeout=60)
    r.raise_for_status()
    for entry in r.json().get("data", []):
      if str(entry.get("popyear")) == str(year):
        tifs = [f for f in entry.get("files", []) if f.endswith(".tif")]
        if tifs:
          return tifs[0]
    print(f"API listed no file for {year}: using the documented pattern")
  except (requests.RequestException, ValueError) as err:
    print(f"API unavailable ({err}); using the documented pattern")
  return PATTERN.format(year=year)

def download(url: str, dest: Path, chunk_size: int = 1 << 20) -> Path:
  """Stream url to dest once, writing to .part first; later runs reuse the file."""
  if dest.exists():
    print(f"exists, skipping: {dest.name}")
    return dest
  tmp = dest.with_name(dest.name + ".part")
  with requests.get(url, stream=True, timeout=600) as r:
    r.raise_for_status()
    with open(tmp, "wb") as f:
      for block in r.iter_content(chunk_size):
        f.write(block)
  tmp.rename(dest)
  print(f"saved {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")
  return dest

if __name__ == "__main__":
  DATA.mkdir(parents=True, exist_ok=True)
  url = find_url(YEAR)
  print("source:", url)
  download(url, DATA / f"ken_pop_{YEAR}_100m.tif")

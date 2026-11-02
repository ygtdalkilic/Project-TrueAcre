"""Which counties border which, from the US Census Bureau, and county-name normalization.

Source: the Census Bureau county adjacency file (public domain), reduced to four columns:
https://www2.census.gov/geo/docs/reference/county_adjacency/county_adjacency2025.txt
Rebuild with `python -m data.geography <path to the downloaded .txt>`.

Growers buy seed across county lines, so dealer coverage is judged over a county and its neighbors.
"""
import functools
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ADJACENCY_FILE = Path(__file__).parent / "county_adjacency.csv.gz"
# Census name endings that a company's own records often leave out. " city" is kept on purpose:
# Richmond city, VA and Richmond County, VA are different places.
SUFFIXES = (" city and borough", " county", " parish", " borough", " census area", " municipality",
            " municipio", " planning region")


def normalize_county(name: str) -> str:
    """'St. Louis County' and 'saint louis' -> 'stlouis'; 'De Witt' and 'DeWitt' -> 'dewitt'.
    Accents, periods, apostrophes, and spaces are dropped."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = " ".join(s.casefold().replace(".", "").replace("'", "").split())
    if s.startswith("saint "):
        s = "st " + s[len("saint "):]
    for suffix in SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.replace(" ", "")


def place(county: str, state: str) -> tuple[str, str]:
    """The key every county comparison uses: (normalized county name, state abbreviation)."""
    return normalize_county(county), str(state).strip().upper()


@functools.cache
def neighbors() -> dict[tuple[str, str], frozenset[tuple[str, str]]]:
    """place -> the places bordering it."""
    df = pd.read_csv(ADJACENCY_FILE, dtype=str)
    out: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for county, state, n_county, n_state in df.itertuples(index=False):
        out.setdefault(place(county, state), set()).add(place(n_county, n_state))
    return {k: frozenset(v) for k, v in out.items()}


def build(census_txt: Path) -> pd.DataFrame:
    """The Census pipe-delimited file ('Story County, IA|19169|Boone County, IA|19015|...') as four columns."""
    raw = pd.read_csv(census_txt, sep="|", dtype=str, encoding="utf-8")
    home = raw["County Name"].str.rsplit(", ", n=1, expand=True)
    other = raw["Neighbor Name"].str.rsplit(", ", n=1, expand=True)
    df = pd.DataFrame({"county": home[0], "state": home[1], "neighbor_county": other[0], "neighbor_state": other[1]})
    return df[(df.county != df.neighbor_county) | (df.state != df.neighbor_state)].reset_index(drop=True)


if __name__ == "__main__":
    build(Path(sys.argv[1])).to_csv(ADJACENCY_FILE, index=False, compression="gzip")
    print(f"wrote {ADJACENCY_FILE}")

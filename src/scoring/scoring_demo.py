from pathlib import Path
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
DEMO_PATH = ROOT_DIR / "data" / "demo" / "routes_scored_demo.csv"


def score_demo_routes() -> pd.DataFrame:
    """Laedt die vorkalkulierten Demo-Routen inkl. Score und Badges."""
    df = pd.read_csv(DEMO_PATH)
    return df

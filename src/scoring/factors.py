import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCORING_DIR = os.path.join(BASE_DIR, "scoring_CSV")

EMISS_PATH = os.path.join(SCORING_DIR, "emission_factors.csv")
ENERGY_PATH = os.path.join(SCORING_DIR, "energy_factors.csv")


def load_emission_factors():
    df = pd.read_csv(EMISS_PATH)
    return df.set_index("mode")["co2_g_per_pkm"].to_dict()


def load_energy_factors():
    df = pd.read_csv(ENERGY_PATH)
    return df.set_index("mode")["energy_Wh_per_pkm"].to_dict()

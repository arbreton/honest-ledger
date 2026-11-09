"""Airdrop option pricing from evidence (ADR-0011). Unknown inputs give ZERO marginal EV, never an invented number."""
import json, pathlib
from .forecasts import CLASS_CAP
ROOT = pathlib.Path(__file__).resolve().parents[1]

def programs():
    return json.loads((ROOT / "registry-data" / "programs.json").read_text())["programs"]

def marginal_ev(program, my_points=None, total_points=None, pool_usd=None, p_not_filtered=0.8, haircut=0.5):
    """gross = p * pool * haircut * (my/total) * P(not filtered). Any missing input => 0."""
    if not (my_points and total_points and pool_usd) or not program.get("criteria_published"):
        return 0.0
    p = CLASS_CAP[program["evidence_class"]]
    return p * pool_usd * haircut * (my_points / total_points) * p_not_filtered

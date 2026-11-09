"""Stored predictions, resolved on schedule and scored (Brier). Calibration caps probability by evidence class (LLD §6)."""
import json, hashlib, datetime
from .ledger import now
CLASS_CAP = {"E0": 0.05, "E1": 0.15, "E2": 0.50, "E3": 0.90, "E4": 0.99}

def create(L, strategy, question, probability, evidence_class, resolve_by, check_kind="manual", check_args=None):
    cap = CLASS_CAP[evidence_class]
    p = min(probability, cap)
    fid = hashlib.sha256(f"{strategy}|{question}|{resolve_by}".encode()).hexdigest()[:12]
    L.db.execute("INSERT OR IGNORE INTO forecasts(forecast_id,strategy,question,probability,evidence_class,created_at,resolve_by,check_kind,check_args) VALUES(?,?,?,?,?,?,?,?,?)",
                 (fid, strategy, question, p, evidence_class, now(), resolve_by, check_kind, json.dumps(check_args or {})))
    L.db.commit()
    return fid, p

def resolve(L, fid, outcome: bool, note=""):
    L.db.execute("UPDATE forecasts SET outcome=?, resolved_at=?, note=? WHERE forecast_id=? AND outcome IS NULL", (1 if outcome else 0, now(), note, fid))
    L.db.commit()

def brier(L, strategy=None):
    q = "SELECT probability, outcome FROM forecasts WHERE outcome IS NOT NULL" + (" AND strategy=?" if strategy else "")
    rows = L.db.execute(q, (strategy,) if strategy else ()).fetchall()
    return (sum((r[0] - r[1]) ** 2 for r in rows) / len(rows), len(rows)) if rows else (None, 0)

def due(L):
    return [dict(r) for r in L.db.execute("SELECT * FROM forecasts WHERE outcome IS NULL AND resolve_by<=? ORDER BY resolve_by", (datetime.date.today().isoformat(),))]

def open_list(L):
    return [dict(r) for r in L.db.execute("SELECT forecast_id,strategy,question,probability,evidence_class,resolve_by FROM forecasts WHERE outcome IS NULL ORDER BY resolve_by")]

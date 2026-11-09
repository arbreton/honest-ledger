"""Global halt flag (FR-X8). Any component may set it; only the operator clears it. Fails closed if unreadable."""
import pathlib, json, datetime, os
DIR = pathlib.Path(os.environ.get("FARMV2_HALT_DIR", pathlib.Path(__file__).resolve().parents[1] / "data" / "halt"))
FLAG = DIR / "HALT"

def is_halted() -> bool:
    try:
        return FLAG.exists()
    except OSError:
        return True   # fail closed

def reason():
    try:
        return json.loads(FLAG.read_text())
    except Exception:
        return None

def set_halt(by: str, why: str):
    DIR.mkdir(parents=True, exist_ok=True)
    if not FLAG.exists():
        FLAG.write_text(json.dumps({"by": by, "why": why, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}))

def clear(operator_confirmed: bool):
    if not operator_confirmed:
        raise PermissionError("only the operator may resume")
    FLAG.unlink(missing_ok=True)

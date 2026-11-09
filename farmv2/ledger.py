"""Append-only, hash-chained event log + double-entry postings (ADR-0002, FR-L1).
Invariants: events are immutable (DB triggers); every journal balances per asset; replay is deterministic."""
import hashlib, json, sqlite3, pathlib, datetime

SCHEMA = """
PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, type TEXT NOT NULL,
  chain_id INTEGER, block_number INTEGER, tx_hash TEXT,
  payload TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL) STRICT;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'events are immutable'); END;
CREATE TABLE IF NOT EXISTS accounts(
  account_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN('asset','liability','equity','income','expense')),
  name TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS journal(
  journal_id TEXT PRIMARY KEY, event_seq INTEGER NOT NULL REFERENCES events(seq),
  strategy TEXT, memo TEXT) STRICT;
CREATE TABLE IF NOT EXISTS postings(
  posting_id INTEGER PRIMARY KEY, journal_id TEXT NOT NULL REFERENCES journal(journal_id),
  account_id TEXT NOT NULL REFERENCES accounts(account_id), asset_id TEXT NOT NULL,
  amount TEXT NOT NULL, usd_value TEXT NOT NULL DEFAULT '0') STRICT;
CREATE TABLE IF NOT EXISTS nav_snapshots(
  block_number INTEGER PRIMARY KEY, ts TEXT NOT NULL, nav_usd TEXT NOT NULL, nav_eth TEXT NOT NULL,
  eth_usd TEXT NOT NULL, breakdown TEXT NOT NULL, source TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS reconciliations(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, block_number INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN('OK','BREACH')), detail TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS declarations(
  tx_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, note TEXT NOT NULL, declared_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS incidents(
  incident_id INTEGER PRIMARY KEY, severity TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL,
  opened_at TEXT NOT NULL, closed_at TEXT) STRICT;
CREATE TABLE IF NOT EXISTS intents(
  intent_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
  state TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY, intent_id TEXT NOT NULL, decision TEXT NOT NULL, rules TEXT NOT NULL, ts TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS sent_txs(
  tx_hash TEXT PRIMARY KEY, intent_id TEXT NOT NULL, step INTEGER NOT NULL, nonce INTEGER NOT NULL,
  status TEXT, ts TEXT NOT NULL, UNIQUE(intent_id, step)) STRICT;
CREATE TABLE IF NOT EXISTS approvals(
  intent_id TEXT PRIMARY KEY, code TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL, decided_at TEXT) STRICT;
CREATE TABLE IF NOT EXISTS considered(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, strategy TEXT NOT NULL, summary TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS forecasts(
  forecast_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, question TEXT NOT NULL, probability REAL NOT NULL,
  evidence_class TEXT NOT NULL, created_at TEXT NOT NULL, resolve_by TEXT NOT NULL, check_kind TEXT NOT NULL,
  check_args TEXT NOT NULL, outcome INTEGER, resolved_at TEXT, note TEXT) STRICT;
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS job_runs(
  id INTEGER PRIMARY KEY, job TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT, detail TEXT) STRICT;
"""

def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

class Ledger:
    def __init__(self, path):
        self.path = str(path)
        pathlib.Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=60)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=60000")
        self.db.executescript(SCHEMA)

    # ---- events ----
    def _last_hash(self) -> str:
        r = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return r["hash"] if r else "0" * 64

    @staticmethod
    def _digest(prev, event_id, typ, payload, occurred_at) -> str:
        return hashlib.sha256(f"{prev}|{event_id}|{typ}|{payload}|{occurred_at}".encode()).hexdigest()

    def has_event(self, event_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone() is not None

    def append(self, event_id, typ, payload: dict, occurred_at, chain_id=8453, block_number=None, tx_hash=None):
        """Idempotent: re-appending the same event_id is a no-op and returns None."""
        if self.has_event(event_id):
            return None
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        prev = self._last_hash()
        h = self._digest(prev, event_id, typ, body, occurred_at)
        cur = self.db.execute(
            "INSERT INTO events(event_id,type,chain_id,block_number,tx_hash,payload,occurred_at,recorded_at,prev_hash,hash)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event_id, typ, chain_id, block_number, tx_hash, body, occurred_at, now(), prev, h))
        self.db.commit()
        return cur.lastrowid

    def verify_chain(self):
        """Replays the hash chain. Returns (ok, n_events, first_bad_seq)."""
        prev, n = "0" * 64, 0
        for r in self.db.execute("SELECT * FROM events ORDER BY seq"):
            if r["prev_hash"] != prev or r["hash"] != self._digest(prev, r["event_id"], r["type"], r["payload"], r["occurred_at"]):
                return False, n, r["seq"]
            prev, n = r["hash"], n + 1
        return True, n, None

    # ---- double entry ----
    def ensure_account(self, account_id, kind, name=None):
        self.db.execute("INSERT OR IGNORE INTO accounts VALUES(?,?,?)", (account_id, kind, name or account_id))

    def post(self, journal_id, event_seq, postings, strategy=None, memo=""):
        """postings: list of (account_id, kind, asset_id, amount:int base units, usd_value:str).
        Each asset must sum to zero within the journal, else ValueError (FR-L1)."""
        sums = {}
        for _, _, asset, amt, _ in postings:
            sums[asset] = sums.get(asset, 0) + int(amt)
        bad = {a: v for a, v in sums.items() if v != 0}
        if bad:
            raise ValueError(f"unbalanced journal {journal_id}: {bad}")
        if self.db.execute("SELECT 1 FROM journal WHERE journal_id=?", (journal_id,)).fetchone():
            return False
        self.db.execute("INSERT INTO journal VALUES(?,?,?,?)", (journal_id, event_seq, strategy, memo))
        for acct, kind, asset, amt, usd in postings:
            self.ensure_account(acct, kind)
            self.db.execute("INSERT INTO postings(journal_id,account_id,asset_id,amount,usd_value) VALUES(?,?,?,?,?)",
                            (journal_id, acct, asset, str(int(amt)), str(usd)))
        self.db.commit()
        return True

    def balances(self, account_prefix="wallet:"):
        """Net base-unit balance per (account, asset) from postings."""
        out = {}
        for r in self.db.execute("SELECT account_id, asset_id, amount FROM postings WHERE account_id LIKE ?", (account_prefix + "%",)):
            k = (r["account_id"], r["asset_id"])
            out[k] = out.get(k, 0) + int(r["amount"])
        return out

    def balances_asof(self, block, account_prefix="wallet:"):
        out = {}
        q = ("SELECT p.account_id, p.asset_id, p.amount FROM postings p JOIN journal j ON j.journal_id=p.journal_id "
             "JOIN events e ON e.seq=j.event_seq WHERE p.account_id LIKE ? AND e.block_number<=?")
        for r in self.db.execute(q, (account_prefix + "%", block)):
            k = (r["account_id"], r["asset_id"])
            out[k] = out.get(k, 0) + int(r["amount"])
        return out

    def events(self, typ=None):
        q = "SELECT * FROM events" + (" WHERE type=?" if typ else "") + " ORDER BY seq"
        return [dict(r) for r in self.db.execute(q, (typ,) if typ else ())]

    def kv_get(self, key, default=None):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def kv_set(self, key, value):
        self.db.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.db.commit()

    def close(self):
        self.db.close()

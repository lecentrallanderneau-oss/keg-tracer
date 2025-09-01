import os
import logging
from uuid import uuid4
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from flask import Flask, render_template, request, jsonify
from jinja2 import TemplateNotFound

# -------------------------------------------------------------------
# App & Logging
# -------------------------------------------------------------------
app = Flask(__name__)

# Logging clair (utile sur Render)
app.logger.setLevel(logging.INFO)
if not app.logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
FR_MONTHS = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}

def month_label_fr(d: date) -> str:
    return f"{FR_MONTHS.get(d.month, str(d.month))} {d.year}"

def parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

# -------------------------------------------------------------------
# Données factices (remplace par ta base JSON/SQL plus tard)
# -------------------------------------------------------------------
DELIVERIES: List[Dict[str, Any]] = [
    # date ISO, supplier, product, quantity, deposit (euros), invoice
    {"date": "2025-08-28", "supplier": "Coreff", "product": "Blonde 30L", "quantity": 4, "deposit": 60.0, "invoice_no": "F-2025-0812"},
    {"date": "2025-08-21", "supplier": "Bzh Craft", "product": "IPA 20L", "quantity": 3, "deposit": 45.0, "invoice_no": "BC-2025-031"},
    {"date": "2025-07-30", "supplier": "Coreff", "product": "Ambrée 30L", "quantity": 2, "deposit": 30.0, "invoice_no": "F-2025-0730"},
]

KEGS: List[Dict[str, Any]] = [
    # id, product, size_l, status(full/empty/lost/unknown), location, updated_at
    {"id": "K-001", "product": "Blonde 30L", "size_l": 30, "status": "full", "location": "Chai", "updated_at": "2025-08-28"},
    {"id": "K-002", "product": "IPA 20L", "size_l": 20, "status": "empty", "location": "Bar", "updated_at": "2025-08-29"},
    {"id": "K-003", "product": "Ambrée 30L", "size_l": 30, "status": "lost", "location": "—", "updated_at": "2025-07-31"},
]

# -------------------------------------------------------------------
# Calculs “métriques”
# -------------------------------------------------------------------
def compute_consigne_balance(deliveries: List[Dict[str, Any]]) -> float:
    # Placeholder : somme des consignes perçues (à adapter avec retours/avoirs)
    return float(sum(d.get("deposit", 0.0) or 0.0 for d in deliveries))

def deliveries_in_month(deliveries: List[Dict[str, Any]], ref: date) -> int:
    return sum(
        1 for d in deliveries
        if (dt := parse_iso_date(d.get("date") or "")) and dt.year == ref.year and dt.month == ref.month
    )

def recent_deliveries(deliveries: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    def key_fn(d):  # tri par date desc
        dt = parse_iso_date(d.get("date") or "") or date(1970,1,1)
        return dt
    return sorted(deliveries, key=key_fn, reverse=True)[:limit]

def kegs_in_circulation(kegs: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    # Placeholder : prend tout, tri par updated_at desc
    def key_fn(k):
        dt = parse_iso_date(k.get("updated_at") or "") or date(1970,1,1)
        return dt
    return sorted(kegs, key=key_fn, reverse=True)[:limit]

def count_pending_returns(kegs: List[Dict[str, Any]]) -> int:
    # Placeholder : considère "full" comme à récupérer
    return sum(1 for k in kegs if (k.get("status") or "unknown") == "full")

# -------------------------------------------------------------------
# Routes applicatives
# -------------------------------------------------------------------
@app.route("/", methods=["GET", "HEAD"])
def index():
    today = date.today()
    ctx = dict(
        consigne_balance=compute_consigne_balance(DELIVERIES),
        total_kegs=len(KEGS),
        deliveries_this_month=deliveries_in_month(DELIVERIES, today),
        pending_returns=count_pending_returns(KEGS),
        current_month_label=month_label_fr(today),
        last_sync=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        build_version=os.getenv("RENDER_GIT_COMMIT", "dev")[:7],
        recent_deliveries=recent_deliveries(DELIVERIES, limit=8),
        kegs_in_circulation=kegs_in_circulation(KEGS, limit=8),
    )
    try:
        return render_template("index.html", **ctx)
    except Exception:
        app.logger.exception("Erreur de rendu index.html")
        return render_template("500.html", error_id=str(uuid4())), 500

@app.route("/deliveries", methods=["GET"])
def deliveries_view():
    q = (request.args.get("q") or "").strip().lower()
    rows = DELI

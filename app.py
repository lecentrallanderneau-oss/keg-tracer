import os
import logging
from uuid import uuid4
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from collections import defaultdict

from flask import Flask, render_template, request, jsonify
from jinja2 import TemplateNotFound

# ---------------------------------------------
# Flask app avec chemins explicites
# ---------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static") if os.path.isdir(os.path.join(BASE_DIR, "static")) else None,
)

# ---------------------------------------------
# Logging clair sur Render
# ---------------------------------------------
app.logger.setLevel(logging.INFO)
if not app.logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

# ---------------------------------------------
# Helpers
# ---------------------------------------------
FR_MONTHS = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}

def month_label_fr(d: date) -> str:
    return f"{FR_MONTHS.get(d.month, str(d.month))} {d.year}"

def parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

# ---------------------------------------------
# Données factices (tu pourras les remplacer)
# ---------------------------------------------
# Livraisons "générales" (utilisées sur le dashboard)
DELIVERIES: List[Dict[str, Any]] = [
    {"date": "2025-08-28", "supplier": "Coreff",   "product": "Blonde 30L", "quantity": 4, "deposit": 60.0, "invoice_no": "F-2025-0812"},
    {"date": "2025-08-21", "supplier": "Bzh Craft","product": "IPA 20L",    "quantity": 3, "deposit": 45.0, "invoice_no": "BC-2025-031"},
    {"date": "2025-07-30", "supplier": "Coreff",   "product": "Ambrée 30L", "quantity": 2, "deposit": 30.0, "invoice_no": "F-2025-0730"},
]

# Fûts "généraux" (utilisés sur le dashboard et la page kegs)
KEGS: List[Dict[str, Any]] = [
    {"id": "K-001", "product": "Blonde 30L", "size_l": 30, "status": "full",  "location": "Chai",    "updated_at": "2025-08-28"},
    {"id": "K-002", "product": "IPA 20L",    "size_l": 20, "status": "empty", "location": "Bar",     "updated_at": "2025-08-29"},
    {"id": "K-003", "product": "Ambrée 30L", "size_l": 30, "status": "lost",  "location": "Inconnu", "updated_at": "2025-07-31"},
]

# Clients & mouvements par client (pour le suivi client)
CLIENTS = [
    {"id": "C-001", "name": "Le Central Landerneau"},
    {"id": "C-002", "name": "Bar des Amis"},
]

# type: delivery (tu livres au client, stock client +) / pickup (tu reprends, stock client -)
# deposit_eur: consigne nette associée au mouvement (positive à la livraison, négative au retour)
KEG_TRANSACTIONS = [
    {"date": "2025-08-01", "client_id": "C-001", "type": "delivery", "product": "Blonde", "size_l": 30, "qty": 3, "deposit_eur": 135.0, "doc_no": "BL-1001"},
    {"date": "2025-08-15", "client_id": "C-001", "type": "pickup",   "product": "Blonde", "size_l": 30, "qty": 1, "deposit_eur": -45.0, "doc_no": "RT-2001"},
    {"date": "2025-08-28", "client_id": "C-001", "type": "delivery", "product": "IPA",    "size_l": 20, "qty": 2, "deposit_eur": 60.0,  "doc_no": "BL-1010"},
    {"date": "2025-08-05", "client_id": "C-002", "type": "delivery", "product": "Ambrée", "size_l": 30, "qty": 2, "deposit_eur": 90.0,  "doc_no": "BL-1003"},
]

# ---------------------------------------------
# Calculs généraux (dashboard)
# ---------------------------------------------
def compute_consigne_balance(deliveries: List[Dict[str, Any]]) -> float:
    return float(sum(d.get("deposit", 0.0) or 0.0 for d in deliveries))

def deliveries_in_month(deliveries: List[Dict[str, Any]], ref: date) -> int:
    return sum(
        1 for d in deliveries
        if (dt := parse_iso_date(d.get("date") or "")) and dt.year == ref.year and dt.month == ref.month
    )

def recent_deliveries(deliveries: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    def key_fn(d):
        dt = parse_iso_date(d.get("date") or "") or date(1970, 1, 1)
        return dt
    return sorted(deliveries, key=key_fn, reverse=True)[:limit]

def kegs_in_circulation(kegs: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    def key_fn(k):
        dt = parse_iso_date(k.get("updated_at") or "") or date(1970, 1, 1)
        return dt
    return sorted(kegs, key=key_fn, reverse=True)[:limit]

def count_pending_returns(kegs: List[Dict[str, Any]]) -> int:
    # exemple : considère "full" comme à récupérer / mouvement futur
    return sum(1 for k in kegs if (k.get("status") or "unknown") == "full")

# ---------------------------------------------
# Calculs par client (stock net + consigne)
# ---------------------------------------------
def list_clients() -> List[Dict[str, Any]]:
    return CLIENTS

def get_client(client_id: str) -> Optional[Dict[str, Any]]:
    return next((c for c in CLIENTS if c["id"] == client_id), None)

def client_transactions(client_id: str) -> List[Dict[str, Any]]:
    rows = [t for t in KEG_TRANSACTIONS if t["client_id"] == client_id]
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    return rows

def compute_client_balances(client_id: str) -> Dict[str, Any]:
    """
    total_kegs: total net de fûts attendus chez le client
    total_deposit_eur: consigne nette (positive = due par le client, négative = à rembourser)
    by_sku: liste des détails par (product, size_l)
    """
    by_sku = defaultdict(lambda: {"qty": 0, "deposit_eur": 0.0})
    total_kegs = 0
    total_deposit = 0.0

    for t in KEG_TRANSACTIONS:
        if t["client_id"] != client_id:
            continue
        sign = 1 if t["type"] == "delivery" else -1
        key = (t.get("product") or "—", int(t.get("size_l") or 0))
        qty = int(t.get("qty") or 0)
        dep = float(t.get("deposit_eur") or 0.0)

        by_sku[key]["qty"] += sign * qty
        by_sku[key]["deposit_eur"] += dep
        total_kegs += sign * qty
        total_deposit += dep

    details = []
    for (product, size_l), vals in sorted(by_sku.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        details.append({
            "product": product,
            "size_l": size_l,
            "qty": vals["qty"],
            "deposit_eur": vals["deposit_eur"],
        })

    return {
        "total_kegs": total_kegs,
        "total_deposit_eur": total_deposit,
        "by_sku": details,
    }

# ---------------------------------------------
# Routes principales
# ---------------------------------------------
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
    rows = DELIVERIES
    if q:
        rows = [
            d for d in DELIVERIES
            if q in str(d.get("supplier", "")).lower()
            or q in str(d.get("product", "")).lower()
            or q in str(d.get("invoice_no", "")).lower()
            or q in str(d.get("date", "")).lower()
        ]
    try:
        return render_template("deliveries.html", deliveries=rows)
    except Exception:
        app.logger.exception("Erreur de rendu deliveries.html")
        return render_template("500.html", error_id=str(uuid4())), 500

@app.route("/kegs", methods=["GET"])
def kegs_view():
    try:
        return render_template("kegs.html", kegs=KEGS, total_kegs=len(KEGS))
    except Exception:
        app.logger.exception("Erreur de rendu kegs.html")
        return render_template("500.html", error_id=str(uuid4())), 500

# --- Clients ---
@app.route("/clients", methods=["GET"])
def clients_list():
    data = []
    for c in list_clients():
        bal = compute_client_balances(c["id"])
        data.append({
            "id": c["id"],
            "name": c["name"],
            "total_kegs": bal["total_kegs"],
            "total_deposit_eur": bal["total_deposit_eur"],
        })
    data.sort(key=lambda r: r["name"].lower())
    return render_template("clients.html", clients=data)

@app.route("/clients/<client_id>", methods=["GET"])
def client_detail(client_id):
    client = get_client(client_id)
    if not client:
        return render_template("404.html"), 404

    bal = compute_client_balances(client_id)
    tx = client_transactions(client_id)
    return render_template(
        "client_detail.html",
        client=client,
        balance=bal,
        transactions=tx,
    )

# ---------------------------------------------
# Diagnostics & santé
# ---------------------------------------------
@app.route("/healthz")
def healthz():
    return jsonify(status="ok", time=datetime.utcnow().isoformat() + "Z")

@app.route("/diag")
def diag():
    info = []
    info.append(f"template_folder = {app.template_folder!r}")
    try:
        _source, filename, _uptodate = app.jinja_env.loader.get_source(app.jinja_env, "index.html")
        info.append(f"index.html trouvé : {filename}")
    except TemplateNotFound:
        info.append("index.html introuvable dans le template loader")
    return "<br>".join(info)

@app.route("/test-template/<name>")
def test_template(name):
    try:
        return render_template(name)
    except Exception as e:
        app.logger.exception(f"Echec rendu template {name}")
        return f"Erreur lors du rendu de {name}: {e}", 500

# ---------------------------------------------
# Handlers d’erreurs
# ---------------------------------------------
@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        app.logger.exception("Erreur de rendu 404.html")
        return "404 Not Found", 404

@app.errorhandler(500)
def internal_error(e):
    err_id = str(uuid4())
    app.logger.exception(f"[{err_id}] 500 Internal Server Error")
    try:
        return render_template("500.html", error_id=err_id), 500
    except Exception:
        return f"500 Internal Server Error — {err_id}", 500

# ---------------------------------------------
# Entrée locale (Render utilise gunicorn app:app)
# ---------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)

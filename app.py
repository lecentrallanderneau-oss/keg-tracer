import os
import logging
from uuid import uuid4
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, case
from jinja2 import TemplateNotFound, TemplateError

# --------------------------------------------------
# Config Flask + DB (Postgres si DATABASE_URL sinon SQLite pour dev)
# --------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static") if os.path.isdir(os.path.join(BASE_DIR, "static")) else None,
)
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --------------------------------------------------
# Logging
# --------------------------------------------------
app.logger.setLevel(logging.INFO)
if not app.logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

# --------------------------------------------------
# Helpers
# --------------------------------------------------
FR_MONTHS = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}
def month_label_fr(d: date) -> str:
    return f"{FR_MONTHS.get(d.month, str(d.month))} {d.year}"

# --------------------------------------------------
# Modèles SQLAlchemy
# --------------------------------------------------
class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(180), nullable=False)       # ex: Coreff Blonde
    size_l = db.Column(db.Integer, nullable=False)         # 20 / 22 / 30
    deposit_eur = db.Column(db.Float, nullable=False, default=30.0)  # consigne par fût
    supplier = db.Column(db.String(120), nullable=True)    # Coreff, Val de Rance...
    active = db.Column(db.Boolean, nullable=False, default=True)

    def display_name(self) -> str:
        return f"{self.name} {self.size_l}L"

class Delivery(db.Model):
    __tablename__ = "deliveries"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    supplier = db.Column(db.String(120), nullable=False)
    product = db.Column(db.String(120), nullable=False)    # texte libre (snapshot)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    deposit = db.Column(db.Float, nullable=False, default=0.0)  # total du BL côté fournisseur
    invoice_no = db.Column(db.String(120), nullable=True)

class Keg(db.Model):
    __tablename__ = "kegs"
    id = db.Column(db.String(64), primary_key=True)        # ex: K-001
    product = db.Column(db.String(120), nullable=False)
    size_l = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(32), nullable=False, default="unknown")  # full / empty / lost / unknown
    location = db.Column(db.String(120), nullable=True)
    updated_at = db.Column(db.Date, nullable=True)

class Client(db.Model):
    __tablename__ = "clients"
    id = db.Column(db.String(64), primary_key=True)        # ex: C-001
    name = db.Column(db.String(200), nullable=False, unique=True)

class KegTransaction(db.Model):
    __tablename__ = "keg_transactions"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date = db.Column(db.Date, nullable=False)
    client_id = db.Column(db.String(64), db.ForeignKey("clients.id"), nullable=False, index=True)
    type = db.Column(db.String(16), nullable=False)        # delivery / pickup
    product = db.Column(db.String(120), nullable=False)    # nom produit (snapshot, ex: Coreff Blonde)
    size_l = db.Column(db.Integer, nullable=False, default=0)
    qty = db.Column(db.Integer, nullable=False, default=0)
    deposit_eur = db.Column(db.Float, nullable=False, default=0.0)  # total mouvement (qty * consigne, signe +/-)
    doc_no = db.Column(db.String(120), nullable=True)

# --------------------------------------------------
# Métriques
# --------------------------------------------------
def compute_consigne_balance() -> float:
    total = db.session.query(func.coalesce(func.sum(Delivery.deposit), 0.0)).scalar() or 0.0
    return float(total)

def deliveries_in_month(ref: date) -> int:
    return db.session.query(Delivery).filter(
        func.extract("year", Delivery.date) == ref.year,
        func.extract("month", Delivery.date) == ref.month,
    ).count()

def recent_deliveries(limit: int = 8) -> List[Dict[str, Any]]:
    rows = db.session.query(Delivery).order_by(Delivery.date.desc()).limit(limit).all()
    return [dict(date=r.date.isoformat(), supplier=r.supplier, product=r.product, quantity=r.quantity,
                 deposit=r.deposit, invoice_no=r.invoice_no or "—") for r in rows]

def kegs_in_circulation(limit: int = 8) -> List[Dict[str, Any]]:
    rows = db.session.query(Keg).order_by(Keg.updated_at.desc().nullslast()).limit(limit).all()
    return [dict(id=r.id, product=r.product, size_l=r.size_l, status=r.status,
                 location=r.location or "—", updated_at=r.updated_at.isoformat() if r.updated_at else "—") for r in rows]

def count_pending_returns() -> int:
    return db.session.query(Keg).filter(Keg.status == "full").count()

# Clients
def client_list():
    return db.session.query(Client).order_by(Client.name.asc()).all()

def get_client(client_id: str) -> Optional[Client]:
    return db.session.get(Client, client_id)

def client_transactions(client_id: str):
    return (db.session.query(KegTransaction)
            .filter(KegTransaction.client_id == client_id)
            .order_by(KegTransaction.date.desc())
            .all())

def compute_client_balances(client_id: str) -> Dict[str, Any]:
    rows = (
        db.session.query(
            KegTransaction.product,
            KegTransaction.size_l,
            func.sum(case((KegTransaction.type == "delivery", KegTransaction.qty), else_=-KegTransaction.qty)).label("qty_net"),
            func.coalesce(func.sum(KegTransaction.deposit_eur), 0.0).label("deposit_sum"),
        )
        .filter(KegTransaction.client_id == client_id)
        .group_by(KegTransaction.product, KegTransaction.size_l)
        .order_by(KegTransaction.product.asc(), KegTransaction.size_l.asc())
        .all()
    )
    details, total_qty, total_dep = [], 0, 0.0
    for p, size_l, qty_net, dep_sum in rows:
        details.append({"product": p, "size_l": int(size_l or 0), "qty": int(qty_net or 0), "deposit_eur": float(dep_sum or 0.0)})
        total_qty += int(qty_net or 0)
        total_dep += float(dep_sum or 0.0)
    return {"total_kegs": total_qty, "total_deposit_eur": total_dep, "by_sku": details}

# --------------------------------------------------
# Routes UI
# --------------------------------------------------
@app.route("/", methods=["GET", "HEAD"])
def index():
    today = date.today()
    ctx = dict(
        consigne_balance=compute_consigne_balance(),
        total_kegs=db.session.query(Keg).count(),
        deliveries_this_month=deliveries_in_month(today),
        pending_returns=count_pending_returns(),
        current_month_label=month_label_fr(today),
        last_sync=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        build_version=os.getenv("RENDER_GIT_COMMIT", "dev")[:7],
        recent_deliveries=recent_deliveries(limit=8),
        kegs_in_circulation=kegs_in_circulation(limit=8),
    )
    try:
        return render_template("index.html", **ctx)
    except Exception:
        app.logger.exception("Erreur de rendu index.html")
        return render_template("500.html", error_id=str(uuid4())), 500

@app.route("/deliveries")
def deliveries_view():
    q = (request.args.get("q") or "").strip().lower()
    query = db.session.query(Delivery)
    if q:
        like = f"%{q}%"
        query = query.filter(
            func.lower(Delivery.supplier).like(like) |
            func.lower(Delivery.product).like(like) |
            func.lower(func.coalesce(Delivery.invoice_no, "")).like(like) |
            func.to_char(Delivery.date, "YYYY-MM-DD").like(like)
        )
    rows = query.order_by(Delivery.date.desc()).all()
    deliveries = [dict(date=r.date.isoformat(), supplier=r.supplier, product=r.product,
                       quantity=r.quantity, deposit=r.deposit, invoice_no=r.invoice_no or "—") for r in rows]
    return render_template("deliveries.html", deliveries=deliveries)

@app.route("/kegs")
def kegs_view():
    rows = db.session.query(Keg).order_by(Keg.id.asc()).all()
    kegs = [dict(id=r.id, product=r.product, size_l=r.size_l, status=r.status,
                 location=r.location or "—", updated_at=r.updated_at.isoformat() if r.updated_at else "—") for r in rows]
    return render_template("kegs.html", kegs=kegs, total_kegs=len(kegs))

@app.route("/clients")
def clients_list():
    data = []
    for c in client_list():
        bal = compute_client_balances(c.id)
        data.append({"id": c.id, "name": c.name, "total_kegs": bal["total_kegs"], "total_deposit_eur": bal["total_deposit_eur"]})
    data.sort(key=lambda r: r["name"].lower())
    return render_template("clients.html", clients=data)

@app.route("/clients/<client_id>")
def client_detail(client_id):
    client = get_client(client_id)
    if not client:
        return render_template("404.html"), 404
    bal = compute_client_balances(client_id)
    tx = client_transactions(client_id)
    transactions = [dict(date=t.date.isoformat(), type=t.type, product=t.product, size_l=t.size_l,
                         qty=t.qty, deposit_eur=t.deposit_eur, doc_no=t.doc_no or "—") for t in tx]
    return render_template("client_detail.html", client={"id": client.id, "name": client.name},
                           balance=bal, transactions=transactions)

# Catalogue
@app.route("/catalog")
def catalog_view():
    prods = (db.session.query(Product)
             .filter(Product.active == True)
             .order_by(Product.name.asc(), Product.size_l.asc())
             .all())
    rows = [dict(id=p.id, name=p.name, size_l=p.size_l, deposit_eur=p.deposit_eur,
                 supplier=p.supplier or "—") for p in prods]
    return render_template("catalog.html", products=rows)

# --------------------------------------------------
# Admin minimal (pages HTML intégrées, mobile-friendly)
# --------------------------------------------------
def _html_page(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial;margin:16px}}
input,select{{padding:10px;font-size:16px;width:100%;box-sizing:border-box;margin:6px 0}}
button{{padding:10px 14px;font-size:16px}}
.row{{margin:10px 0}}
a{{color:#0b6efd;text-decoration:none}}
</style></head><body>
<p><a href="/">← Dashboard</a> · <a href="/catalog">Catalogue</a> · <a href="/clients">Clients</a> · <a href="/deliveries">Livraisons</a> · <a href="/kegs">Fûts</a></p>
<h1 style="margin-top:0">{title}</h1>
{body_html}
</body></html>"""

# Init & seed
@app.route("/admin/init-db")
def admin_init_db():
    db.create_all()
    return "DB initialisée ✅"

@app.route("/admin/seed")
def admin_seed():
    # Catalogue Coreff + Cidre — consigne 30€ par fût
    if db.session.query(Product).count() == 0:
        db.session.add_all([
            Product(name="Coreff Blonde",      size_l=20, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff Blonde",      size_l=30, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff Blonde Bio",  size_l=20, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff Blonde Bio",  size_l=30, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff IPA",         size_l=20, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff IPA",         size_l=30, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff Blanche",     size_l=20, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff Rousse",      size_l=20, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Coreff Ambrée",      size_l=22, deposit_eur=30.0, supplier="Coreff"),
            Product(name="Cidre Val de Rance", size_l=20, deposit_eur=30.0, supplier="Val de Rance"),
        ])

    if db.session.query(Client).count() == 0:
        db.session.add_all([
            Client(id="C-001", name="Le Central Landerneau"),
            Client(id="C-002", name="Bar des Amis"),
        ])

    if db.session.query(Delivery).count() == 0:
        db.session.add_all([
            Delivery(date=date(2025,8,28), supplier="Coreff", product="Coreff Blonde 30L", quantity=4, deposit=4*30.0, invoice_no="F-2025-0812"),
            Delivery(date=date(2025,8,21), supplier="Coreff", product="Coreff IPA 20L",    quantity=3, deposit=3*30.0, invoice_no="F-2025-0821"),
        ])

    if db.session.query(Keg).count() == 0:
        db.session.add_all([
            Keg(id="K-001", product="Coreff Blonde 30L", size_l=30, status="full",  location="Chai",    updated_at=date(2025,8,28)),
            Keg(id="K-002", product="Coreff IPA 20L",    size_l=20, status="empty", location="Bar",     updated_at=date(2025,8,29)),
        ])

    if db.session.query(KegTransaction).count() == 0:
        db.session.add_all([
            # Livraison client = + qty ; reprise = - qty (signe via type)
            KegTransaction(date=date(2025,8,1),  client_id="C-001", type="delivery", product="Coreff Blonde", size_l=30, qty=3, deposit_eur= 3*30.0, doc_no="BL-1001"),
            KegTransaction(date=date(2025,8,15), client_id="C-001", type="pickup",   product="Coreff Blonde", size_l=30, qty=1, deposit_eur=-1*30.0, doc_no="RT-2001"),
            KegTransaction(date=date(2025,8,28), client_id="C-001", type="delivery", product="Coreff IPA",    size_l=20, qty=2, deposit_eur= 2*30.0, doc_no="BL-1010"),
        ])

    db.session.commit()
    return "Seed ok ✅"

# Admin: + Produit
@app.route("/admin/add-product", methods=["GET", "POST"])
def admin_add_product():
    msg = ""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        size_l = int(request.form.get("size_l") or 0)
        deposit_eur = float(request.form.get("deposit_eur") or 30.0)
        supplier = (request.form.get("supplier") or "").strip() or None
        if name and size_l > 0:
            db.session.add(Product(name=name, size_l=size_l, deposit_eur=deposit_eur, supplier=supplier))
            db.session.commit()
            return redirect(url_for("catalog_view"))
        else:
            msg = "<p style='color:#c00'>Nom et contenance requis.</p>"
    return _html_page("Ajouter un produit (catalogue)", f"""
<form method="post">
  <div class="row"><label>Nom</label><input name="name" placeholder="Coreff Blonde"></div>
  <div class="row"><label>Contenance (L)</label><input type="number" name="size_l" inputmode="numeric" value="30"></div>
  <div class="row"><label>Consigne / fût (€)</label><input type="number" step="0.01" name="deposit_eur" value="30"></div>
  <div class="row"><label>Fournisseur</label><input name="supplier" placeholder="Coreff"></div>
  <button type="submit">Enregistrer</button>
</form>
{msg}
<p style="margin-top:10px"><a href="/catalog">↳ Voir le catalogue</a></p>
""")

# Admin: + Client
@app.route("/admin/add-client", methods=["GET", "POST"])
def admin_add_client():
    msg = ""
    if request.method == "POST":
        cid = (request.form.get("id") or "").strip()
        name = (request.form.get("name") or "").strip()
        if cid and name:
            if not db.session.get(Client, cid):
                db.session.add(Client(id=cid, name=name))
                db.session.commit()
                return redirect(url_for("clients_list"))
            else:
                msg = "<p style='color:#c00'>ID déjà existant.</p>"
        else:
            msg = "<p style='color:#c00'>Renseigne ID et Nom.</p>"
    return _html_page("Ajouter un client", f"""
<form method="post">
  <div class="row"><label>ID client</label><input name="id" placeholder="C-003"></div>
  <div class="row"><label>Nom</label><input name="name" placeholder="Nom du client"></div>
  <button type="submit">Enregistrer</button>
</form>
{msg}
<p style="margin-top:10px"><a href="/clients">↳ Voir la liste</a></p>
""")

# Admin: + Livraison fournisseur
@app.route("/admin/add-delivery", methods=["GET", "POST"])
def admin_add_delivery():
    prods = (db.session.query(Product).filter(Product.active==True)
             .order_by(Product.name.asc(), Product.size_l.asc()).all())
    msg = ""
    if request.method == "POST":
        prod_id = request.form.get("product_id")
        product_text = (request.form.get("product") or "").strip()
        try:
            dt = datetime.fromisoformat((request.form.get("date") or "").strip()).date()
        except Exception:
            dt = date.today()
        supplier = (request.form.get("supplier") or "").strip()
        quantity = int(request.form.get("quantity") or 0)
        deposit_manual = request.form.get("deposit")
        deposit = float(deposit_manual) if deposit_manual not in (None, "",) else 0.0

        if prod_id:
            p = db.session.get(Product, int(prod_id))
            if p:
                if deposit_manual in (None, "",):
                    deposit = quantity * float(p.deposit_eur or 0.0)
                product_text = p.display_name()
                if not supplier:
                    supplier = p.supplier or ""
        if supplier and product_text and quantity > 0:
            db.session.add(Delivery(date=dt, supplier=supplier, product=product_text,
                                    quantity=quantity, deposit=deposit,
                                    invoice_no=(request.form.get("invoice_no") or "").strip() or None))
            db.session.commit()
            return redirect(url_for("deliveries_view"))
        else:
            msg = "<p style='color:#c00'>Fournisseur, Produit et Quantité obligatoires.</p>"

    opts = "".join([f'<option value="{p.id}">{p.display_name()} — consigne {p.deposit_eur:.2f}€</option>' for p in prods]) or '<option value="" disabled>Aucun produit</option>'
    today_str = date.today().isoformat()
    return _html_page("Ajouter une livraison fournisseur", f"""
<form method="post">
  <div class="row"><label>Date</label><input type="date" name="date" value="{today_str}"></div>
  <div class="row"><label>Fournisseur</label><input name="supplier" placeholder="Coreff"></div>

  <div class="row"><label>Produit (catalogue)</label>
    <select name="product_id">
      <option value="">— sélectionner (ou remplir manuel dessous) —</option>
      {opts}
    </select>
  </div>
  <div class="row"><label>OU Produit (manuel)</label><input name="product" placeholder="Coreff Blonde 30L"></div>

  <div class="row"><label>Quantité</label><input type="number" name="quantity" inputmode="numeric" value="1"></div>
  <div class="row"><label>Consigne totale (€) — vide = auto</label><input type="number" step="0.01" name="deposit" placeholder="auto"></div>
  <div class="row"><label>N° Facture (optionnel)</label><input name="invoice_no" placeholder="F-2025-0001"></div>
  <button type="submit">Enregistrer</button>
</form>
{msg}
<p style="margin-top:10px"><a href="/deliveries">↳ Voir les livraisons</a></p>
""")

# Admin: + Mouvement client (livraison / reprise)
@app.route("/admin/add-transaction", methods=["GET", "POST"])
def admin_add_transaction():
    clients = db.session.query(Client).order_by(Client.name.asc()).all()
    prods = (db.session.query(Product).filter(Product.active==True)
             .order_by(Product.name.asc(), Product.size_l.asc()).all())
    msg = ""
    if request.method == "POST":
        try:
            dt = datetime.fromisoformat((request.form.get("date") or "").strip()).date()
        except Exception:
            dt = date.today()
        client_id = (request.form.get("client_id") or "").strip()
        typ = (request.form.get("type") or "").strip()
        product_text = (request.form.get("product") or "").strip()
        size_l = int(request.form.get("size_l") or 0)
        qty = int(request.form.get("qty") or 0)
        deposit_manual = request.form.get("deposit_eur")
        deposit_eur = float(deposit_manual) if deposit_manual not in (None, "",) else 0.0
        doc_no = (request.form.get("doc_no") or "").strip() or None
        prod_id = request.form.get("product_id")

        if prod_id:
            p = db.session.get(Product, int(prod_id))
            if p:
                product_text = p.name
                size_l = p.size_l
                if deposit_manual in (None, "",):
                    # signe selon type
                    unit = float(p.deposit_eur or 0.0)
                    deposit_eur = qty * unit if typ == "delivery" else -qty * unit

        if client_id and typ in ("delivery", "pickup") and product_text and size_l > 0 and qty > 0:
            db.session.add(KegTransaction(date=dt, client_id=client_id, type=typ,
                                          product=product_text, size_l=size_l, qty=qty,
                                          deposit_eur=deposit_eur, doc_no=doc_no))
            db.session.commit()
            return redirect(url_for("client_detail", client_id=client_id))
        else:
            msg = "<p style='color:#c00'>Client, Type, Produit, L, Qté requis.</p>"

    opt_clients = "".join([f'<option value="{c.id}">{c.name}</option>' for c in clients]) or '<option value="" disabled>Aucun client</option>'
    opt_prods = "".join([f'<option value="{p.id}">{p.display_name()} — consigne {p.deposit_eur:.2f}€</option>' for p in prods]) or '<option value="" disabled>Aucun produit</option>'
    today_str = date.today().isoformat()
    return _html_page("Ajouter un mouvement client", f"""
<form method="post">
  <div class="row"><label>Date</label><input type="date" name="date" value="{today_str}"></div>
  <div class="row"><label>Client</label>
    <select name="client_id">{opt_clients}</select>
  </div>
  <div class="row"><label>Type</label>
    <select name="type">
      <option value="delivery">delivery (livraison)</option>
      <option value="pickup">pickup (reprise)</option>
    </select>
  </div>

  <div class="row"><label>Produit (catalogue)</label>
    <select name="product_id">
      <option value="">— sélectionner (ou remplir manuel dessous) —</option>
      {opt_prods}
    </select>
  </div>
  <div class="row"><label>OU Produit (manuel)</label><input name="product" placeholder="Coreff Blonde"></div>
  <div class="row"><label>Contenance (L)</label><input type="number" inputmode="numeric" name="size_l" value="30"></div>

  <div class="row"><label>Quantité</label><input type="number" inputmode="numeric" name="qty" value="1"></div>
  <div class="row"><label>Consigne totale (€) — vide = auto (±30€/fût)</label><input type="number" step="0.01" name="deposit_eur" placeholder="auto"></div>
  <div class="row"><label>Doc (BL/RT)</label><input name="doc_no" placeholder="BL-xxxx / RT-xxxx"></div>
  <button type="submit">Enregistrer</button>
</form>
{msg}
<p style="margin-top:10px"><a href="/clients">↳ Voir les clients</a></p>
""")

# Admin: + Fût
@app.route("/admin/add-keg", methods=["GET", "POST"])
def admin_add_keg():
    msg = ""
    if request.method == "POST":
        kid = (request.form.get("id") or "").strip()
        product = (request.form.get("product") or "").strip()
        size_l = int(request.form.get("size_l") or 0)
        status = (request.form.get("status") or "unknown").strip()
        location = (request.form.get("location") or "").strip() or None
        try:
            updated_at = datetime.fromisoformat((request.form.get("updated_at") or "").strip()).date()
        except Exception:
            updated_at = None
        if kid and product and size_l > 0:
            if not db.session.get(Keg, kid):
                db.session.add(Keg(id=kid, product=product, size_l=size_l,
                                   status=status, location=location, updated_at=updated_at))
                db.session.commit()
                return redirect(url_for("kegs_view"))
            else:
                msg = "<p style='color:#c00'>ID de fût déjà existant.</p>"
        else:
            msg = "<p style='color:#c00'>ID, Produit, Contenance requis.</p>"
    today_str = date.today().isoformat()
    return _html_page("Ajouter un fût", f"""
<form method="post">
  <div class="row"><label>ID fût</label><input name="id" placeholder="K-010"></div>
  <div class="row"><label>Produit (texte libre)</label><input name="product" placeholder="Coreff Blonde 30L"></div>
  <div class="row"><label>Contenance (L)</label><input type="number" inputmode="numeric" name="size_l" value="30"></div>
  <div class="row"><label>Statut</label>
    <select name="status">
      <option value="full">full</option>
      <option value="empty">empty</option>
      <option value="lost">lost</option>
      <option value="unknown" selected>unknown</option>
    </select>
  </div>
  <div class="row"><label>Localisation</label><input name="location" placeholder="Chai / Client"></div>
  <div class="row"><label>MàJ (date)</label><input type="date" name="updated_at" value="{today_str}"></div>
  <button type="submit">Enregistrer</button>
</form>
{msg}
<p style="margin-top:10px"><a href="/kegs">↳ Voir les fûts</a></p>
""")

# --------------------------------------------------
# Santé / Diagnostic
# --------------------------------------------------
@app.route("/healthz")
def healthz():
    return jsonify(status="ok", time=datetime.utcnow().isoformat() + "Z", db=DB_URL.split("://",1)[0])

@app.route("/diag")
def diag():
    info = []
    info.append(f"template_folder = {app.template_folder!r}")
    info.append(f"db = {DB_URL.split('://',1)[0]}")
    try:
        _source, filename, _uptodate = app.jinja_env.loader.get_source(app.jinja_env, "index.html")
        info.append(f"index.html trouvé : {filename}")
    except TemplateNotFound:
        info.append("index.html introuvable")
    return "<br>".join(info)

# --------------------------------------------------
# Errors
# --------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "404 Not Found", 404

@app.errorhandler(500)
def internal_error(e):
    err_id = str(uuid4())
    app.logger.exception(f"[{err_id}] 500")
    try:
        return render_template("500.html", error_id=err_id), 500
    except TemplateError:
        return f"500 Internal Server Error — {err_id}", 500

# Local run
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)

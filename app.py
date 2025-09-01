import os
from datetime import date, datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# ---------------------------------------------------------
# Base de données : psycopg3 si DATABASE_URL, sinon SQLite
# ---------------------------------------------------------
def build_db_uri() -> str:
    db_url = os.environ.get("DATABASE_URL", "sqlite:///kegs.db")

    # Normalisation du driver pour SQLAlchemy + psycopg3
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    # Sur Render → forcer sslmode=require si Postgres
    if "RENDER" in os.environ and db_url.startswith("postgresql+psycopg://") and "sslmode=" not in db_url:
        sep = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{sep}sslmode=require"

    return db_url

app.config["SQLALCHEMY_DATABASE_URI"] = build_db_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)

# ----------------
# Modèles simples
# ----------------
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dt = db.Column(db.Date, nullable=False, default=date.today)
    mtype = db.Column(db.String(20), nullable=False)  # 'delivery' ou 'return'
    qty = db.Column(db.Integer, nullable=False, default=0)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    beer_id = db.Column(db.Integer, db.ForeignKey("beer.id"), nullable=False)
    consigne_per_keg = db.Column(db.Float, nullable=False, default=0.0)

    client = db.relationship("Client")
    beer = db.relationship("Beer")

# Création tables si absentes
with app.app_context():
    db.create_all()

# ----------------
# Helpers
# ----------------
def _int(v, d=0):
    try:
        return int(v)
    except Exception:
        return d

def _float(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d

# -----------
# ROUTES UI
# -----------
@app.route("/")
def index():
    deliveries = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "delivery").scalar() or 0
    returns = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "return").scalar() or 0
    outstanding = deliveries - returns

    consigne_charged = (
        db.session.query(func.coalesce(func.sum(Movement.qty * Movement.consigne_per_keg), 0.0))
        .filter(Movement.mtype == "delivery")
        .scalar()
        or 0.0
    )
    consigne_returned = (
        db.session.query(func.coalesce(func.sum(Movement.qty * Movement.consigne_per_keg), 0.0))
        .filter(Movement.mtype == "return")
        .scalar()
        or 0.0
    )
    consigne_balance = consigne_charged - consigne_returned

    return render_template(
        "index.html",
        deliveries=deliveries,
        returns=returns,
        outstanding=outstanding,
        consigne_balance=consigne_balance,
    )

# Clients
@app.route("/clients", methods=["GET", "POST"])
def clients():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Nom client requis", "err")
        else:
            if db.session.query(Client).filter_by(name=name).first():
                flash("Ce client existe déjà.", "err")
            else:
                db.session.add(Client(name=name))
                db.session.commit()
                flash("Client ajouté.", "ok")
        return redirect(url_for("clients"))

    items = Client.query.order_by(Client.name.asc()).all()
    return render_template("clients.html", items=items)

@app.route("/clients/<int:cid>/delete", methods=["POST"])
def client_delete(cid):
    obj = Client.query.get_or_404(cid)
    # sécurité : empêcher suppression si mouvements existants
    has_moves = db.session.query(Movement.id).filter(Movement.client_id == cid).first()
    if has_moves:
        flash("Impossible de supprimer : des mouvements existent pour ce client.", "err")
        return redirect(url_for("clients"))
    db.session.delete(obj)
    db.session.commit()
    flash("Client supprimé.", "ok")
    return redirect(url_for("clients"))

# Bières
@app.route("/beers", methods=["GET", "POST"])
def beers():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Nom bière requis", "err")
        else:
            if db.session.query(Beer).filter_by(name=name).first():
                flash("Cette bière existe déjà.", "err")
            else:
                db.session.add(Beer(name=name))
                db.session.commit()
                flash("Bière ajoutée.", "ok")
        return redirect(url_for("beers"))

    items = Beer.query.order_by(Beer.name.asc()).all()
    return render_template("beers.html", items=items)

@app.route("/beers/<int:bid>/delete", methods=["POST"])
def beer_delete(bid):
    obj = Beer.query.get_or_404(bid)
    has_moves = db.session.query(Movement.id).filter(Movement.beer_id == bid).first()
    if has_moves:
        flash("Impossible de supprimer : des mouvements existent pour cette bière.", "err")
        return redirect(url_for("beers"))
    db.session.delete(obj)
    db.session.commit()
    flash("Bière supprimée.", "ok")
    return redirect(url_for("beers"))

# Mouvements – liste
@app.route("/movements")
def movements():
    q = Movement.query.order_by(Movement.dt.desc(), Movement.id.desc()).all()
    clients = Client.query.order_by(Client.name.asc()).all()
    beers = Beer.query.order_by(Beer.name.asc()).all()
    return render_template("movements.html", moves=q, clients=clients, beers=beers)

# Mouvements – ajout
@app.route("/movements/add", methods=["GET", "POST"])
def movement_add():
    clients = Client.query.order_by(Client.name.asc()).all()
    beers = Beer.query.order_by(Beer.name.asc()).all()

    if request.method == "POST":
        dt_str = request.form.get("dt") or date.today().isoformat()
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d").date()
        except Exception:
            dt = date.today()

        mtype = request.form.get("mtype") or "delivery"
        qty = _int(request.form.get("qty"), 0)
        client_id = _int(request.form.get("client_id"), 0)
        beer_id = _int(request.form.get("beer_id"), 0)
        consigne_per_keg = _float(request.form.get("consigne_per_keg"), 0.0)

        if mtype not in ("delivery", "return"):
            flash("Type de mouvement invalide.", "err")
            return redirect(url_for("movement_add"))
        if qty <= 0:
            flash("Quantité > 0 requise.", "err")
            return redirect(url_for("movement_add"))
        if not Client.query.get(client_id) or not Beer.query.get(beer_id):
            flash("Client ou bière invalide.", "err")
            return redirect(url_for("movement_add"))

        m = Movement(
            dt=dt,
            mtype=mtype,
            qty=qty,
            client_id=client_id,
            beer_id=beer_id,
            consigne_per_keg=consigne_per_keg,
        )
        db.session.add(m)
        db.session.commit()
        flash("Mouvement ajouté.", "ok")
        return redirect(url_for("movements"))

    today_str = date.today().isoformat()
    return render_template("movement_form.html", clients=clients, beers=beers, today_str=today_str)

# Mouvements – suppression (ENDPOINT DEMANDÉ DANS LES LOGS)
@app.route("/movements/<int:mid>/delete", methods=["POST"])
def movement_delete(mid):
    m = Movement.query.get_or_404(mid)
    db.session.delete(m)
    db.session.commit()
    flash("Mouvement supprimé.", "ok")
    return redirect(url_for("movements"))

# Rapport simple
@app.route("/report")
def report():
    deliveries = (
        db.session.query(func.coalesce(func.sum(Movement.qty), 0))
        .filter(Movement.mtype == "delivery")
        .scalar()
        or 0
    )
    returns = (
        db.session.query(func.coalesce(func.sum(Movement.qty), 0))
        .filter(Movement.mtype == "return")
        .scalar()
        or 0
    )
    outstanding = deliveries - returns

    consigne_charged = (
        db.session.query(func.coalesce(func.sum(Movement.qty * Movement.consigne_per_keg), 0.0))
        .filter(Movement.mtype == "delivery")
        .scalar()
        or 0.0
    )
    consigne_returned = (
        db.session.query(func.coalesce(func.sum(Movement.qty * Movement.consigne_per_keg), 0.0))
        .filter(Movement.mtype == "return")
        .scalar()
        or 0.0
    )
    consigne_balance = consigne_charged - consigne_returned

    return render_template(
        "report.html",
        deliveries=deliveries,
        returns=returns,
        outstanding=outstanding,
        consigne_balance=consigne_balance,
    )

# -------------
# Lancement WSGI
# -------------
if __name__ == "__main__":
    app.run(debug=True)

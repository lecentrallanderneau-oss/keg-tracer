# app.py
from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import (
    Flask,
    redirect,
    render_template,
    request,
    url_for,
    flash,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# DB: Render fournit DATABASE_URL. Fallback SQLite pour dev local.
db_url = os.environ.get("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    # SQLAlchemy attend postgresql://
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///keg_tracer.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# Rendre 'date' dispo dans Jinja (évite l'erreur 'date is undefined' dans les templates)
app.jinja_env.globals["date"] = date

# Constantes métier
CONSigne_EUR_PER_KEG = Decimal("30.00")  # 30€ par fût (livraison = débit, retour = crédit)

# -----------------------------------------------------------------------------
# Modèles
# -----------------------------------------------------------------------------
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    price_ttc = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # prix TTC par fût

class Movement(db.Model):
    __tablename__ = "movement"

    id = db.Column(db.Integer, primary_key=True)
    dt = db.Column(db.Date, nullable=False, default=date.today)
    mtype = db.Column(db.String(20), nullable=False)  # 'delivery' ou 'return'
    qty = db.Column(db.Integer, nullable=False, default=1)

    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    beer_id = db.Column(db.Integer, db.ForeignKey("beer.id"), nullable=False)

    # Les champs "gelés" au moment du mouvement
    price_ttc_per_keg = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    consigne_per_keg = db.Column(db.Numeric(10, 2), nullable=False, default=CONSigne_EUR_PER_KEG)

    client = db.relationship("Client")
    beer = db.relationship("Beer")

    # Helpers
    def total_beer_ttc(self) -> Decimal:
        return Decimal(self.price_ttc_per_keg) * self.qty

    def total_consigne(self) -> Decimal:
        # livraison => +30€ par fût ; retour => -30€ par fût (crédit)
        sign = Decimal(1) if self.mtype == "delivery" else Decimal(-1)
        return Decimal(self.consigne_per_keg) * self.qty * sign

    def total_ttc_with_consigne(self) -> Decimal:
        return self.total_beer_ttc() + self.total_consigne()


# -----------------------------------------------------------------------------
# Outils d'affichage
# -----------------------------------------------------------------------------
def eur(value: Decimal | float | int) -> str:
    q = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{q:,.2f}".replace(",", " ").replace(".", ",")  # format français
    return f"{s} €"

app.jinja_env.filters["eur"] = eur


# -----------------------------------------------------------------------------
# Seed du catalogue bières (tes tarifs TTC)
# -----------------------------------------------------------------------------
BEER_CATALOG = [
    # Coreff Blonde
    ("Coreff Blonde 20L", "68.00"),
    ("Coreff Blonde 30L", "102.00"),
    # Coreff Blonde Bio
    ("Coreff Blonde Bio 20L", "74.00"),
    ("Coreff Blonde Bio 30L", "110.00"),
    # Coreff IPA
    ("Coreff IPA 20L", "85.00"),
    ("Coreff IPA 30L", "127.00"),
    # Coreff Blanche (pas de 30L)
    ("Coreff Blanche 20L", "81.00"),
    # Coreff Rousse (uniquement 20L)
    ("Coreff Rousse 20L", "82.00"),
    # Coreff Ambrée (uniquement 22L)
    ("Coreff Ambrée 22L", "78.00"),
    # Cidre Val de Rance (pas de 30L)
    ("Cidre Val de Rance 20L", "96.00"),
]

def seed_beers():
    existing = {b.name for b in Beer.query.all()}
    to_add = []
    for name, price in BEER_CATALOG:
        if name not in existing:
            to_add.append(Beer(name=name, price_ttc=Decimal(price)))
    if to_add:
        db.session.add_all(to_add)
        db.session.commit()

# -----------------------------------------------------------------------------
# Création DB au démarrage (si besoin) + seed
# -----------------------------------------------------------------------------
with app.app_context():
    db.create_all()
    seed_beers()

# -----------------------------------------------------------------------------
# Vues
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    # KPIs simples
    deliveries_qty = db.session.query(func.coalesce(func.sum(Movement.qty), 0)).filter(
        Movement.mtype == "delivery"
    ).scalar() or 0

    returns_qty = db.session.query(func.coalesce(func.sum(Movement.qty), 0)).filter(
        Movement.mtype == "return"
    ).scalar() or 0

    # Sommes € (bière TTC et consignes)
    beer_ttc_total = db.session.query(
        func.coalesce(func.sum(Movement.price_ttc_per_keg * Movement.qty), 0)
    ).scalar() or 0

    consignes_total = Decimal(0)
    for sign, q in db.session.query(Movement.mtype, func.coalesce(func.sum(Movement.qty), 0)).group_by(Movement.mtype):
        if sign == "delivery":
            consignes_total += CONSigne_EUR_PER_KEG * Decimal(q)
        elif sign == "return":
            consignes_total -= CONSigne_EUR_PER_KEG * Decimal(q)

    grand_total = Decimal(beer_ttc_total) + consignes_total

    return render_template(
        "index.html",
        deliveries=deliveries_qty,
        returns=returns_qty,
        beer_ttc_total=beer_ttc_total,
        consignes_total=consignes_total,
        grand_total=grand_total,
    )

# -------- Clients -------------------------------------------------------------
@app.route("/clients", methods=["GET", "POST"])
def clients():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Nom client requis", "error")
        elif Client.query.filter_by(name=name).first():
            flash("Ce client existe déjà", "error")
        else:
            db.session.add(Client(name=name))
            db.session.commit()
            flash("Client ajouté", "ok")
        return redirect(url_for("clients"))

    items = Client.query.order_by(Client.name.asc()).all()
    return render_template("clients.html", clients=items)

# -------- Bières --------------------------------------------------------------
@app.route("/beers", methods=["GET", "POST"])
def beers():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        price = (request.form.get("price_ttc") or "0").replace(",", ".")
        try:
            p = Decimal(price)
        except Exception:
            flash("Prix invalide", "error")
            return redirect(url_for("beers"))

        if not name:
            flash("Nom bière requis", "error")
        elif Beer.query.filter_by(name=name).first():
            flash("Cette bière existe déjà", "error")
        else:
            db.session.add(Beer(name=name, price_ttc=p))
            db.session.commit()
            flash("Bière ajoutée", "ok")
        return redirect(url_for("beers"))

    items = Beer.query.order_by(Beer.name.asc()).all()
    return render_template("beers.html", beers=items)

# -------- Mouvements ----------------------------------------------------------
@app.route("/movements")
def movements():
    q = Movement.query.order_by(Movement.dt.desc(), Movement.id.desc()).all()
    clients = Client.query.order_by(Client.name.asc()).all()
    beers = Beer.query.order_by(Beer.name.asc()).all()
    return render_template("movements.html", moves=q, clients=clients, beers=beers)

@app.route("/movements/add", methods=["GET", "POST"])
def movement_add():
    clients = Client.query.order_by(Client.name.asc()).all()
    beers = Beer.query.order_by(Beer.name.asc()).all()

    if request.method == "POST":
        # Champs du formulaire
        dt_str = request.form.get("dt") or date.today().isoformat()
        try:
            dt_val = datetime.strptime(dt_str, "%Y-%m-%d").date()
        except ValueError:
            dt_val = date.today()

        mtype = request.form.get("mtype") or "delivery"
        client_id = int(request.form.get("client_id") or 0)
        beer_id = int(request.form.get("beer_id") or 0)
        qty = int(request.form.get("qty") or 1)

        # Récup du prix TTC courant de la bière
        beer = Beer.query.get(beer_id)
        if not beer:
            flash("Bière introuvable", "error")
            return redirect(url_for("movements"))

        price_ttc_per_keg = Decimal(beer.price_ttc)

        # Consigne automatique : +30€ par fût (livraison), -30€ (retour)
        consigne = CONSigne_EUR_PER_KEG

        move = Movement(
            dt=dt_val,
            mtype=mtype,
            client_id=client_id,
            beer_id=beer_id,
            qty=qty,
            price_ttc_per_keg=price_ttc_per_keg,
            consigne_per_keg=consigne,
        )
        db.session.add(move)
        db.session.commit()
        flash("Mouvement ajouté", "ok")
        return redirect(url_for("movements"))

    # GET => afficher formulaire
    return render_template("movement_form.html", clients=clients, beers=beers)

@app.route("/movements/<int:mid>/delete", methods=["POST"])
def movement_delete(mid: int):
    m = Movement.query.get_or_404(mid)
    db.session.delete(m)
    db.session.commit()
    flash("Mouvement supprimé", "ok")
    return redirect(url_for("movements"))

# -------- Rapport -------------------------------------------------------------
@app.route("/report")
def report():
    moves = Movement.query.order_by(Movement.dt.asc(), Movement.id.asc()).all()

    beer_ttc_total = sum((m.total_beer_ttc() for m in moves), Decimal(0))
    consignes_total = sum((m.total_consigne() for m in moves), Decimal(0))
    grand_total = beer_ttc_total + consignes_total

    # Regroupement simple par client pour affichage
    by_client = {}
    for m in moves:
        by_client.setdefault(m.client.name, {"beer": Decimal(0), "consigne": Decimal(0), "total": Decimal(0)})
        by_client[m.client.name]["beer"] += m.total_beer_ttc()
        by_client[m.client.name]["consigne"] += m.total_consigne()
        by_client[m.client.name]["total"] += m.total_ttc_with_consigne()

    return render_template(
        "report.html",
        moves=moves,
        beer_ttc_total=beer_ttc_total,
        consignes_total=consignes_total,
        grand_total=grand_total,
        by_client=by_client,
    )

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Pour tests locaux: flask run ou python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

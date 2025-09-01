import os
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from sqlalchemy import case

app = Flask(__name__)

# =========================
# DB CONFIG (psycopg v3)
# =========================
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Render fournit parfois postgres:// ; SQLAlchemy + psycopg attend postgresql+psycopg://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///keg_tracer.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# =========================
# MODELS
# =========================
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)


class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)     # ex: Coreff Blonde
    volume = db.Column(db.String(10), nullable=False)     # ex: 20L, 30L, 22L
    abv = db.Column(db.String(10), nullable=True)         # ex: 5%
    price_ttc = db.Column(db.Float, nullable=False)       # prix TTC / fût


class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dt = db.Column(db.Date, nullable=False, default=date.today)
    mtype = db.Column(db.String(20), nullable=False)  # "Livraison" ou "Retour"
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    beer_id = db.Column(db.Integer, db.ForeignKey("beer.id"), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.String(200))

    client = db.relationship("Client", backref=db.backref("movements", lazy=True))
    beer = db.relationship("Beer", backref=db.backref("movements", lazy=True))

    CONSIGNE = 30.0  # € par fût

    @property
    def consigne_total(self) -> float:
        sgn = 1 if self.mtype == "Livraison" else -1
        return sgn * self.qty * self.CONSIGNE

    @property
    def beer_total(self) -> float:
        sgn = 1 if self.mtype == "Livraison" else -1
        return sgn * self.qty * float(self.beer.price_ttc)

    @property
    def total_ttc(self) -> float:
        return self.beer_total + self.consigne_total


# =========================
# HELPERS
# =========================
def ensure_db():
    """Crée tables + seed si nécessaire. Appelé au début de chaque vue."""
    db.create_all()

    # Seed clients de démo (si vide)
    if not Client.query.first():
        db.session.add_all([
            Client(name="Client A"),
            Client(name="Client B"),
        ])
        db.session.commit()

    # Seed bières (si vide) — avec tes corrections
    if not Beer.query.first():
        seed_beers = [
            # Coreff Blonde
            Beer(name="Coreff Blonde", volume="20L", abv="4.2%", price_ttc=68.0),
            Beer(name="Coreff Blonde", volume="30L", abv="4.2%", price_ttc=102.0),

            # Coreff Blonde Bio
            Beer(name="Coreff Blonde Bio", volume="20L", abv="5%", price_ttc=74.0),
            Beer(name="Coreff Blonde Bio", volume="30L", abv="5%", price_ttc=110.0),

            # Coreff IPA
            Beer(name="Coreff IPA", volume="20L", abv="5.6%", price_ttc=85.0),
            Beer(name="Coreff IPA", volume="30L", abv="5.6%", price_ttc=127.0),

            # Coreff Blanche
            Beer(name="Coreff Blanche", volume="20L", abv="4.4%", price_ttc=81.0),

            # Coreff Rousse (seulement 22L à 78€)
            Beer(name="Coreff Rousse", volume="22L", abv="5.5%", price_ttc=78.0),

            # Coreff Ambrée (TA DEMANDE : seulement 22L à 78€)
            Beer(name="Coreff Ambrée", volume="22L", abv="5%", price_ttc=78.0),

            # Cidre
            Beer(name="Cidre Val de Rance", volume="20L", abv="4.5%", price_ttc=96.0),
        ]
        db.session.bulk_save_objects(seed_beers)
        db.session.commit()


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    ensure_db()
    last_moves = Movement.query.order_by(Movement.dt.desc()).limit(10).all()
    deliveries = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Livraison").scalar() or 0
    returns = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Retour").scalar() or 0
    return render_template("index.html", last_moves=last_moves, deliveries=deliveries, returns=returns)


@app.route("/clients")
def clients():
    ensure_db()
    clients = Client.query.order_by(Client.name.asc()).all()
    return render_template("clients.html", clients=clients)


@app.route("/beers")
def beers():
    ensure_db()
    beers = Beer.query.order_by(Beer.name.asc(), Beer.volume.asc()).all()
    return render_template("beers.html", beers=beers)


@app.route("/movements")
def movements():
    ensure_db()
    moves = Movement.query.order_by(Movement.dt.desc(), Movement.id.desc()).all()
    return render_template("movements.html", moves=moves)


@app.route("/movements/add", methods=["GET", "POST"])
def movement_add():
    ensure_db()
    if request.method == "POST":
        # Form POST
        try:
            dt = datetime.strptime(request.form["dt"], "%Y-%m-%d").date()
        except Exception:
            dt = date.today()

        mtype = request.form.get("mtype")  # "Livraison" ou "Retour"
        client_id = int(request.form.get("client_id"))
        beer_id = int(request.form.get("beer_id"))
        qty = int(request.form.get("qty", "1"))
        notes = request.form.get("notes")

        mv = Movement(dt=dt, mtype=mtype, client_id=client_id, beer_id=beer_id, qty=qty, notes=notes)
        db.session.add(mv)
        db.session.commit()
        return redirect(url_for("movements"))

    clients = Client.query.order_by(Client.name.asc()).all()
    beers = Beer.query.order_by(Beer.name.asc(), Beer.volume.asc()).all()
    today = date.today().strftime("%Y-%m-%d")
    return render_template("movement_add.html", clients=clients, beers=beers, today=today)


@app.route("/movements/<int:mid>/delete", methods=["POST"])
def movement_delete(mid: int):
    ensure_db()
    mv = Movement.query.get_or_404(mid)
    db.session.delete(mv)
    db.session.commit()
    return redirect(url_for("movements"))


@app.route("/report")
def report():
    ensure_db()

    deliveries = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Livraison").scalar() or 0
    returns = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Retour").scalar() or 0

    # Total bières TTC (signé selon mtype), via sqlalchemy.case (compat SQLA 2.x)
    sign = case((Movement.mtype == "Livraison", 1), else_=-1)
    beer_total_signed = (
        db.session.query(func.coalesce(func.sum(sign * Movement.qty * Beer.price_ttc), 0.0))
        .join(Beer, Beer.id == Movement.beer_id)
        .scalar()
        or 0.0
    )

    # Total consigne (30€/fût * (livraisons - retours))
    consigne_total = (deliveries - returns) * Movement.CONSIGNE

    total_ttc = beer_total_signed + consigne_total

    return render_template(
        "report.html",
        deliveries=deliveries,
        returns=returns,
        beer_total_signed=beer_total_signed,
        consigne_total=consigne_total,
        total_ttc=total_ttc,
    )


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    with app.app_context():
        ensure_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

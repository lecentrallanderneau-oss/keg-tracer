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
    name = db.Column(db.String(120), nullable=False)  # ex: Coreff Blonde
    volume = db.Column(db.String(10), nullable=False)  # ex: 20L
    abv = db.Column(db.String(10), nullable=True)      # ex: 5%
    price_ttc = db.Column(db.Float, nullable=False)    # € TTC par fût


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

    CONSIGNE = 30.0  # €/fût

    @property
    def consigne_total(self):
        sgn = 1 if self.mtype == "Livraison" else -1
        return sgn * self.qty * self.CONSIGNE

    @property
    def beer_total(self):
        sgn = 1 if self.mtype == "Livraison" else -1
        return sgn * self.qty * self.beer.price_ttc

    @property
    def total_ttc(self):
        return self.beer_total + self.consigne_total


# =========================
# HELPERS
# =========================
def ensure_db():
    db.create_all()

    if not Client.query.first():
        db.session.add_all([Client(name="Client A"), Client(name="Client B")])
        db.session.commit()

    if not Beer.query.first():
        beers = [
            # Coreff Blonde
            Beer(name="Coreff Blonde", volume="20L", abv="4.2%", price_ttc=68.0),
            Beer(name="Coreff Blonde", volume="30L", abv="4.2%", price_ttc=102.0),

            # Coreff Blonde Bio
            Beer(name="Coreff Blonde Bio", volume="20L", abv="5%", price_ttc=74.0),
            Beer(name="Coreff Blonde Bio", volume="30L", abv="5%", price_ttc=110.0),

            # IPA
            Beer(name="Coreff IPA", volume="20L", abv="5.6%", price_ttc=85.0),
            Beer(name="Coreff IPA", volume="30L", abv="5.6%", price_ttc=127.0),

            # Blanche
            Beer(name="Coreff Blanche", volume="20L", abv="4.4%", price_ttc=81.0),

            # Rousse
            Beer(name="Coreff Rousse", volume="20L", abv="5.5%", price_ttc=82.0),

            # Ambrée (uniquement 22L à 78€)
            Beer(name="Coreff Ambrée", volume="22L", abv="5%", price_ttc=78.0),

            # Cidre
            Beer(name="Cidre Val de Rance", volume="20L", abv="4.5%", price_ttc=96.0),
        ]
        db.session.bulk_save_objects(beers)
        db.session.commit()


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    ensure_db()
    moves = Movement.query.order_by(Movement.dt.desc()).limit(10).all()
    deliveries = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Livraison").scalar() or 0
    returns = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Retour").scalar() or 0
    return render_template("index.html", last_moves=moves, deliveries=deliveries, returns=returns)


@app.route("/clients")
def clients():
    ensure_db()
    return render_template("clients.html", clients=Client.query.order_by(Client.name).all())


@app.route("/beers")
def beers():
    ensure_db()
    return render_template("beers.html", beers=Beer.query.order_by(Beer.name, Beer.volume).all())


@app.route("/movements")
def movements():
    ensure_db()
    return render_template("movements.html", moves=Movement.query.order_by(Movement.dt.desc(), Movement.id.desc()).all())


@app.route("/movements/add", methods=["GET", "POST"])
def movement_add():
    ensure_db()
    if request.method == "POST":
        try:
            dt = datetime.strptime(request.form["dt"], "%Y-%m-%d").date()
        except Exception:
            dt = date.today()
        m = Movement(
            dt=dt,
            mtype=request.form["mtype"],
            client_id=int(request.form["client_id"]),
            beer_id=int(request.form["beer_id"]),
            qty=int(request.form["qty"]),
            notes=request.form.get("notes"),
        )
        db.session.add(m)
        db.session.commit()
        return redirect(url_for("movements"))

    return render_template(
        "movement_add.html",
        today=date.today().strftime("%Y-%m-%d"),
        clients=Client.query.order_by(Client.name).all(),
        beers=Beer.query.order_by(Beer.name, Beer.volume).all(),
    )


@app.route("/movements/<int:mid>/delete", methods=["POST"])
def movement_delete(mid):
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

    sign = case((Movement.mtype == "Livraison", 1), else_=-1)
    beer_total_signed = (
        db.session.query(func.coalesce(func.sum(sign * Movement.qty * Beer.price_ttc), 0.0))
        .join(Beer, Beer.id == Movement.beer_id)
        .scalar()
    )
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


if __name__ == "__main__":
    with app.app_context():
        ensure_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

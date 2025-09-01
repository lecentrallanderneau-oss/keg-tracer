from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from datetime import datetime
import os

app = Flask(__name__)

# --- Configuration base de données ---
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///kegs.db"
).replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# --- Modèles ---
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)


class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    volume = db.Column(db.Integer, nullable=False)  # en litres
    abv = db.Column(db.Float, nullable=True)  # degré alcool
    price_ttc = db.Column(db.Float, nullable=False)  # prix en €
    consigne = db.Column(db.Float, default=30.0)  # 30€ par défaut


class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dt = db.Column(db.Date, default=datetime.utcnow)
    mtype = db.Column(db.String(50), nullable=False)  # delivery, return_full, return_empty
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"))
    beer_id = db.Column(db.Integer, db.ForeignKey("beer.id"))
    qty = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, nullable=True)

    client = db.relationship("Client", backref="movements")
    beer = db.relationship("Beer", backref="movements")

    @property
    def total_consigne(self):
        if self.mtype == "delivery":
            return (self.qty or 0) * (self.beer.consigne if self.beer else 30)
        return 0

    @property
    def total_ttc(self):
        if self.mtype == "delivery" and self.beer:
            return (self.qty or 0) * self.beer.price_ttc
        return 0


# --- Catalogue de bières ---
BEERS_CATALOG = [
    {"name": "Coreff Blonde 30L", "volume": 30, "abv": 5.0, "price_ttc": 135},
    {"name": "Coreff Blanche 30L", "volume": 30, "abv": 4.5, "price_ttc": 135},
    {"name": "Coreff Ambrée 22L", "volume": 22, "abv": 5.2, "price_ttc": 78},
    {"name": "Coreff IPA 30L", "volume": 30, "abv": 6.0, "price_ttc": 145},
    {"name": "Cidre Kerné 20L", "volume": 20, "abv": 4.5, "price_ttc": 95},
]


def reset_and_seed_db():
    """⚠️ Supprime et recrée les tables avec le catalogue de bières"""
    db.drop_all()
    db.create_all()

    # Clients test
    db.session.add(Client(name="Ploudiry"))
    db.session.add(Client(name="Châteauneuf-du-Faou"))

    # Bières
    for b in BEERS_CATALOG:
        beer = Beer(
            name=b["name"],
            volume=b["volume"],
            abv=b.get("abv"),
            price_ttc=b["price_ttc"],
        )
        db.session.add(beer)

    db.session.commit()


# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/clients")
def clients():
    return render_template("clients.html", clients=Client.query.all())


@app.route("/beers")
def beers():
    return render_template("beers.html", beers=Beer.query.all())


@app.route("/movements")
def movements():
    return render_template("movements.html", movements=Movement.query.order_by(Movement.dt.desc()).all())


@app.route("/movements/add", methods=["GET", "POST"])
def add_movement():
    if request.method == "POST":
        m = Movement(
            dt=datetime.strptime(request.form["dt"], "%Y-%m-%d"),
            mtype=request.form["mtype"],
            client_id=request.form["client_id"],
            beer_id=request.form["beer_id"],
            qty=int(request.form["qty"]),
            notes=request.form.get("notes"),
        )
        db.session.add(m)
        db.session.commit()
        return redirect(url_for("movements"))
    return render_template("movement_form.html", clients=Client.query.all(), beers=Beer.query.all())


@app.route("/report")
def report():
    # Totaux
    delivered = (
        db.session.query(func.sum(Movement.qty))
        .filter(Movement.mtype == "delivery")
        .scalar()
        or 0
    )
    returned_full = (
        db.session.query(func.sum(Movement.qty))
        .filter(Movement.mtype == "return_full")
        .scalar()
        or 0
    )
    returned_empty = (
        db.session.query(func.sum(Movement.qty))
        .filter(Movement.mtype == "return_empty")
        .scalar()
        or 0
    )

    total_consigne = sum(m.total_consigne for m in Movement.query.all())
    total_ttc = sum(m.total_ttc for m in Movement.query.all())

    return render_template(
        "report.html",
        delivered=delivered,
        returned_full=returned_full,
        returned_empty=returned_empty,
        total_consigne=total_consigne,
        total_ttc=total_ttc,
        moves=Movement.query.order_by(Movement.dt.desc()).all(),
    )


# --- Lancement ---
if __name__ == "__main__":
    reset_and_seed_db()  # ⚠️ réinitialisation à chaque démarrage
    app.run(host="0.0.0.0", port=5000, debug=True)

import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from datetime import datetime

app = Flask(__name__)

# === Database configuration ===
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Render fournit souvent "postgres://", SQLAlchemy attend "postgresql+psycopg://"
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///keg_tracer.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# === Models ===
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)


class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    volume = db.Column(db.String(10), nullable=False)  # 20L, 30L, 22L...
    abv = db.Column(db.String(10), nullable=True)  # % alcool
    price_ttc = db.Column(db.Float, nullable=False)  # Prix TTC par fût


class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.utcnow)
    mtype = db.Column(db.String(50), nullable=False)  # Livraison ou Retour
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    beer_id = db.Column(db.Integer, db.ForeignKey("beer.id"), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.String(200))

    client = db.relationship("Client", backref=db.backref("movements", lazy=True))
    beer = db.relationship("Beer", backref=db.backref("movements", lazy=True))

    # Consigne = 30€ / fût
    CONSIGNE = 30.0

    @property
    def consigne_total(self):
        return self.qty * self.CONSIGNE if self.mtype == "Livraison" else -self.qty * self.CONSIGNE

    @property
    def beer_total(self):
        return self.qty * self.beer.price_ttc if self.mtype == "Livraison" else -self.qty * self.beer.price_ttc

    @property
    def total_ttc(self):
        return self.beer_total + self.consigne_total


# === Routes ===
@app.route("/")
def index():
    movements = Movement.query.order_by(Movement.date.desc()).limit(10).all()
    return render_template("index.html", movements=movements)


@app.route("/clients")
def clients():
    clients = Client.query.all()
    return render_template("clients.html", clients=clients)


@app.route("/beers")
def beers():
    beers = Beer.query.all()
    return render_template("beers.html", beers=beers)


@app.route("/movements")
def movements():
    movements = Movement.query.order_by(Movement.date.desc()).all()
    return render_template("movements.html", movements=movements)


@app.route("/movements/add", methods=["GET", "POST"])
def add_movement():
    if request.method == "POST":
        date = datetime.strptime(request.form["date"], "%Y-%m-%d")
        mtype = request.form["mtype"]
        client_id = int(request.form["client"])
        beer_id = int(request.form["beer"])
        qty = int(request.form["qty"])
        notes = request.form.get("notes")

        new_move = Movement(date=date, mtype=mtype, client_id=client_id, beer_id=beer_id, qty=qty, notes=notes)
        db.session.add(new_move)
        db.session.commit()
        return redirect(url_for("movements"))

    clients = Client.query.all()
    beers = Beer.query.all()
    return render_template("add_movement.html", clients=clients, beers=beers)


@app.route("/movements/<int:id>/delete", methods=["POST"])
def delete_movement(id):
    move = Movement.query.get_or_404(id)
    db.session.delete(move)
    db.session.commit()
    return redirect(url_for("movements"))


@app.route("/report")
def report():
    deliveries = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Livraison").scalar() or 0
    returns = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "Retour").scalar() or 0

    total_beer = db.session.query(func.sum(Movement.qty * Beer.price_ttc)).join(Beer).filter(Movement.mtype == "Livraison").scalar() or 0
    total_consigne = deliveries * Movement.CONSIGNE - returns * Movement.CONSIGNE

    total = total_beer + total_consigne

    return render_template(
        "report.html",
        deliveries=deliveries,
        returns=returns,
        total_beer=total_beer,
        total_consigne=total_consigne,
        total=total,
    )


# === Init DB ===
@app.before_first_request
def create_tables():
    db.create_all()
    # Préremplissage catalogue Coreff si vide
    if not Beer.query.first():
        beers = [
            Beer(name="Coreff Blonde", volume="20L", abv="4.2", price_ttc=68),
            Beer(name="Coreff Blonde", volume="30L", abv="4.2", price_ttc=102),
            Beer(name="Coreff Blonde Bio", volume="20L", abv="5", price_ttc=74),
            Beer(name="Coreff Blonde Bio", volume="30L", abv="5", price_ttc=110),
            Beer(name="Coreff IPA", volume="20L", abv="5.6", price_ttc=85),
            Beer(name="Coreff IPA", volume="30L", abv="5.6", price_ttc=127),
            Beer(name="Coreff Blanche", volume="20L", abv="4.4", price_ttc=81),
            Beer(name="Coreff Rousse", volume="22L", abv="5.5", price_ttc=78),
            Beer(name="Coreff Ambrée", volume="20L", abv

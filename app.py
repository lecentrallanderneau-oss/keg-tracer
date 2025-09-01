import os
from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from sqlalchemy.sql import func

# -----------------------------------------------------------------------------
# App & DB config
# -----------------------------------------------------------------------------
def _normalize_db_url(raw: str) -> str:
    """
    Normalise l'URL DB pour forcer le driver psycopg (v3) et éviter psycopg2.
    - remplace postgres:// par postgresql+psycopg://
    - remplace postgresql:// (sans driver) par postgresql+psycopg://
    """
    if not raw:
        return "sqlite:///kegs.db"

    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        # si aucun driver explicite, on force psycopg
        if "+psycopg" not in url and "+psycopg2" not in url and "+pg8000" not in url:
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(os.environ.get("DATABASE_URL"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)


class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    volume = db.Column(db.Integer, nullable=False, default=0)        # litres par fût
    abv = db.Column(db.Float, nullable=True)                         # degré
    price_ttc = db.Column(db.Float, nullable=False, default=0.0)     # € TTC par fût
    consigne = db.Column(db.Float, nullable=False, default=30.0)     # € par fût


class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dt = db.Column(db.Date, nullable=False, default=date.today)
    mtype = db.Column(db.String(32), nullable=False)  # delivery | return_full | return_empty
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)
    beer_id = db.Column(db.Integer, db.ForeignKey("beer.id"), nullable=True)
    qty = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)

    client = db.relationship("Client")
    beer = db.relationship("Beer")

    @property
    def total_consigne(self) -> float:
        # la consigne ne s’applique que sur les livraisons
        if self.mtype == "delivery" and self.beer:
            return (self.qty or 0) * (self.beer.consigne or 30.0)
        return 0.0

    @property
    def total_ttc(self) -> float:
        # total TTC bière (hors consigne) pour les livraisons
        if self.mtype == "delivery" and self.beer:
            return (self.qty or 0) * (self.beer.price_ttc or 0.0)
        return 0.0


# -----------------------------------------------------------------------------
# Startup migration & seed
# -----------------------------------------------------------------------------
CATALOG = [
    # Catalogue validé
    {"name": "Coreff Blonde 30L",  "volume": 30, "abv": 5.0, "price_ttc": 135.0},
    {"name": "Coreff Blanche 30L", "volume": 30, "abv": 4.5, "price_ttc": 135.0},
    {"name": "Coreff IPA 30L",     "volume": 30, "abv": 6.0, "price_ttc": 145.0},
    {"name": "Cidre Kerné 20L",    "volume": 20, "abv": 4.5, "price_ttc": 95.0},
    # Spécifique demandé : Coreff Ambrée uniquement 22L à 78 €
    {"name": "Coreff Ambrée 22L",  "volume": 22, "abv": 5.2, "price_ttc": 78.0},
]


def migrate_schema():
    """
    - Crée les tables si elles n'existent pas.
    - Ajoute les colonnes manquantes dans 'beer' (volume, abv, price_ttc, consigne).
    Compatible Postgres & SQLite.
    """
    db.create_all()  # crée tables manquantes sans toucher aux existantes

    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    if "beer" not in tables:
        return

    existing_cols = {c["name"] for c in inspector.get_columns("beer")}

    # Ajouts conditionnels de colonnes
    with db.engine.begin() as conn:
        if "volume" not in existing_cols:
            conn.execute(text("ALTER TABLE beer ADD COLUMN volume INTEGER DEFAULT 0 NOT NULL"))
        if "abv" not in existing_cols:
            # SQLite n’a pas de type float strict, mais accepte FLOAT
            conn.execute(text("ALTER TABLE beer ADD COLUMN abv FLOAT"))
        if "price_ttc" not in existing_cols:
            conn.execute(text("ALTER TABLE beer ADD COLUMN price_ttc FLOAT DEFAULT 0 NOT NULL"))
        if "consigne" not in existing_cols:
            conn.execute(text("ALTER TABLE beer ADD COLUMN consigne FLOAT DEFAULT 30 NOT NULL"))


def seed_if_empty():
    """Insère le catalogue si la table Beer est vide."""
    if db.session.query(Beer).limit(1).first():
        return
    for b in CATALOG:
        db.session.add(
            Beer(
                name=b["name"],
                volume=b["volume"],
                abv=b.get("abv"),
                price_ttc=b["price_ttc"],
                consigne=30.0,
            )
        )
    # quelques clients de base (facultatif)
    if not db.session.query(Client).limit(1).first():
        db.session.add_all([Client(name="Ploudiry"), Client(name="Châteauneuf-du-Faou")])
    db.session.commit()


def ensure_db_ready():
    """À appeler au début de chaque route avant d'interroger Beer."""
    migrate_schema()
    seed_if_empty()


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    ensure_db_ready()
    return render_template("index.html")


@app.route("/beers")
def beers():
    ensure_db_ready()
    beers = Beer.query.order_by(Beer.name.asc()).all()
    return render_template("beers.html", beers=beers)


@app.route("/clients")
def clients():
    ensure_db_ready()
    return render_template("clients.html", clients=Client.query.order_by(Client.name.asc()).all())


@app.route("/movements")
def movements():
    ensure_db_ready()
    moves = Movement.query.order_by(Movement.dt.desc(), Movement.id.desc()).all()
    return render_template("movements.html", movements=moves)


@app.route("/movements/add", methods=["GET", "POST"])
def movement_add():
    ensure_db_ready()
    if request.method == "POST":
        # champs du formulaire
        dt_str = request.form.get("dt") or date.today().isoformat()
        mtype = request.form.get("mtype")  # delivery / return_full / return_empty
        client_id = request.form.get("client_id")
        beer_id = request.form.get("beer_id")
        qty = request.form.get("qty") or "0"
        notes = request.form.get("notes") or None

        try:
            m = Movement(
                dt=datetime.strptime(dt_str, "%Y-%m-%d").date(),
                mtype=mtype,
                client_id=int(client_id) if client_id else None,
                beer_id=int(beer_id) if beer_id else None,
                qty=int(qty),
                notes=notes,
            )
            db.session.add(m)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        return redirect(url_for("movements"))

    return render_template(
        "movement_form.html",
        clients=Client.query.order_by(Client.name.asc()).all(),
        beers=Beer.query.order_by(Beer.name.asc()).all(),
        today=date.today().isoformat(),
    )


@app.route("/movements/<int:mid>/delete", methods=["POST"])
def movement_delete(mid):
    ensure_db_ready()
    m = Movement.query.get_or_404(mid)
    db.session.delete(m)
    db.session.commit()
    return redirect(url_for("movements"))


@app.route("/report")
def report():
    ensure_db_ready()

    delivered = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "delivery").scalar() or 0
    returned_full = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "return_full").scalar() or 0
    returned_empty = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "return_empty").scalar() or 0

    moves = Movement.query.order_by(Movement.dt.desc(), Movement.id.desc()).all()
    total_consigne = sum(m.total_consigne for m in moves)
    total_ttc = sum(m.total_ttc for m in moves)
    total_general = total_ttc + total_consigne

    return render_template(
        "report.html",
        delivered=delivered,
        returned_full=returned_full,
        returned_empty=returned_empty,
        total_consigne=round(total_consigne, 2),
        total_ttc=round(total_ttc, 2),
        total_general=round(total_general, 2),
        moves=moves,
    )


# -----------------------------------------------------------------------------
# Dev server
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # En local :
    ensure_db_ready()
    app.run(host="0.0.0.0", port=5000, debug=True)

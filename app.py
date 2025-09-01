import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

# -------------------------------------------------
# App & DB config
# -------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

raw_uri = os.environ.get("DATABASE_URL", "").strip()
if raw_uri.startswith("postgres://"):
    raw_uri = raw_uri.replace("postgres://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = raw_uri or "sqlite:///local.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Connexions stables (Render)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,  # 30 min
    "pool_size": 5,
    "max_overflow": 5,
}

db = SQLAlchemy(app)

# -------------------------------------------------
# Models
# -------------------------------------------------
class Client(db.Model):
    __tablename__ = "clients"
    # ID string, ex: "C-001"
    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(200), nullable=False)

class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    size_l = db.Column(db.Integer, nullable=False, default=30)
    supplier = db.Column(db.String(200), nullable=True)
    deposit_eur = db.Column(db.Float, nullable=False, default=30.0)
    active = db.Column(db.Boolean, nullable=False, default=True)

class Delivery(db.Model):
    __tablename__ = "deliveries"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    client_id = db.Column(db.String(32), db.ForeignKey("clients.id"), nullable=True)
    supplier = db.Column(db.String(200), nullable=True)  # ex. ton fournisseur
    product = db.Column(db.String(200), nullable=True)   # nom produit "Pale Ale"
    quantity = db.Column(db.Integer, nullable=False, default=0)  # nb fûts (+livraison / -reprise)
    deposit = db.Column(db.Float, nullable=False, default=0.0)   # consigne en €
    invoice_no = db.Column(db.String(100), nullable=True)

class Keg(db.Model):
    __tablename__ = "kegs"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    product = db.Column(db.String(200), nullable=True)
    size_l = db.Column(db.Integer, nullable=False, default=30)
    status = db.Column(db.String(50), nullable=False, default="stock")  # stock / chez_client / vide…
    location = db.Column(db.String(200), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def compute_consigne_balance() -> float:
    total = db.session.query(func.coalesce(func.sum(Delivery.deposit), 0.0)).scalar() or 0.0
    return float(total)

def client_list():
    return db.session.query(Client).order_by(Client.name.asc()).all()

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        consigne_balance=compute_consigne_balance(),
        client_count=db.session.query(func.count(Client.id)).scalar() or 0,
        product_count=db.session.query(func.count(Product.id)).scalar() or 0,
        delivery_count=db.session.query(func.count(Delivery.id)).scalar() or 0,
        keg_count=db.session.query(func.count(Keg.id)).scalar() or 0,
    )

# ---------- Clients ----------
@app.route("/clients", methods=["GET"])
def clients():
    return render_template("clients.html", clients=client_list())

@app.route("/clients/add", methods=["POST"])
def add_client():
    client_id = (request.form.get("id") or "").strip()
    name = (request.form.get("name") or "").strip()
    if not client_id or not name:
        flash("ID et Nom sont requis.", "danger")
        return redirect(url_for("clients"))
    if Client.query.get(client_id):
        flash(f"Un client avec l'ID {client_id} existe déjà.", "warning")
        return redirect(url_for("clients"))
    db.session.add(Client(id=client_id, name=name))
    db.session.commit()
    flash("Client ajouté.", "success")
    return redirect(url_for("clients"))

# Suppression avec ID **string**
@app.route("/clients/delete/<string:client_id>", methods=["POST"])
def delete_client(client_id: str):
    client = Client.query.get_or_404(client_id)
    # Supprimer ses livraisons liées (si tu préfères interdire, on peut bloquer ici)
    Delivery.query.filter_by(client_id=client.id).delete(synchronize_session=False)
    db.session.delete(client)
    db.session.commit()
    flash(f"Client '{client.name}' supprimé.", "success")
    return redirect(url_for("clients"))

# ---------- Catalogue Produits ----------
@app.route("/catalog")
def catalog_view():
    products = (
        db.session.query(Product)
        .filter(Product.active.is_(True))
        .order_by(Product.name.asc(), Product.size_l.asc())
        .all()
    )
    return render_template("catalog.html", products=products)

@app.route("/catalog/add", methods=["POST"])
def add_product():
    name = (request.form.get("name") or "").strip()
    supplier = (request.form.get("supplier") or "").strip()
    size_l = int(request.form.get("size_l") or 30)
    deposit_eur = float(request.form.get("deposit_eur") or 30.0)
    active = True if request.form.get("active") == "on" else False
    if not name:
        flash("Nom produit requis.", "danger")
        return redirect(url_for("catalog_view"))
    prod = Product(name=name, supplier=supplier, size_l=size_l, deposit_eur=deposit_eur, active=active)
    db.session.add(prod)
    db.session.commit()
    flash("Produit ajouté au catalogue.", "success")
    return redirect(url_for("catalog_view"))

# ---------- Livraisons ----------
@app.route("/deliveries")
def deliveries_view():
    rows = (
        db.session.query(Delivery)
        .order_by(Delivery.date.desc())
        .all()
    )
    return render_template("deliveries.html", deliveries=rows)

@app.route("/deliveries/add", methods=["POST"])
def add_delivery():
    # quantity peut être négative pour une reprise
    try:
        date_str = (request.form.get("date") or "").strip()
        date_val = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.utcnow().date()
        client_id = (request.form.get("client_id") or "").strip() or None
        supplier = (request.form.get("supplier") or "").strip()
        product = (request.form.get("product") or "").strip()
        quantity = int(request.form.get("quantity") or 0)
        deposit = float(request.form.get("deposit") or 0.0)
        invoice_no = (request.form.get("invoice_no") or "").strip()
        d = Delivery(
            date=date_val, client_id=client_id, supplier=supplier, product=product,
            quantity=quantity, deposit=deposit, invoice_no=invoice_no
        )
        db.session.add(d)
        db.session.commit()
        flash("Livraison/Retour enregistré(e).", "success")
    except (ValueError, SQLAlchemyError) as e:
        db.session.rollback()
        flash(f"Erreur: {e}", "danger")
    return redirect(url_for("deliveries_view"))

# ---------- Fûts ----------
@app.route("/kegs")
def kegs_view():
    rows = db.session.query(Keg).order_by(Keg.id.asc()).all()
    return render_template("kegs.html", kegs=rows)

@app.route("/kegs/add", methods=["POST"])
def add_keg():
    try:
        product = (request.form.get("product") or "").strip()
        size_l = int(request.form.get("size_l") or 30)
        status = (request.form.get("status") or "stock").strip()
        location = (request.form.get("location") or "").strip()
        k = Keg(product=product, size_l=size_l, status=status, location=location, updated_at=datetime.utcnow())
        db.session.add(k)
        db.session.commit()
        flash("Fût ajouté.", "success")
    except (ValueError, SQLAlchemyError) as e:
        db.session.rollback()
        flash(f"Erreur: {e}", "danger")
    return redirect(url_for("kegs_view"))

# -------------------------------------------------
# Startup: créer les tables si besoin
# -------------------------------------------------
@app.before_request
def ensure_tables():
    # Crée les tables au premier hit si elles n'existent pas
    db.create_all()

# -------------------------------------------------
# Entrypoint local (facultatif)
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))

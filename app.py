import os
from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text, inspect

# -----------------------------------------------------------------------------
# App & DB config
# -----------------------------------------------------------------------------
def _normalized_db_url():
    raw = os.getenv("DATABASE_URL", "sqlite:///keg_tracer.db")
    # Render/Heroku donnent parfois 'postgres://'
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+psycopg://", 1)
    return raw

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

app.config["SQLALCHEMY_DATABASE_URI"] = _normalized_db_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# mieux pour les erreurs transitoires réseau (ex: SSL bad record mac)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class Client(db.Model):
    __tablename__ = "clients"
    # IDs type string (ex: 'C-001')
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(200), nullable=False)

class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    size_l = db.Column(db.Float, nullable=False)
    deposit_eur = db.Column(db.Float, nullable=False, default=0.0)
    supplier = db.Column(db.String(120))
    active = db.Column(db.Boolean, nullable=False, default=True)

class Keg(db.Model):
    __tablename__ = "kegs"
    id = db.Column(db.Integer, primary_key=True)
    product = db.Column(db.String(200), nullable=False)
    size_l = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), nullable=False, default="in_stock")
    location = db.Column(db.String(120))
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

class Delivery(db.Model):
    __tablename__ = "deliveries"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=func.current_date())
    # Colonne problématique dans tes logs -> on la force en String FK facultative
    client_id = db.Column(db.String(64), db.ForeignKey("clients.id"), nullable=True)
    supplier = db.Column(db.String(120))
    # On garde le champ texte 'product' vu dans les logs
    product = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    deposit = db.Column(db.Float, nullable=False, default=0.0)
    invoice_no = db.Column(db.String(120))

# -----------------------------------------------------------------------------
# Startup: create tables + patch colonnes manquantes
# -----------------------------------------------------------------------------
def ensure_schema():
    """Crée les tables manquantes et ajoute certaines colonnes si absentes."""
    db.create_all()

    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    # Si la table deliveries existe mais sans client_id (vu dans logs)
    if "deliveries" in tables:
        cols = {c["name"] for c in inspector.get_columns("deliveries")}
        if "client_id" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE deliveries ADD COLUMN client_id VARCHAR(64)"))
    # On pourrait ajouter d’autres patchs simples ici si besoin.

with app.app_context():
    ensure_schema()

# -----------------------------------------------------------------------------
# Utils
# -----------------------------------------------------------------------------
def compute_consigne_balance() -> float:
    """Somme des dépôts de consigne (évitera 500 si vide)."""
    total = db.session.query(func.coalesce(func.sum(Delivery.deposit), 0.0)).scalar()
    return float(total or 0.0)

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        consigne_balance=compute_consigne_balance(),
        clients_count=db.session.query(func.count(Client.id)).scalar() or 0,
        kegs_count=db.session.query(func.count(Keg.id)).scalar() or 0,
        products_count=db.session.query(func.count(Product.id)).scalar() or 0,
        deliveries_count=db.session.query(func.count(Delivery.id)).scalar() or 0,
    )

# ---- Clients -----------------------------------------------------------------
@app.route("/clients")
def clients():
    rows = Client.query.order_by(Client.name.asc()).all()
    return render_template("clients.html", clients=rows)

@app.route("/admin/add-client", methods=["GET", "POST"])
def admin_add_client():
    if request.method == "POST":
        client_id = (request.form.get("id") or "").strip()
        name = (request.form.get("name") or "").strip()
        if not client_id or not name:
            flash("ID et nom sont obligatoires.", "error")
            return redirect(url_for("admin_add_client"))
        if Client.query.get(client_id):
            flash("Cet ID client existe déjà.", "error")
            return redirect(url_for("admin_add_client"))
        db.session.add(Client(id=client_id, name=name))
        db.session.commit()
        flash("Client ajouté.", "success")
        return redirect(url_for("clients"))
    return render_template("admin_add_client.html")

@app.route("/clients/delete/<string:client_id>", methods=["POST"])
def delete_client(client_id):
    c = Client.query.get(client_id)
    if not c:
        flash("Client introuvable.", "error")
        return redirect(url_for("clients"))
    # On autorise la suppression même si des livraisons pointent dessus (client_id nullable)
    db.session.delete(c)
    db.session.commit()
    flash("Client supprimé.", "success")
    return redirect(url_for("clients"))

# ---- Kegs --------------------------------------------------------------------
@app.route("/kegs")
def kegs():
    rows = Keg.query.order_by(Keg.id.asc()).all()
    return render_template("kegs.html", kegs=rows)

@app.route("/admin/add-keg", methods=["GET", "POST"])
def admin_add_keg():
    if request.method == "POST":
        product = (request.form.get("product") or "").strip()
        size_l = float(request.form.get("size_l") or 0)
        status = (request.form.get("status") or "in_stock").strip()
        location = (request.form.get("location") or "").strip()
        if not product or size_l <= 0:
            flash("Produit et taille (L) obligatoires.", "error")
            return redirect(url_for("admin_add_keg"))
        db.session.add(Keg(product=product, size_l=size_l, status=status, location=location))
        db.session.commit()
        flash("Fût ajouté.", "success")
        return redirect(url_for("kegs"))
    return render_template("admin_add_keg.html")

# ---- Deliveries --------------------------------------------------------------
@app.route("/deliveries")
def deliveries():
    rows = (
        db.session.query(Delivery)
        .order_by(Delivery.date.desc())
        .all()
    )
    return render_template("deliveries.html", deliveries=rows)

@app.route("/admin/add-delivery", methods=["GET", "POST"])
def admin_add_delivery():
    if request.method == "POST":
        try:
            d = request.form.get("date") or ""
            d = date.fromisoformat(d) if d else date.today()
        except Exception:
            d = date.today()
        client_id = (request.form.get("client_id") or "").strip() or None
        supplier = (request.form.get("supplier") or "").strip() or None
        product = (request.form.get("product") or "").strip()
        quantity = int(request.form.get("quantity") or 1)
        deposit = float(request.form.get("deposit") or 0.0)
        invoice_no = (request.form.get("invoice_no") or "").strip() or None

        if not product:
            flash("Produit obligatoire.", "error")
            return redirect(url_for("admin_add_delivery"))

        db.session.add(
            Delivery(
                date=d,
                client_id=client_id,
                supplier=supplier,
                product=product,
                quantity=quantity,
                deposit=deposit,
                invoice_no=invoice_no,
            )
        )
        db.session.commit()
        flash("Livraison ajoutée.", "success")
        return redirect(url_for("deliveries"))

    # Pour aider à saisir
    return render_template("admin_add_delivery.html", clients=Client.query.order_by(Client.name).all())

# ---- Catalogue produits ------------------------------------------------------
@app.route("/catalog")
def catalog():
    rows = Product.query.filter_by(active=True).order_by(Product.name.asc(), Product.size_l.asc()).all()
    return render_template("catalog.html", products=rows)

@app.route("/admin/add-product", methods=["GET", "POST"])
def admin_add_product():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        size_l = float(request.form.get("size_l") or 0)
        deposit_eur = float(request.form.get("deposit_eur") or 0.0)
        supplier = (request.form.get("supplier") or "").strip() or None
        active = request.form.get("active") == "on"
        if not name or size_l <= 0:
            flash("Nom et taille (L) sont obligatoires.", "error")
            return redirect(url_for("admin_add_product"))
        db.session.add(Product(name=name, size_l=size_l, deposit_eur=deposit_eur, supplier=supplier, active=active))
        db.session.commit()
        flash("Produit ajouté.", "success")
        return redirect(url_for("catalog"))
    return render_template("admin_add_product.html")

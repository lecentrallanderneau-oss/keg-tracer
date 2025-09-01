import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from uuid import uuid4

# --- Configuration ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL or "sqlite:///kegs.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --- Modèles ---
class Client(db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    deliveries = db.relationship("Delivery", backref="client", cascade="all, delete-orphan")

class Delivery(db.Model):
    __tablename__ = "deliveries"
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    product = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    deposit = db.Column(db.Float, nullable=False, default=0.0)
    date = db.Column(db.DateTime, server_default=func.now())

# --- Catalogue (issu de ton image) ---
CATALOGUE = [
    {"product": "Coreff Blonde 30L", "price": 155, "consigne": 30},
    {"product": "Coreff Blonde 50L", "price": 240, "consigne": 30},
    {"product": "Coreff Ambrée 30L", "price": 160, "consigne": 30},
    {"product": "Coreff Ambrée 50L", "price": 250, "consigne": 30},
    {"product": "Coreff Blanche 30L", "price": 165, "consigne": 30},
    {"product": "Coreff Blanche 50L", "price": 260, "consigne": 30},
]

# --- Fonctions utilitaires ---
def compute_consigne_balance():
    total = db.session.query(func.coalesce(func.sum(Delivery.deposit), 0.0)).scalar() or 0.0
    return total

# --- Routes ---
@app.route("/")
def index():
    try:
        clients = Client.query.all()
        ctx = {
            "clients": clients,
            "consigne_balance": compute_consigne_balance(),
        }
        return render_template("index.html", **ctx)
    except Exception as e:
        return render_template("500.html", error_id=str(uuid4()), message=str(e)), 500

@app.route("/clients")
def clients():
    return render_template("clients.html", clients=Client.query.all())

@app.route("/clients/add", methods=["POST"])
def add_client():
    name = request.form.get("name")
    if not name:
        flash("Nom du client requis", "danger")
        return redirect(url_for("clients"))
    if Client.query.filter_by(name=name).first():
        flash("Ce client existe déjà.", "warning")
        return redirect(url_for("clients"))

    new_client = Client(name=name)
    db.session.add(new_client)
    db.session.commit()
    flash("Client ajouté avec succès.", "success")
    return redirect(url_for("clients"))

@app.route("/clients/delete/<int:client_id>", methods=["POST"])
def delete_client(client_id):
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    flash("Client supprimé avec succès.", "success")
    return redirect(url_for("clients"))

@app.route("/deliveries")
def deliveries():
    return render_template("deliveries.html", deliveries=Delivery.query.all(), catalogue=CATALOGUE)

@app.route("/deliveries/add", methods=["POST"])
def add_delivery():
    client_id = request.form.get("client_id")
    product = request.form.get("product")
    quantity = int(request.form.get("quantity", 0))

    product_info = next((p for p in CATALOGUE if p["product"] == product), None)
    deposit = product_info["consigne"] if product_info else 30

    delivery = Delivery(client_id=client_id, product=product, quantity=quantity, deposit=deposit)
    db.session.add(delivery)
    db.session.commit()
    flash("Livraison ajoutée avec succès.", "success")
    return redirect(url_for("deliveries"))

# --- Santé ---
@app.route("/healthz")
def healthz():
    return {"status": "ok"}

# --- Init DB ---
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)

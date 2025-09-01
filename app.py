from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import date, datetime
import os

app = Flask(__name__)

# Configuration DB
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///kegs.db").replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------------------
# MODELS
# ---------------------------

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)


class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    size_l = db.Column(db.Integer, default=30)
    price_ttc = db.Column(db.Numeric(10,2), nullable=False, default=0)  # Prix TTC par fût


class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dt = db.Column(db.Date, nullable=False, default=date.today)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    beer_id = db.Column(db.Integer, db.ForeignKey("beer.id"), nullable=False)
    mtype = db.Column(db.String(20), nullable=False)  # delivery / return_full / return_empty
    qty = db.Column(db.Integer, nullable=False, default=1)
    consigne_per_keg = db.Column(db.Numeric(10,2), nullable=False, default=30.00)
    notes = db.Column(db.Text)

    client = db.relationship("Client")
    beer = db.relationship("Beer")

# ---------------------------
# ROUTES
# ---------------------------

@app.route("/")
def index():
    deliveries = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == "del

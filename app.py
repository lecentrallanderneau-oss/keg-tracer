from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, case, text
from sqlalchemy import inspect as sqla_inspect
from datetime import datetime, date, timedelta
import os
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

app = Flask(__name__)

# ---------- DB URL normalisation (psycopg v3 + sslmode=require si manquant) ----------
def _ensure_sslmode(url: str) -> str:
    try:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        if "sslmode" not in q:
            q["sslmode"] = "require"
            p = p._replace(query=urlencode(q))
            return urlunparse(p)
        return url
    except Exception:
        return url

def _normalize_db_url(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    # Render peut fournir "postgres://"
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://") and not raw.startswith("postgresql+psycopg://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    # Forcer sslmode=require si Postgres
    if raw.startswith("postgresql+psycopg://"):
        raw = _ensure_sslmode(raw)
    return raw

_db_url_env = os.getenv("DATABASE_URL", "")
db_url = _normalize_db_url(_db_url_env)

if db_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///kegs.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "change-me"

# Rendre la connexion plus robuste (évite erreurs réseau transitoires)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,   # recycle avant idle timeout typique des proxies
}

db = SQLAlchemy(app)

# ---------- Modèles ----------
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    address = db.Column(db.String(255))
    email = db.Column(db.String(120))
    siret = db.Column(db.String(32))

class Beer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    size_l = db.Column(db.Integer, default=30)

class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dt = db.Column(db.Date, nullable=False, default=date.today)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    beer_id = db.Column(db.Integer, db.ForeignKey('beer.id'), nullable=False)
    mtype = db.Column(db.String(20), nullable=False)  # delivery / return_full / return_empty
    qty = db.Column(db.Integer, nullable=False, default=1)
    consigne_per_keg = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # utilisé pour l’anti-doublon

    client = db.relationship('Client')
    beer = db.relationship('Beer')

# ---------- Init / migration légère ----------
def seed_if_empty():
    if not Client.query.first():
        db.session.add_all([
            Client(name="Client A"),
            Client(name="Client B"),
            Client(name="Client C")
        ])
        db.session.commit()
    if not Beer.query.first():
        db.session.add_all([
            Beer(name="Blonde 30L", size_l=30),
            Beer(name="IPA 20L", size_l=20)
        ])
        db.session.commit()

def ensure_columns():
    """Ajoute la colonne created_at si elle manque (Postgres/SQLite)."""
    insp = sqla_inspect(db.engine)
    cols = [c["name"] for c in insp.get_columns("movement")]
    if "created_at" not in cols:
        if db.engine.name == "postgresql":
            db.session.execute(text(
                "ALTER TABLE movement "
                "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL"
            ))
            # Sécurise les anciennes lignes (au cas où)
            db.session.execute(text(
                "UPDATE movement SET created_at = NOW() WHERE created_at IS NULL"
            ))
        elif db.engine.name == "sqlite":
            # SQLite ne supporte pas NOT NULL sans défaut lors d'un ADD COLUMN
            db.session.execute(text(
                "ALTER TABLE movement "
                "ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ))
            db.session.execute(text(
                "UPDATE movement SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
            ))
        else:
            # Autres SGBD : ajoute une colonne générique
            db.session.execute(text(
                "ALTER TABLE movement ADD COLUMN created_at TIMESTAMP"
            ))
            db.session.execute(text(
                "UPDATE movement SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
            ))
        db.session.commit()

with app.app_context():
    db.create_all()
    ensure_columns()
    seed_if_empty()

# ---------- Routes ----------
@app.route('/')
def index():
    deliveries = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == 'delivery').scalar() or 0
    ret_full   = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == 'return_full').scalar() or 0
    ret_empty  = db.session.query(func.sum(Movement.qty)).filter(Movement.mtype == 'return_empty').scalar() or 0

    outstanding_kegs = deliveries - ret_full
    outstanding_empties = deliveries - ret_empty
    outstanding_consigne = (db.session.query(
        (func.coalesce(func.sum(case((Movement.mtype == 'delivery', Movement.qty * Movement.consigne_per_keg), else_=0)), 0) -
         func.coalesce(func.sum(case((Movement.mtype == 'return_empty', Movement.qty * Movement.consigne_per_keg), else_=0)), 0))
    ).scalar() or 0)

    clients = Client.query.order_by(Client.name).all()
    per_client = []
    for c in clients:
        d  = db.session.query(func.coalesce(func.sum(Movement.qty), 0)).filter(Movement.client_id == c.id, Movement.mtype == 'delivery').scalar() or 0
        rf = db.session.query(func.coalesce(func.sum(Movement.qty), 0)).filter(Movement.client_id == c.id, Movement.mtype == 'return_full').scalar() or 0
        re = db.session.query(func.coalesce(func.sum(Movement.qty), 0)).filter(Movement.client_id == c.id, Movement.mtype == 'return_empty').scalar() or 0
        cons_charge = db.session.query(func.coalesce(func.sum(case((Movement.mtype == 'delivery', Movement.qty * Movement.consigne_per_keg), else_=0)), 0)).filter(Movement.client_id == c.id).scalar() or 0
        cons_refund = db.session.query(func.coalesce(func.sum(case((Movement.mtype == 'return_empty', Movement.qty * Movement.consigne_per_keg), else_=0)), 0)).filter(Movement.client_id == c.id).scalar() or 0
        per_client.append({
            'client': c,
            'delivered': int(d),
            'returned_full': int(rf),
            'returned_empty': int(re),
            'kegs_out': int(d - rf),
            'empties_due': int(d - re),
            'consigne_out': float(cons_charge - cons_refund)
        })

    return render_template('index.html',
        deliveries=int(deliveries),
        ret_full=int(ret_full),
        ret_empty=int(ret_empty),
        outstanding_kegs=int(outstanding_kegs),
        outstanding_empties=int(outstanding_empties),
        outstanding_consigne=float(outstanding_consigne),
        per_client=per_client
    )

# ---- Clients ----
@app.route('/clients')
def clients():
    clients = Client.query.order_by(Client.name).all()
    return render_template('clients.html', clients=clients)

@app.route('/clients/add', methods=['POST'])
def add_client():
    name = request.form['name'].strip()
    address = request.form.get('address', '').strip()
    email = request.form.get('email', '').strip()
    siret = request.form.get('siret', '').strip()
    if name:
        db.session.add(Client(name=name, address=address, email=email, siret=siret))
        db.session.commit()
    return redirect(url_for('clients'))

@app.route('/clients/<int:cid>/delete', methods=['POST'])
def del_client(cid):
    Movement.query.filter_by(client_id=cid).delete()
    Client.query.filter_by(id=cid).delete()
    db.session.commit()
    return redirect(url_for('clients'))

# ---- Bières ----
@app.route('/beers')
def beers():
    beers = Beer.query.order_by(Beer.name).all()
    return render_template('beers.html', beers=beers)

@app.route('/beers/add', methods=['POST'])
def add_beer():
    name = request.form['name'].strip()
    size_l = int(request.form.get('size_l') or 30)
    if name:
        db.session.add(Beer(name=name, size_l=size_l))
        db.session.commit()
    return redirect(url_for('beers'))

@app.route('/beers/<int:bid>/delete', methods=['POST'])
def del_beer(bid):
    Movement.query.filter_by(beer_id=bid).delete()
    Beer.query.filter_by(id=bid).delete()
    db.session.commit()
    return redirect(url_for('beers'))

# ---- Mouvements ----
@app.route('/movements')
def movements():
    q = Movement.query.order_by(Movement.dt.desc(), Movement.id.desc()).limit(200).all()
    clients = Client.query.order_by(Client.name).all()
    beers = Beer.query.order_by(Beer.name).all()
    return render_template('movements.html', moves=q, clients=clients, beers=beers)

@app.route('/movements/add', methods=['GET', 'POST'])
def movement_add():
    """Affiche le formulaire. La création se fait via /api/movement (JS), on ignore le POST HTML."""
    clients = Client.query.order_by(Client.name).all()
    beers = Beer.query.order_by(Beer.name).all()
    if request.method == 'POST':
        return redirect(url_for('movements'))
    return render_template('movement_form.html', clients=clients, beers=beers)

@app.route('/movements/<int:mid>/delete', methods=['POST'])
def movement_delete(mid):
    Movement.query.filter_by(id=mid).delete()
    db.session.commit()
    return redirect(url_for('movements'))

# ---- Reporting ----
@app.route('/report')
def report():
    client_id = request.args.get('client_id', type=int)
    beer_id = request.args.get('beer_id', type=int)
    months_back = request.args.get('months_back', type=int)
    date_from = request.args.get('from')
    date_to = request.args.get('to')

    if months_back is not None:
        today = date.today()
        year = today.year
        month = today.month - months_back
        while month <= 0:
            month += 12
            year -= 1
        start = date(year, month, 1)
        end_month = month + 1
        end_year = year
        if end_month == 13:
            end_month = 1
            end_year += 1
        end = date(end_year, end_month, 1)
    else:
        start = datetime.fromisoformat(date_from).date() if date_from else date.today().replace(day=1)
        end = datetime.fromisoformat(date_to).date() if date_to else date.today() + timedelta(days=1)

    q = Movement.query.filter(Movement.dt >= start, Movement.dt < end)
    if client_id:
        q = q.filter(Movement.client_id == client_id)
    if beer_id:
        q = q.filter(Movement.beer_id == beer_id)

    moves = q.order_by(Movement.dt.asc()).all()

    delivered = sum(m.qty for m in moves if m.mtype == 'delivery')
    returned_full = sum(m.qty for m in moves if m.mtype == 'return_full')
    returned_empty = sum(m.qty for m in moves if m.mtype == 'return_empty')
    consigne_charged = sum(float(m.qty) * float(m.consigne_per_keg) for m in moves if m.mtype == 'delivery')
    consigne_refunded = sum(float(m.qty) * float(m.consigne_per_keg) for m in moves if m.mtype == 'return_empty')

    breakdown = {}
    for m in moves:
        key = m.beer.name
        breakdown.setdefault(key, {'delivered': 0, 'returned_full': 0, 'returned_empty': 0})
        if m.mtype == 'delivery':
            breakdown[key]['delivered'] += m.qty
        elif m.mtype == 'return_full':
            breakdown[key]['returned_full'] += m.qty
        elif m.mtype == 'return_empty':
            breakdown[key]['returned_empty'] += m.qty

    clients = Client.query.order_by(Client.name).all()
    beers = Beer.query.order_by(Beer.name).all()

    return render_template('report.html',
                           moves=moves,
                           delivered=delivered,
                           returned_full=returned_full,
                           returned_empty=returned_empty,
                           consigne_charged=consigne_charged,
                           consigne_refunded=consigne_refunded,
                           breakdown=breakdown,
                           start=start, end=end,
                           clients=clients, beers=beers,
                           selected_client_id=client_id, selected_beer_id=beer_id,
                           months_back=months_back)

# --- API & Health (PWA/offline) ---
@app.route('/api/ping')
def api_ping():
    return jsonify({'ok': True})

@app.route('/api/movement', methods=['POST'])
def api_movement():
    data = request.get_json(force=True) or {}
    try:
        dt_val = datetime.fromisoformat(data.get('dt')).date() if data.get('dt') else date.today()
        mtype = data['mtype']
        client_id = int(data['client_id'])
        beer_id = int(data['beer_id'])
        qty = int(data.get('qty', 1))
        consigne = float(data.get('consigne_per_keg', 0))
        notes = data.get('notes', '')

        # Anti-doublons 30s
        thirty_secs_ago = datetime.utcnow() - timedelta(seconds=30)
        last = (Movement.query
                .filter_by(dt=dt_val, mtype=mtype, client_id=client_id, beer_id=beer_id,
                           qty=qty, consigne_per_keg=consigne, notes=notes)
                .order_by(Movement.id.desc())
                .first())
        if last and last.created_at and last.created_at >= thirty_secs_ago:
            return jsonify({'ok': True, 'id': last.id, 'dedup': True})

        mv = Movement(dt=dt_val, mtype=mtype, client_id=client_id, beer_id=beer_id,
                      qty=qty, consigne_per_keg=consigne, notes=notes)
        db.session.add(mv)
        db.session.commit()
        return jsonify({'ok': True, 'id': mv.id})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/health')
def health():
    return "ok", 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=bool(os.getenv('FLASK_DEBUG', '')))

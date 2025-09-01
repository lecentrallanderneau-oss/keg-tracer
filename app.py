import os
import logging
from uuid import uuid4
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from flask import Flask, render_template, request, jsonify
from jinja2 import TemplateNotFound

# -------------------------------------------------------------------
# Initialisation de l'app Flask
# -------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static") if os.path.isdir(os.path.join(BASE_DIR, "static")) else None,
)

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
app.logger.setLevel(logging.INFO)
if not app.logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
FR_MONTHS = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}

def month_label_fr(d: date) -> str:
    return f"{FR_MONTHS.get(d.month, str(d.month))} {d.year}"

def parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

# -------------------------------------------------------------------
# Données factices (remplace plus tard par ta base/SQL)
# -------------------------------------------------------------------
DELIVERIES: List[Dict[str, Any]] = [
    {"date": "2025-08-28", "supplier": "Coreff", "product": "Blonde 30L", "quantity": 4, "deposit": 60.0, "invoice_no": "F-2025-0812"},
    {"date": "2025-08-21", "supplier": "Bzh Craft", "product": "IPA 20L", "quantity": 3, "deposit": 45.0, "invoice_no": "BC-2025-031"},
]

KEGS: List[Dict[str, Any]] = [
    {"id": "K-001", "product": "Blonde 30L", "size_l": 30, "status": "full", "location": "C_

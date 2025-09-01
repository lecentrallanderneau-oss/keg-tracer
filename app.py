import os
import logging
from uuid import uuid4
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from flask import Flask, render_template, request, jsonify
from jinja2 import TemplateNotFound

# ---------------------------------------------
# Flask app avec chemins explicites
# ---------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static") if os.path.isdir(os.path.join(BASE_DIR, "static")) else None,
)

# ---------------------------------------------
# Logging clair sur Render
# ---------------------------------------------
app.logger.setLevel(logging.INFO)
if not app.logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

# ---------------------------------------------
# Helpers
# ---------------------------------------------
FR_MONTHS = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}

def month_label_fr(d: date) -> str:
    return f"{FR_MONTHS.get(d.month, str(d.month))} {d.year}"

def parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

# ---------------------------------------------
# Données factices (remplace par ta base plus tard)
# ---------------------------------------------
DELIVERIES: List[Dict[str, Any]] = [
    {"date": "2025-

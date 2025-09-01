import os
from datetime import datetime
from flask import Flask, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static") if os.path.isdir(os.path.join(BASE_DIR, "static")) else None,
)

@app.route("/healthz")
def healthz():
    return jsonify(status="ok", time=datetime.utcnow().isoformat() + "Z")

@app.route("/")
def root():
    return "OK : app.py minimal est chargé"

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)


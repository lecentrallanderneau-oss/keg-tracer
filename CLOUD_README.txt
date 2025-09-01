
# Déploiement gratuit (Render + Postgres gratuit)

## Étapes
1. Créez une base Postgres gratuite (Neon, Supabase ou Railway).
   - Récupérez l’URL de connexion (commence par `postgresql://` ou `postgres://`).
2. Sur Render.com → New → Web Service → Connecter votre repo (ou Importer depuis zip une fois poussé sur Git).
3. Lors de la création du service :
   - Runtime: **Python**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app`
   - Variables d’environnement :
     - `DATABASE_URL` = votre URL Postgres (remplace `postgres://` par `postgresql://` si besoin)
     - `FLASK_DEBUG` = (laisser vide)
4. Première ouverture : l’app crée les tables automatiquement.

## Notes
- En local, si `DATABASE_URL` n’est pas défini, l’app utilise `sqlite:///kegs.db`.
- Vous pouvez rester sur SQLite en local et Postgres en ligne, sans rien changer.

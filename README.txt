# Mini appli web locale — Suivi de fûts (livraisons, reprises, consignes)

Cette mini appli Flask fonctionne **en local** (pas besoin d’hébergeur). Elle permet de :
- Enregistrer des **livraisons**, **reprises pleines** et **reprises de vides**
- Suivre les **consignes** (facturées à la livraison, remboursées à la reprise de vide)
- Voir un **tableau de bord** et des **rapports** (par période, client, bière)
- Gérer vos **clients** (3 gros clients) et **bières**

## Installation (Windows/Mac/Linux)

1. Installer **Python 3.10+** : https://www.python.org/downloads/
2. Ouvrir un terminal dans ce dossier et créer un environnement :
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # sous Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Lancer l’appli :
   ```bash
   python app.py
   ```
4. Ouvrir le navigateur sur http://localhost:5000

## Utilisation
- Onglet **Mouvements** → **Ajouter** une livraison / reprise (plein / vide).
- Renseigner la **consigne par fût** lors de la livraison (ex. 30 €). À la reprise du **vide**, indiquez la même consigne pour que le rapport calcule le **remboursement**.
- Onglet **Rapports** : filtrez par période ou utilisez le champ *"Mois N mois en arrière"* (ex. `3` pour le mois d’il y a 3 mois).

## Sauvegardes / Export
- La base est un fichier `kegs.db`. Vous pouvez le sauvegarder/copier.
- Exportez vos tableaux en copiant/collant vers Excel si besoin (fonction export CSV à ajouter si vous le souhaitez).

## Personnalisation
- Barème de consigne différent selon la bière : saisissez la consigne souhaitée à chaque livraison (ou je peux automatiser par bière).
- Droits utilisateurs, exports PDF, etc. → faciles à ajouter plus tard.

# 🎓 Gestion des Bulletins Étudiants

Application web simple permettant de gérer les notes des étudiants, avec calcul automatique des moyennes pondérées par UE/ECU et de la moyenne générale.

## ✨ Fonctionnalités

- **Gestion des étudiants** : ajout et suppression
- **Gestion des UE / ECU** : chaque matière possède un nombre de crédits (coefficient)
- **Composantes multi-enseignants** : une même UE peut être évaluée par plusieurs enseignants (ex : Contrôle continu 40% + Examen 60%), chacun avec son propre poids
- **Saisie progressive des notes** : possibilité de saisir uniquement les notes disponibles, le reste peut être complété plus tard
- **Calcul automatique** :
  - Moyenne de chaque UE = somme des (note × poids de la composante)
  - Moyenne générale = somme des (moyenne UE × crédits) ÷ somme des crédits
- **Export CSV** des résultats pour sauvegarde ou archivage

## 🚀 Utilisation en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre automatiquement dans votre navigateur à l'adresse `http://localhost:8501`.

## 🌐 Déploiement en ligne (gratuit)

1. Pousser ce dépôt sur GitHub (déjà fait ✅)
2. Se rendre sur [share.streamlit.io](https://share.streamlit.io)
3. Cliquer sur **"Create app"** et sélectionner ce dépôt
4. Choisir `app.py` comme fichier principal
5. Cliquer sur **"Deploy"**

## 📋 Ordre d'utilisation recommandé

1. Ajouter les **étudiants** (onglet Étudiants)
2. Créer les **UE/ECU** avec leurs crédits (onglet UE / ECU)
3. Ajouter les **composantes** de chaque UE avec leur poids (onglet Composantes)
4. **Saisir les notes** au fur et à mesure qu'elles arrivent (onglet Saisie des notes)
5. Consulter et **exporter les résultats** (onglet Bulletins & Résultats)

## ⚠️ Note importante sur les données

Les données sont stockées dans une base locale (`bulletins.db`) au sein de l'application. Sur Streamlit Community Cloud, cette base peut être réinitialisée après une longue période d'inactivité ou un redéploiement.

**Recommandation** : téléchargez régulièrement une sauvegarde CSV depuis l'onglet "Bulletins & Résultats".

## 🛠️ Technologies

- [Streamlit](https://streamlit.io) — interface web
- [SQLite](https://www.sqlite.org) — stockage des données
- [Pandas](https://pandas.pydata.org) — traitement des données

## 📄 Licence

Usage libre et gratuit.

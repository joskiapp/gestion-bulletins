import streamlit as st
import sqlite3
import pandas as pd

st.set_page_config(page_title="Gestion des Bulletins", page_icon="🎓", layout="wide")

DB_FILE = "bulletins.db"


# ---------- BASE DE DONNÉES ----------
def get_conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS etudiants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        matricule TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ecus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        credits REAL NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS composantes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ecu_id INTEGER NOT NULL,
        enseignant TEXT,
        libelle TEXT NOT NULL,
        poids REAL NOT NULL,
        FOREIGN KEY(ecu_id) REFERENCES ecus(id) ON DELETE CASCADE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS notes (
        etudiant_id INTEGER NOT NULL,
        composante_id INTEGER NOT NULL,
        note REAL,
        PRIMARY KEY (etudiant_id, composante_id),
        FOREIGN KEY(etudiant_id) REFERENCES etudiants(id) ON DELETE CASCADE,
        FOREIGN KEY(composante_id) REFERENCES composantes(id) ON DELETE CASCADE
    )""")
    conn.commit()
    conn.close()


def df(query, params=()):
    conn = get_conn()
    result = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return result


def execute(query, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id


init_db()

st.title("🎓 Gestion des Bulletins Étudiants")

tabs = st.tabs([
    "👤 Étudiants",
    "📚 UE / ECU",
    "🧩 Composantes",
    "✍️ Saisie des notes",
    "📊 Bulletins & Résultats",
])

# ---------- ONGLET 1 : ÉTUDIANTS ----------
with tabs[0]:
    st.subheader("Liste des étudiants")

    with st.form("form_etudiant", clear_on_submit=True):
        col1, col2 = st.columns(2)
        nom = col1.text_input("Nom complet")
        matricule = col2.text_input("Matricule (optionnel)")
        if st.form_submit_button("➕ Ajouter l'étudiant") and nom.strip():
            execute("INSERT INTO etudiants (nom, matricule) VALUES (?, ?)", (nom.strip(), matricule.strip()))
            st.success(f"Étudiant '{nom}' ajouté.")
            st.rerun()

    etudiants = df("SELECT * FROM etudiants ORDER BY nom")
    if etudiants.empty:
        st.info("Aucun étudiant pour l'instant. Ajoutez-en un ci-dessus.")
    else:
        for _, row in etudiants.iterrows():
            c1, c2, c3 = st.columns([4, 3, 1])
            c1.write(row["nom"])
            c2.write(row["matricule"] or "—")
            if c3.button("🗑️", key=f"del_etu_{row['id']}"):
                execute("DELETE FROM etudiants WHERE id=?", (row["id"],))
                execute("DELETE FROM notes WHERE etudiant_id=?", (row["id"],))
                st.rerun()

# ---------- ONGLET 2 : UE / ECU ----------
with tabs[1]:
    st.subheader("Liste des UE / ECU (matières)")

    with st.form("form_ecu", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        nom_ecu = col1.text_input("Nom de l'UE / ECU")
        credits = col2.number_input("Crédits (coefficient)", min_value=0.5, step=0.5, value=3.0)
        if st.form_submit_button("➕ Ajouter l'UE") and nom_ecu.strip():
            execute("INSERT INTO ecus (nom, credits) VALUES (?, ?)", (nom_ecu.strip(), credits))
            st.success(f"UE '{nom_ecu}' ajoutée.")
            st.rerun()

    ecus = df("SELECT * FROM ecus ORDER BY nom")
    if ecus.empty:
        st.info("Aucune UE pour l'instant. Ajoutez-en une ci-dessus.")
    else:
        for _, row in ecus.iterrows():
            c1, c2, c3 = st.columns([4, 2, 1])
            c1.write(row["nom"])
            c2.write(f"{row['credits']} crédits")
            if c3.button("🗑️", key=f"del_ecu_{row['id']}"):
                comp_ids = df("SELECT id FROM composantes WHERE ecu_id=?", (row["id"],))["id"].tolist()
                for cid in comp_ids:
                    execute("DELETE FROM notes WHERE composante_id=?", (cid,))
                execute("DELETE FROM composantes WHERE ecu_id=?", (row["id"],))
                execute("DELETE FROM ecus WHERE id=?", (row["id"],))
                st.rerun()

# ---------- ONGLET 3 : COMPOSANTES ----------
with tabs[2]:
    st.subheader("Composantes de chaque UE (un ou plusieurs enseignants par UE)")
    st.caption("Ex : 'Contrôle continu' (Enseignant A, poids 40%) + 'Examen final' (Enseignant B, poids 60%)")

    ecus = df("SELECT * FROM ecus ORDER BY nom")
    if ecus.empty:
        st.warning("Créez d'abord une UE dans l'onglet '📚 UE / ECU'.")
    else:
        ecu_choice = st.selectbox("Choisir l'UE", ecus["nom"])
        ecu_id = int(ecus[ecus["nom"] == ecu_choice]["id"].iloc[0])

        composantes = df("SELECT * FROM composantes WHERE ecu_id=?", (ecu_id,))
        poids_actuel = composantes["poids"].sum() if not composantes.empty else 0.0
        st.caption(f"Somme des poids actuels pour cette UE : **{poids_actuel:.0f}%** (visez 100%)")

        with st.form("form_composante", clear_on_submit=True):
            col1, col2, col3 = st.columns([2, 2, 1])
            libelle = col1.text_input("Libellé (ex: Contrôle continu)")
            enseignant = col2.text_input("Enseignant")
            poids = col3.number_input("Poids (%)", min_value=0.0, max_value=100.0, step=5.0, value=50.0)
            if st.form_submit_button("➕ Ajouter la composante") and libelle.strip():
                execute(
                    "INSERT INTO composantes (ecu_id, enseignant, libelle, poids) VALUES (?, ?, ?, ?)",
                    (ecu_id, enseignant.strip(), libelle.strip(), poids),
                )
                st.rerun()

        composantes = df("SELECT * FROM composantes WHERE ecu_id=?", (ecu_id,))
        if not composantes.empty:
            for _, row in composantes.iterrows():
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                c1.write(row["libelle"])
                c2.write(row["enseignant"] or "—")
                c3.write(f"{row['poids']:.0f}%")
                if c4.button("🗑️", key=f"del_comp_{row['id']}"):
                    execute("DELETE FROM notes WHERE composante_id=?", (row["id"],))
                    execute("DELETE FROM composantes WHERE id=?", (row["id"],))
                    st.rerun()

# ---------- ONGLET 4 : SAISIE DES NOTES ----------
with tabs[3]:
    st.subheader("Saisie des notes")

    ecus = df("SELECT * FROM ecus ORDER BY nom")
    etudiants = df("SELECT * FROM etudiants ORDER BY nom")

    if ecus.empty or etudiants.empty:
        st.warning("Il faut au moins un étudiant et une UE (avec ses composantes) avant de saisir des notes.")
    else:
        ecu_choice = st.selectbox("UE à noter", ecus["nom"], key="saisie_ecu")
        ecu_id = int(ecus[ecus["nom"] == ecu_choice]["id"].iloc[0])
        composantes = df("SELECT * FROM composantes WHERE ecu_id=?", (ecu_id,))

        if composantes.empty:
            st.warning("Cette UE n'a pas encore de composante. Ajoutez-en dans l'onglet '🧩 Composantes'.")
        else:
            comp_choice = st.selectbox(
                "Composante (enseignant)",
                composantes.apply(lambda r: f"{r['libelle']} — {r['enseignant'] or 'sans enseignant'}", axis=1),
                key="saisie_comp",
            )
            comp_id = int(composantes.iloc[list(composantes.apply(
                lambda r: f"{r['libelle']} — {r['enseignant'] or 'sans enseignant'}", axis=1)).index(comp_choice)]["id"])

            st.write("Saisissez uniquement les notes que vous avez sous les yeux — le reste peut être complété plus tard.")

            existing = df("SELECT etudiant_id, note FROM notes WHERE composante_id=?", (comp_id,))
            existing_map = dict(zip(existing["etudiant_id"], existing["note"]))

            with st.form("form_notes"):
                new_values = {}
                for _, etu in etudiants.iterrows():
                    val = existing_map.get(etu["id"], None)
                    new_values[etu["id"]] = st.number_input(
                        etu["nom"], min_value=0.0, max_value=20.0, step=0.25,
                        value=float(val) if val is not None else 0.0,
                        key=f"note_{comp_id}_{etu['id']}",
                    )
                if st.form_submit_button("💾 Enregistrer les notes"):
                    for etu_id, note in new_values.items():
                        execute(
                            "INSERT INTO notes (etudiant_id, composante_id, note) VALUES (?, ?, ?) "
                            "ON CONFLICT(etudiant_id, composante_id) DO UPDATE SET note=excluded.note",
                            (etu_id, comp_id, note),
                        )
                    st.success("Notes enregistrées.")
                    st.rerun()

# ---------- ONGLET 5 : RÉSULTATS ----------
with tabs[4]:
    st.subheader("Bulletins et moyennes")

    etudiants = df("SELECT * FROM etudiants ORDER BY nom")
    ecus = df("SELECT * FROM ecus ORDER BY nom")

    if etudiants.empty or ecus.empty:
        st.info("Ajoutez des étudiants et des UE pour voir les résultats.")
    else:
        lignes = []
        for _, etu in etudiants.iterrows():
            moyenne_generale_num = 0.0
            moyenne_generale_den = 0.0
            ligne = {"Étudiant": etu["nom"]}
            for _, ecu in ecus.iterrows():
                composantes = df("SELECT * FROM composantes WHERE ecu_id=?", (ecu["id"],))
                if composantes.empty:
                    moyenne_ue = None
                else:
                    total_poids = composantes["poids"].sum() or 1
                    somme = 0.0
                    for _, comp in composantes.iterrows():
                        note_row = df(
                            "SELECT note FROM notes WHERE etudiant_id=? AND composante_id=?",
                            (etu["id"], comp["id"]),
                        )
                        note = float(note_row["note"].iloc[0]) if not note_row.empty else 0.0
                        somme += note * (comp["poids"] / total_poids)
                    moyenne_ue = somme
                ligne[ecu["nom"]] = round(moyenne_ue, 2) if moyenne_ue is not None else "—"
                if moyenne_ue is not None:
                    moyenne_generale_num += moyenne_ue * ecu["credits"]
                    moyenne_generale_den += ecu["credits"]
            ligne["Moyenne générale"] = (
                round(moyenne_generale_num / moyenne_generale_den, 2) if moyenne_generale_den > 0 else "—"
            )
            lignes.append(ligne)

        resultats = pd.DataFrame(lignes)
        st.dataframe(resultats, use_container_width=True, hide_index=True)

        csv = resultats.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Télécharger les résultats (CSV)", csv, "resultats.csv", "text/csv")

        st.divider()
        st.caption(
            "💾 Astuce : téléchargez régulièrement une sauvegarde CSV. "
            "Sur Streamlit Cloud, la base peut être réinitialisée après une longue inactivité ou un redéploiement."
        )

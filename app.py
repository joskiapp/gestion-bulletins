import streamlit as st
import pandas as pd
import sqlite3
import os
import sys
import json

st.set_page_config(page_title="Calculatrice de Bulletins", page_icon="🧮", layout="wide")

MAX_ROWS = 500


# ---------- STOCKAGE PERSISTANT ----------
def get_data_dir():
    """Dossier stable et inscriptible, que l'app tourne en script ou en exécutable."""
    if getattr(sys, "frozen", False):
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "GestionBulletins")
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(base, exist_ok=True)
    return base


DB_FILE = os.path.join(get_data_dir(), "calculatrice.db")


def get_conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    conn = get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


def save_state(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()
    conn.close()


def load_state(key, default):
    conn = get_conn()
    row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else default


init_db()

# ---------- INITIALISATION DE L'ÉTAT ----------
if "reference_df" not in st.session_state:
    saved = load_state("reference_df", None)
    if saved:
        st.session_state.reference_df = pd.DataFrame(saved)
    else:
        st.session_state.reference_df = pd.DataFrame(
            {"Nom": [""] * MAX_ROWS, "Prénom": [""] * MAX_ROWS, "Matricule": [""] * MAX_ROWS}
        )

if "grades" not in st.session_state:
    st.session_state.grades = load_state("grades", {})  # clé: index de ligne (str) -> note


def persist_all():
    save_state("reference_df", st.session_state.reference_df.to_dict(orient="list"))
    save_state("grades", st.session_state.grades)


st.title("🧮 Calculatrice de Bulletins")
st.caption("Liste de référence → saisie désordonnée des notes → résultat toujours dans l'ordre officiel")

tab1, tab2, tab3 = st.tabs(["📋 1. Liste de référence", "✍️ 2. Saisie des notes", "📊 3. Résultat final"])

# ============================================================
# ONGLET 1 : LISTE DE RÉFÉRENCE
# ============================================================
with tab1:
    st.subheader("Liste de référence (ordre officiel de la scolarité)")
    st.info(
        "📌 Copiez la liste (Nom, Prénom, Matricule) depuis votre fichier Excel, "
        "cliquez sur la première cellule ci-dessous, puis collez (Ctrl+V). "
        "L'ordre des lignes collées devient l'ordre officiel du bulletin final."
    )

    edited_df = st.data_editor(
        st.session_state.reference_df,
        num_rows="fixed",
        use_container_width=True,
        height=420,
        key="reference_editor",
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("💾 Enregistrer la liste"):
            st.session_state.reference_df = edited_df
            persist_all()
            st.success("Liste enregistrée.")
            st.rerun()
    with col2:
        if st.button("🗑️ Effacer la liste (et le résultat final)", type="secondary"):
            st.session_state.reference_df = pd.DataFrame(
                {"Nom": [""] * MAX_ROWS, "Prénom": [""] * MAX_ROWS, "Matricule": [""] * MAX_ROWS}
            )
            st.session_state.grades = {}  # effacement en cascade du résultat
            persist_all()
            st.success("Liste et résultats effacés. Vous pouvez coller une nouvelle liste.")
            st.rerun()

    nb_etudiants = (st.session_state.reference_df["Nom"].astype(str).str.strip() != "").sum()
    st.caption(f"👥 {nb_etudiants} étudiant(s) actuellement dans la liste.")

# ============================================================
# ONGLET 2 : SAISIE DES NOTES (recherche par nom, ordre libre)
# ============================================================
with tab2:
    st.subheader("Saisie des notes (dans n'importe quel ordre)")

    ref = st.session_state.reference_df
    valid_mask = ref["Nom"].astype(str).str.strip() != ""
    valid_indices = ref.index[valid_mask].tolist()

    if not valid_indices:
        st.warning("Aucune liste de référence trouvée. Allez d'abord dans l'onglet '📋 1. Liste de référence'.")
    else:
        options = {
            idx: f"{ref.loc[idx, 'Nom']} {ref.loc[idx, 'Prénom']}"
            + (f" — {ref.loc[idx, 'Matricule']}" if str(ref.loc[idx, "Matricule"]).strip() else "")
            for idx in valid_indices
        }

        col1, col2 = st.columns([3, 1])
        with col1:
            chosen_idx = st.selectbox(
                "🔍 Tapez 2-3 lettres du nom pour le retrouver",
                options=list(options.keys()),
                format_func=lambda i: options[i],
                index=None,
                placeholder="Rechercher un étudiant...",
                key="search_student",
            )
        with col2:
            note_val = st.number_input("Note /20", min_value=0.0, max_value=20.0, step=0.25, key="note_input")

        if st.button("✅ Enregistrer cette note", type="primary", disabled=chosen_idx is None):
            st.session_state.grades[str(chosen_idx)] = note_val
            persist_all()
            st.success(f"Note enregistrée pour {options[chosen_idx]}.")
            st.rerun()

        st.divider()
        st.write("**Notes saisies jusqu'à présent (ordre de saisie) :**")
        if st.session_state.grades:
            saisie = []
            for idx_str, note in st.session_state.grades.items():
                idx = int(idx_str)
                if idx in options:
                    saisie.append({"Étudiant": options[idx], "Note": note})
            st.dataframe(pd.DataFrame(saisie), use_container_width=True, hide_index=True)
        else:
            st.caption("Aucune note saisie pour l'instant.")

# ============================================================
# ONGLET 3 : RÉSULTAT FINAL (toujours dans l'ordre de la liste)
# ============================================================
with tab3:
    st.subheader("Résultat final — dans l'ordre officiel de la liste")

    ref = st.session_state.reference_df
    valid_mask = ref["Nom"].astype(str).str.strip() != ""
    valid_ref = ref[valid_mask].copy()

    if valid_ref.empty:
        st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    else:
        rows = []
        for idx in valid_ref.index:
            note = st.session_state.grades.get(str(idx), None)
            rows.append({
                "Ordre": len(rows) + 1,
                "Nom": valid_ref.loc[idx, "Nom"],
                "Prénom": valid_ref.loc[idx, "Prénom"],
                "Matricule": valid_ref.loc[idx, "Matricule"],
                "Note": note if note is not None else "",
            })

        resultat_df = pd.DataFrame(rows)

        st.caption("💡 Astuce : cliquez-glissez pour sélectionner des cellules, puis Ctrl+C pour copier vers Excel.")
        st.dataframe(resultat_df, use_container_width=True, hide_index=True, height=460)

        nb_notes = sum(1 for r in rows if r["Note"] != "")
        st.caption(f"📝 {nb_notes} note(s) saisie(s) sur {len(rows)} étudiant(s).")

        col1, col2, col3 = st.columns([1, 1, 3])
        with col1:
            csv = resultat_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Télécharger en CSV", csv, "resultat_final.csv", "text/csv")
        with col2:
            if st.button("🗑️ Effacer seulement les notes", type="secondary"):
                st.session_state.grades = {}
                persist_all()
                st.success("Notes effacées. La liste de référence est conservée.")
                st.rerun()

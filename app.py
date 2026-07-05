import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import os
import sys
import json
import html as html_lib

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
            {"Nom et Prénom": [""] * MAX_ROWS, "Matricule": [""] * MAX_ROWS}
        )

if "grades" not in st.session_state:
    # structure : { "index_etudiant": { "Matière": note, ... }, ... }
    st.session_state.grades = load_state("grades", {})

if "matieres" not in st.session_state:
    st.session_state.matieres = load_state("matieres", [])  # liste des matières déjà utilisées


def persist_all():
    save_state("reference_df", st.session_state.reference_df.to_dict(orient="list"))
    save_state("grades", st.session_state.grades)
    save_state("matieres", st.session_state.matieres)


def split_nom_prenom(nom_complet):
    """Sépare 'Nom et Prénom' collé en deux parties : premier mot = Nom, reste = Prénom."""
    parts = str(nom_complet).strip().split(" ", 1)
    nom = parts[0] if parts else ""
    prenom = parts[1] if len(parts) > 1 else ""
    return nom, prenom


def tableau_selectionnable(df, height=460):
    """Affiche un tableau HTML où l'on peut cliquer-glisser pour sélectionner une plage
    de cellules (comme Excel), puis Ctrl+C pour la copier vers le presse-papiers."""
    cols = list(df.columns)
    header_html = "".join(f"<th>{html_lib.escape(str(c))}</th>" for c in cols)
    body_html = ""
    for r, (_, row) in enumerate(df.iterrows()):
        cells = "".join(
            f'<td data-r="{r}" data-c="{c}">{html_lib.escape(str(row[col]))}</td>'
            for c, col in enumerate(cols)
        )
        body_html += f"<tr>{cells}</tr>"

    page = f"""
    <style>
      .sel-table-wrap {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; overflow: auto;
                          max-height: {height}px; border: 1px solid #444; border-radius: 6px; }}
      table.sel-table {{ border-collapse: collapse; width: 100%; font-size: 14px; user-select: none; }}
      table.sel-table th {{ position: sticky; top: 0; background:#2E74B5; color: white;
                             padding: 6px 10px; text-align: left; white-space: nowrap; }}
      table.sel-table td {{ padding: 5px 10px; border: 1px solid #3a3a3a; white-space: nowrap; color: #eee; }}
      table.sel-table td.selected {{ background: #2E74B5; color: white; }}
      .copy-msg {{ font-size: 12px; color: #70AD47; margin-top: 4px; height: 16px; }}
    </style>
    <div class="sel-table-wrap">
      <table class="sel-table" id="selTable">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    <div class="copy-msg" id="copyMsg"></div>
    <script>
      const table = document.getElementById("selTable");
      const msg = document.getElementById("copyMsg");
      let isSelecting = false;
      let startCell = null;

      function clearSelection() {{
        table.querySelectorAll("td.selected").forEach(td => td.classList.remove("selected"));
      }}

      function selectRange(r1, c1, r2, c2) {{
        clearSelection();
        const rMin = Math.min(r1, r2), rMax = Math.max(r1, r2);
        const cMin = Math.min(c1, c2), cMax = Math.max(c1, c2);
        table.querySelectorAll("td").forEach(td => {{
          const r = parseInt(td.dataset.r), c = parseInt(td.dataset.c);
          if (r >= rMin && r <= rMax && c >= cMin && c <= cMax) td.classList.add("selected");
        }});
      }}

      table.addEventListener("mousedown", (e) => {{
        const td = e.target.closest("td");
        if (!td) return;
        isSelecting = true;
        startCell = td;
        selectRange(+td.dataset.r, +td.dataset.c, +td.dataset.r, +td.dataset.c);
        e.preventDefault();
      }});

      table.addEventListener("mouseover", (e) => {{
        if (!isSelecting) return;
        const td = e.target.closest("td");
        if (!td) return;
        selectRange(+startCell.dataset.r, +startCell.dataset.c, +td.dataset.r, +td.dataset.c);
      }});

      document.addEventListener("mouseup", () => {{ isSelecting = false; }});

      function getSelectedAsTSV() {{
        const selected = Array.from(table.querySelectorAll("td.selected"));
        if (selected.length === 0) return "";
        const rows = {{}};
        selected.forEach(td => {{
          const r = +td.dataset.r, c = +td.dataset.c;
          if (!rows[r]) rows[r] = {{}};
          rows[r][c] = td.innerText;
        }});
        const rIdx = Object.keys(rows).map(Number).sort((a,b)=>a-b);
        return rIdx.map(r => {{
          const cIdx = Object.keys(rows[r]).map(Number).sort((a,b)=>a-b);
          return cIdx.map(c => rows[r][c]).join("\\t");
        }}).join("\\n");
      }}

      document.addEventListener("keydown", async (e) => {{
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") {{
          const text = getSelectedAsTSV();
          if (!text) return;
          try {{
            await navigator.clipboard.writeText(text);
            msg.innerText = "✅ Copié ! Vous pouvez coller dans Excel (Ctrl+V).";
          }} catch (err) {{
            msg.innerText = "⚠️ Copie automatique bloquée par le navigateur — réessayez.";
          }}
          setTimeout(() => {{ msg.innerText = ""; }}, 3000);
        }}
      }});
    </script>
    """
    components.html(page, height=height + 40, scrolling=True)


st.title("🧮 Calculatrice de Bulletins")
st.caption("Liste de référence → saisie désordonnée des notes → résultat toujours dans l'ordre officiel")

tab1, tab2, tab3 = st.tabs(["📋 1. Liste de référence", "✍️ 2. Saisie des notes", "📊 3. Résultat final"])

# ============================================================
# ONGLET 1 : LISTE DE RÉFÉRENCE
# ============================================================
with tab1:
    st.subheader("Liste de référence (ordre officiel de la scolarité)")

    if st.button("🗑️ Effacer la liste (et le résultat final)", type="secondary"):
        st.session_state.reference_df = pd.DataFrame(
            {"Nom et Prénom": [""] * MAX_ROWS, "Matricule": [""] * MAX_ROWS}
        )
        st.session_state.grades = {}  # effacement en cascade du résultat
        persist_all()
        st.success("Liste et résultats effacés. Vous pouvez coller une nouvelle liste.")
        st.rerun()

    nb_etudiants = (st.session_state.reference_df["Nom et Prénom"].astype(str).str.strip() != "").sum()
    st.caption(f"👥 {nb_etudiants} étudiant(s) actuellement reconnu(s) dans la liste.")

    st.info(
        "📌 Collez votre liste telle que fournie par la scolarité : une seule colonne "
        "'Nom et Prénom' (les deux ensemble, comme dans votre fichier), et le Matricule si disponible. "
        "Cliquez sur la première cellule ci-dessous, puis collez (Ctrl+V). "
        "**La reconnaissance est automatique**, dès que vous collez. "
        "Double-cliquez sur une cellule pour corriger une valeur ; cliquez-glissez pour sélectionner une plage."
    )

    edited_df = st.data_editor(
        st.session_state.reference_df,
        num_rows="fixed",
        use_container_width=True,
        height=420,
        key="reference_editor",
    )

    # Reconnaissance automatique : dès que le tableau change, on l'enregistre immédiatement
    if not edited_df.equals(st.session_state.reference_df):
        st.session_state.reference_df = edited_df
        persist_all()
        st.rerun()

# ============================================================
# ONGLET 2 : SAISIE DES NOTES (recherche par nom, ordre libre)
# ============================================================
with tab2:
    st.subheader("Saisie des notes (dans n'importe quel ordre)")

    ref = st.session_state.reference_df
    valid_mask = ref["Nom et Prénom"].astype(str).str.strip() != ""
    valid_indices = ref.index[valid_mask].tolist()

    if not valid_indices:
        st.warning("Aucune liste de référence trouvée. Allez d'abord dans l'onglet '📋 1. Liste de référence'.")
    else:
        options = {
            idx: f"{ref.loc[idx, 'Nom et Prénom']}"
            + (f" — {ref.loc[idx, 'Matricule']}" if str(ref.loc[idx, "Matricule"]).strip() else "")
            for idx in valid_indices
        }

        matiere_defaut = st.session_state.matieres[-1] if st.session_state.matieres else ""
        col0, col1, col2 = st.columns([2, 3, 1])
        with col0:
            matiere = st.text_input(
                "📚 Matière", value=matiere_defaut, placeholder="Ex: Mathématiques", key="matiere_input"
            )
        with col1:
            chosen_idx = st.selectbox(
                "🔍 Tapez 2-3 lettres du nom ou prénom pour le retrouver",
                options=list(options.keys()),
                format_func=lambda i: options[i],
                index=None,
                placeholder="Rechercher un étudiant...",
                key="search_student",
            )
        with col2:
            note_val = st.number_input("Note /20", min_value=0.0, max_value=20.0, step=0.25, key="note_input")

        if st.button("✅ Enregistrer cette note", type="primary", disabled=(chosen_idx is None or not matiere.strip())):
            idx_str = str(chosen_idx)
            if idx_str not in st.session_state.grades:
                st.session_state.grades[idx_str] = {}
            st.session_state.grades[idx_str][matiere.strip()] = note_val
            if matiere.strip() not in st.session_state.matieres:
                st.session_state.matieres.append(matiere.strip())
            persist_all()
            st.success(f"Note enregistrée pour {options[chosen_idx]} en {matiere.strip()}.")
            st.rerun()

        st.divider()
        st.write("**Notes saisies jusqu'à présent (ordre de saisie) :**")
        lignes_saisie = []
        for idx_str, matieres_notes in st.session_state.grades.items():
            idx = int(idx_str)
            if idx in options:
                for mat, note in matieres_notes.items():
                    lignes_saisie.append({"Étudiant": options[idx], "Matière": mat, "Note": note})
        if lignes_saisie:
            st.dataframe(pd.DataFrame(lignes_saisie), use_container_width=True, hide_index=True)
        else:
            st.caption("Aucune note saisie pour l'instant.")

# ============================================================
# ONGLET 3 : RÉSULTAT FINAL (toujours dans l'ordre de la liste)
# ============================================================
with tab3:
    st.subheader("Résultat final — dans l'ordre officiel de la liste")

    ref = st.session_state.reference_df
    valid_mask = ref["Nom et Prénom"].astype(str).str.strip() != ""
    valid_ref = ref[valid_mask].copy()

    if valid_ref.empty:
        st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    else:
        matieres = st.session_state.matieres  # ordre d'apparition des matières

        col1, col2, col3 = st.columns([1, 1, 3])
        with col1:
            rows_preview = []
            for idx in valid_ref.index:
                notes_etu = st.session_state.grades.get(str(idx), {})
                nom, prenom = split_nom_prenom(valid_ref.loc[idx, "Nom et Prénom"])
                row = {"Ordre": len(rows_preview) + 1, "Nom": nom, "Prénom": prenom,
                       "Matricule": valid_ref.loc[idx, "Matricule"]}
                notes_numeriques = []
                for mat in matieres:
                    val = notes_etu.get(mat, "")
                    row[mat] = val
                    if val != "":
                        notes_numeriques.append(val)
                row["Moyenne"] = round(sum(notes_numeriques) / len(notes_numeriques), 2) if notes_numeriques else ""
                rows_preview.append(row)
            csv = pd.DataFrame(rows_preview).to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ CSV", csv, "resultat_final.csv", "text/csv")
        with col2:
            if st.button("🗑️ Effacer les notes", type="secondary"):
                st.session_state.grades = {}
                st.session_state.matieres = []
                persist_all()
                st.success("Notes effacées. La liste de référence est conservée.")
                st.rerun()

        resultat_df = pd.DataFrame(rows_preview)
        nb_notes = sum(1 for idx in valid_ref.index if st.session_state.grades.get(str(idx)))
        st.caption(f"📝 {nb_notes} étudiant(s) avec au moins une note, sur {len(rows_preview)} au total "
                   f"— {len(matieres)} matière(s) : {', '.join(matieres) if matieres else 'aucune'}.")

        st.caption("💡 Cliquez-glissez pour sélectionner une plage de cellules, puis Ctrl+C pour copier vers Excel.")
        tableau_selectionnable(resultat_df, height=460)

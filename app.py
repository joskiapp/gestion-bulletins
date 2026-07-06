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

if "matieres_df" not in st.session_state:
    saved_mat = load_state("matieres_df", None)
    if saved_mat:
        st.session_state.matieres_df = pd.DataFrame(saved_mat)
    else:
        st.session_state.matieres_df = pd.DataFrame({"Matière": [""] * 50})

if "grades" not in st.session_state:
    # structure : { "index_etudiant": { "Matière": note, ... }, ... }
    st.session_state.grades = load_state("grades", {})

if "matieres" not in st.session_state:
    st.session_state.matieres = load_state("matieres", [])  # liste des matières déjà utilisées

if "annee_etudes" not in st.session_state:
    st.session_state.annee_etudes = load_state("annee_etudes", "")

if "filiere" not in st.session_state:
    st.session_state.filiere = load_state("filiere", "")


def persist_all():
    save_state("reference_df", st.session_state.reference_df.to_dict(orient="list"))
    save_state("grades", st.session_state.grades)
    save_state("matieres", st.session_state.matieres)
    save_state("matieres_df", st.session_state.matieres_df.to_dict(orient="list"))
    save_state("annee_etudes", st.session_state.annee_etudes)
    save_state("filiere", st.session_state.filiere)


def split_nom_prenom(nom_complet):
    """Sépare 'Nom et Prénom' collé en deux parties : premier mot = Nom, reste = Prénom."""
    parts = str(nom_complet).strip().split(" ", 1)
    nom = parts[0] if parts else ""
    prenom = parts[1] if len(parts) > 1 else ""
    return nom, prenom


def tableau_selectionnable(df, height=460):
    """Affiche un tableau HTML où l'on peut cliquer-glisser pour sélectionner une plage
    de cellules (comme Excel), avec défilement automatique en bordure, copie via Ctrl+C
    ou clic droit → Copier."""
    cols = list(df.columns)
    header_html = "".join(f"<th>{html_lib.escape(str(c))}</th>" for c in cols)
    body_html = ""
    for r, (_, row) in enumerate(df.iterrows()):
        cells = "".join(
            f'<td data-r="{r}" data-c="{c}">{html_lib.escape("" if pd.isna(row[col]) else str(row[col]))}</td>'
            for c, col in enumerate(cols)
        )
        body_html += f"<tr>{cells}</tr>"

    page = f"""
    <style>
      .sel-table-wrap {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; overflow: auto;
                          max-height: {height}px; border: 1px solid #444; border-radius: 6px; position: relative; }}
      table.sel-table {{ border-collapse: collapse; width: 100%; font-size: 14px; user-select: none; }}
      table.sel-table th {{ position: sticky; top: 0; background:#2E74B5; color: white;
                             padding: 6px 10px; text-align: left; white-space: nowrap; z-index: 2; }}
      table.sel-table td {{ padding: 5px 10px; border: 1px solid #3a3a3a; white-space: nowrap; color: #eee; }}
      table.sel-table td.selected {{ background: #2E74B5; color: white; }}
      .copy-msg {{ font-size: 12px; color: #70AD47; margin-top: 4px; height: 16px; }}
      .ctx-menu {{ position: fixed; display: none; background: #2b2b2b; border: 1px solid #555;
                   border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); z-index: 9999;
                   font-family: -apple-system, Segoe UI, Arial, sans-serif; font-size: 14px; overflow: hidden; }}
      .ctx-menu div {{ padding: 8px 16px; color: #eee; cursor: pointer; white-space: nowrap; }}
      .ctx-menu div:hover {{ background: #2E74B5; }}
    </style>
    <div class="sel-table-wrap" id="wrap">
      <table class="sel-table" id="selTable">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    <div class="copy-msg" id="copyMsg"></div>
    <div class="ctx-menu" id="ctxMenu">
      <div id="ctxCopy">📋 Copier</div>
    </div>
    <script>
      const wrap = document.getElementById("wrap");
      const table = document.getElementById("selTable");
      const msg = document.getElementById("copyMsg");
      const ctxMenu = document.getElementById("ctxMenu");
      let isSelecting = false;
      let startCell = null;
      let autoScrollTimer = null;

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

      function stopAutoScroll() {{
        if (autoScrollTimer) {{ clearInterval(autoScrollTimer); autoScrollTimer = null; }}
      }}

      // Défilement automatique quand le curseur approche le haut/bas pendant la sélection
      function handleAutoScroll(clientY) {{
        stopAutoScroll();
        const rect = wrap.getBoundingClientRect();
        const margin = 30;
        if (clientY > rect.bottom - margin) {{
          autoScrollTimer = setInterval(() => {{ wrap.scrollTop += 15; }}, 30);
        }} else if (clientY < rect.top + margin) {{
          autoScrollTimer = setInterval(() => {{ wrap.scrollTop -= 15; }}, 30);
        }}
      }}

      table.addEventListener("mousedown", (e) => {{
        if (e.button !== 0) return;  // seulement le clic gauche démarre une sélection
        const td = e.target.closest("td");
        if (!td) return;
        isSelecting = true;
        startCell = td;
        selectRange(+td.dataset.r, +td.dataset.c, +td.dataset.r, +td.dataset.c);
        e.preventDefault();
      }});

      document.addEventListener("mousemove", (e) => {{
        if (!isSelecting) return;
        handleAutoScroll(e.clientY);
        const el = document.elementFromPoint(e.clientX, e.clientY);
        const td = el ? el.closest("td") : null;
        if (td) selectRange(+startCell.dataset.r, +startCell.dataset.c, +td.dataset.r, +td.dataset.c);
      }});

      document.addEventListener("mouseup", () => {{ isSelecting = false; stopAutoScroll(); }});

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

      async function copySelection() {{
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

      document.addEventListener("keydown", (e) => {{
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") copySelection();
      }});

      // Menu clic droit
      table.addEventListener("contextmenu", (e) => {{
        e.preventDefault();
        const td = e.target.closest("td");
        if (td && !td.classList.contains("selected")) {{
          selectRange(+td.dataset.r, +td.dataset.c, +td.dataset.r, +td.dataset.c);
        }}
        ctxMenu.style.left = e.clientX + "px";
        ctxMenu.style.top = e.clientY + "px";
        ctxMenu.style.display = "block";
      }});

      document.getElementById("ctxCopy").addEventListener("click", () => {{
        copySelection();
        ctxMenu.style.display = "none";
      }});

      document.addEventListener("click", (e) => {{
        if (!ctxMenu.contains(e.target)) ctxMenu.style.display = "none";
      }});
    </script>
    """
    components.html(page, height=height + 40, scrolling=True)


def construire_resultat_df():
    ref = st.session_state.reference_df
    valid_mask = ref["Nom et Prénom"].astype(str).str.strip() != ""
    valid_ref = ref[valid_mask].copy()
    matieres = st.session_state.matieres
    rows = []
    for idx in valid_ref.index:
        notes_etu = st.session_state.grades.get(str(idx), {})
        nom, prenom = split_nom_prenom(valid_ref.loc[idx, "Nom et Prénom"])
        row = {"Ordre": len(rows) + 1, "Nom": nom, "Prénom": prenom,
               "Matricule": valid_ref.loc[idx, "Matricule"]}
        notes_numeriques = []
        for mat in matieres:
            val = notes_etu.get(mat, None)
            row[mat] = val
            if val is not None:
                notes_numeriques.append(val)
        row["Moyenne"] = round(sum(notes_numeriques) / len(notes_numeriques), 2) if notes_numeriques else None
        rows.append(row)
    return pd.DataFrame(rows), matieres, valid_ref


def afficher_entete_contexte():
    """Affiche l'année d'études et la filière en en-tête, si renseignées."""
    if st.session_state.annee_etudes or st.session_state.filiere:
        morceaux = []
        if st.session_state.annee_etudes:
            morceaux.append(f"🗓️ **Année d'études :** {st.session_state.annee_etudes}")
        if st.session_state.filiere:
            morceaux.append(f"🎓 **Filière :** {st.session_state.filiere}")
        st.info(" &nbsp;|&nbsp; ".join(morceaux))


st.title("🧮 Calculatrice de Bulletins")
st.caption("Liste de référence → saisie désordonnée des notes → résultat toujours dans l'ordre officiel")

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 1. Liste de référence", "✍️ 2. Saisie des notes",
    "📊 3. Résultat final", "📑 4. Récapitulatif",
])

# ============================================================
# ONGLET 1 : LISTE DE RÉFÉRENCE
# ============================================================
with tab1:
    st.subheader("Liste de référence (ordre officiel de la scolarité)")

    col_a, col_b = st.columns(2)
    with col_a:
        nouvelle_annee = st.text_input("🗓️ Année d'études", value=st.session_state.annee_etudes,
                                        placeholder="Ex: 2025-2026", key="annee_input")
    with col_b:
        nouvelle_filiere = st.text_input("🎓 Filière", value=st.session_state.filiere,
                                          placeholder="Ex: Licence 2 Informatique", key="filiere_input")
    if nouvelle_annee != st.session_state.annee_etudes or nouvelle_filiere != st.session_state.filiere:
        st.session_state.annee_etudes = nouvelle_annee
        st.session_state.filiere = nouvelle_filiere
        persist_all()

    st.divider()

    nb_notes_existantes = sum(len(v) for v in st.session_state.grades.values())
    if st.button("🗑️ Effacer la liste de référence (garde les résultats)", type="secondary"):
        st.session_state.reference_df = pd.DataFrame(
            {"Nom et Prénom": [""] * MAX_ROWS, "Matricule": [""] * MAX_ROWS}
        )
        persist_all()
        st.success("Liste de référence effacée. Les notes déjà saisies sont conservées.")
        st.rerun()
    if nb_notes_existantes > 0:
        st.caption(
            "⚠️ Des notes existent déjà. Si vous collez une liste totalement différente (nouvelle année), "
            "pensez à aussi effacer les résultats dans l'onglet '📊 3. Résultat final', car les anciennes "
            "notes resteraient associées aux nouvelles positions de la liste."
        )

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

    with st.expander("📋 Vue sélectionnable (cliquez-glissez ou clic droit → Copier)"):
        vue_ref = st.session_state.reference_df[
            st.session_state.reference_df["Nom et Prénom"].astype(str).str.strip() != ""
        ].reset_index(drop=True)
        if vue_ref.empty:
            st.caption("Aucune donnée à afficher pour l'instant.")
        else:
            tableau_selectionnable(vue_ref, height=300)

    st.divider()
    st.write("**📚 Liste des matières** (collez-en plusieurs à la fois, une par ligne)")
    edited_matieres_df = st.data_editor(
        st.session_state.matieres_df,
        num_rows="fixed",
        use_container_width=True,
        height=220,
        key="matieres_editor",
    )
    if not edited_matieres_df.equals(st.session_state.matieres_df):
        st.session_state.matieres_df = edited_matieres_df
        nouvelles_matieres = [
            m.strip() for m in edited_matieres_df["Matière"].astype(str).tolist() if m.strip()
        ]
        # on garde l'ordre d'apparition, sans doublons
        vues = []
        for m in nouvelles_matieres:
            if m not in vues:
                vues.append(m)
        st.session_state.matieres = vues
        persist_all()
        st.rerun()

    with st.expander("📋 Vue sélectionnable des matières (cliquez-glissez ou clic droit → Copier)"):
        vue_mat = pd.DataFrame({"Matière": st.session_state.matieres})
        if vue_mat.empty:
            st.caption("Aucune matière à afficher pour l'instant.")
        else:
            tableau_selectionnable(vue_mat, height=220)

# ============================================================
# ONGLET 2 : SAISIE DES NOTES (recherche par nom, ordre libre)
# ============================================================
with tab2:
    st.subheader("Saisie des notes (dans n'importe quel ordre)")
    afficher_entete_contexte()

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

        # --- Choix de la matière : reste fixe tant qu'on ne la change pas volontairement ---
        NOUVELLE = "➕ Nouvelle matière..."
        if "matiere_courante" not in st.session_state:
            st.session_state.matiere_courante = st.session_state.matieres[-1] if st.session_state.matieres else ""

        choix_matiere = st.selectbox(
            "📚 Matière (tapez pour rechercher parmi les matières existantes, ou choisissez 'Nouvelle matière')",
            options=st.session_state.matieres + [NOUVELLE],
            index=(st.session_state.matieres.index(st.session_state.matiere_courante)
                   if st.session_state.matiere_courante in st.session_state.matieres else
                   (len(st.session_state.matieres) if st.session_state.matieres else 0)),
            key="matiere_select",
        )
        if choix_matiere == NOUVELLE:
            nouvelle_matiere = st.text_input("Nom de la nouvelle matière", key="nouvelle_matiere_input")
            matiere_active = nouvelle_matiere.strip()
        else:
            matiere_active = choix_matiere
            st.session_state.matiere_courante = choix_matiere

        st.caption(f"Matière active : **{matiere_active or '(aucune)'}** — elle restera sélectionnée pour les saisies suivantes.")

        # --- Formulaire : Entrée du clavier valide directement, puis se vide pour la saisie suivante ---
        with st.form("form_saisie_note", clear_on_submit=True):
            col1, col2 = st.columns([3, 1])
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

            submitted = st.form_submit_button("✅ Enregistrer (ou appuyez sur Entrée)", type="primary")
            if submitted:
                if chosen_idx is None or not matiere_active:
                    st.warning("Choisissez une matière et un étudiant avant de valider.")
                else:
                    idx_str = str(chosen_idx)
                    if idx_str not in st.session_state.grades:
                        st.session_state.grades[idx_str] = {}
                    st.session_state.grades[idx_str][matiere_active] = note_val
                    if matiere_active not in st.session_state.matieres:
                        st.session_state.matieres.append(matiere_active)
                        st.session_state.matiere_courante = matiere_active
                        # on garde aussi la table collable des matières synchronisée
                        colonne = st.session_state.matieres_df["Matière"].astype(str).tolist()
                        premiere_vide = next((i for i, v in enumerate(colonne) if not v.strip()), None)
                        if premiere_vide is not None:
                            st.session_state.matieres_df.loc[premiere_vide, "Matière"] = matiere_active
                        else:
                            st.session_state.matieres_df = pd.concat(
                                [st.session_state.matieres_df, pd.DataFrame({"Matière": [matiere_active]})],
                                ignore_index=True,
                            )
                    persist_all()
                    st.success(f"Note enregistrée pour {options[chosen_idx]} en {matiere_active}. "
                               f"Résultat final et récapitulatif mis à jour.")

# ============================================================
# ONGLET 3 : RÉSULTAT FINAL (toujours dans l'ordre de la liste)
# ============================================================
with tab3:
    st.subheader("Résultat final — dans l'ordre officiel de la liste")
    afficher_entete_contexte()

    resultat_df, matieres, valid_ref = construire_resultat_df()

    if valid_ref.empty:
        st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    else:
        col1, col2, col3 = st.columns([1, 1, 3])
        with col1:
            csv = resultat_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ CSV", csv, "resultat_final.csv", "text/csv")
        with col2:
            if st.button("🗑️ Effacer les notes", type="secondary"):
                st.session_state.grades = {}
                persist_all()
                st.success("Notes effacées. La liste de référence et les matières sont conservées.")
                st.rerun()

        nb_notes = sum(1 for idx in valid_ref.index if st.session_state.grades.get(str(idx)))
        st.caption(f"📝 {nb_notes} étudiant(s) avec au moins une note, sur {len(resultat_df)} au total "
                   f"— {len(matieres)} matière(s) : {', '.join(matieres) if matieres else 'aucune'}.")

        st.caption("💡 Cliquez-glissez (ou clic droit → Copier) pour copier une plage de cellules vers Excel.")
        tableau_selectionnable(resultat_df, height=460)

# ============================================================
# ONGLET 4 : RÉCAPITULATIF (étudiants en lignes, matières en colonnes)
# ============================================================
with tab4:
    st.subheader("Récapitulatif — étudiants en lignes, matières en colonnes")
    afficher_entete_contexte()

    resultat_df, matieres, valid_ref = construire_resultat_df()

    if valid_ref.empty:
        st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    elif not matieres:
        st.info("Aucune matière saisie pour l'instant. Ajoutez des notes dans l'onglet '✍️ 2. Saisie des notes'.")
    else:
        st.dataframe(resultat_df, use_container_width=True, hide_index=True, height=460)

        # En-tête Année/Filière inclus dans les fichiers exportés
        entete_lignes = []
        if st.session_state.annee_etudes:
            entete_lignes.append(f"Année d'études : {st.session_state.annee_etudes}")
        if st.session_state.filiere:
            entete_lignes.append(f"Filière : {st.session_state.filiere}")
        entete_texte = " | ".join(entete_lignes)

        col1, col2 = st.columns([1, 1])
        with col1:
            csv_contenu = (entete_texte + "\n" if entete_texte else "") + resultat_df.to_csv(index=False)
            st.download_button("⬇️ Télécharger en CSV", csv_contenu.encode("utf-8"),
                                "recapitulatif.csv", "text/csv", key="dl_recap_csv")
        with col2:
            from io import BytesIO
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                start_row = 0
                if entete_texte:
                    pd.DataFrame({entete_texte: []}).to_excel(writer, index=False, sheet_name="Récapitulatif", startrow=0)
                    start_row = 2
                resultat_df.to_excel(writer, index=False, sheet_name="Récapitulatif", startrow=start_row)
            st.download_button(
                "⬇️ Télécharger en Excel", buffer.getvalue(), "recapitulatif.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_recap_xlsx",
            )

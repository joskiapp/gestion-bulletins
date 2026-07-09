import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import os
import sys
import json
import html as html_lib
import difflib
import unicodedata
import re
import copy
from io import BytesIO

st.set_page_config(page_title="Calculatrice de Bulletins", page_icon="🧮", layout="wide")

MAX_ROWS = 500

# ---------- ARBRE ANNÉES / FILIÈRES ----------
CONTEXT_TREE = {
    "L1": ["TC"],
    "L2": ["AGRN", "ESR", "NSAA", "STPAH", "STPV"],
    "L3": ["AGRN", "ESR", "NSAA", "STPAH", "STPV"],
    "M1": ["ASCA", "AGEPA", "AGRN", "NSAA", "STPAH", "STPV", "GDSCC", "IVAV"],
    "M2": ["ASCA", "AGEPA", "FAUNE", "FORET", "IES", "AEA", "PA", "AGP", "PV", "NSAA", "GDSCC", "IVAV"],
}


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


# ---------- GESTION DU CONTEXTE (ANNÉE + FILIÈRE) ----------
def cle_contexte(annee_academique, annee, filiere):
    brut = f"{annee_academique}_{annee}_{filiere}"
    return re.sub(r"[^A-Za-z0-9_]", "_", brut)


def contexte_par_defaut():
    return {
        "reference_df": pd.DataFrame({"Nom et Prénom": [""] * MAX_ROWS, "Matricule": [""] * MAX_ROWS}),
        "matieres_df": pd.DataFrame({"Matière": [""] * 50}),
        "grades": {},
        "matieres": [],
        "matiere_courante": "",
        "collage_notes_df": pd.DataFrame({"Nom et Prénom": [""] * 500, "Note": [""] * 500}),
        "analyse_collage": None,
        "rattrapage": {},
        "snapshot_recap": None,
        "snapshot_decisions": None,
        "snapshot_rattrapage": None,
    }


def enregistrer_dans_registre(annee_academique, annee, filiere):
    """Garde trace de toutes les combinaisons (année académique, année, filière) déjà
    ouvertes, pour pouvoir les retrouver plus tard dans l'onglet Archives."""
    registre = load_state("registre_structure", {})
    registre.setdefault(annee_academique, {}).setdefault(annee, [])
    if filiere not in registre[annee_academique][annee]:
        registre[annee_academique][annee].append(filiere)
    save_state("registre_structure", registre)


def charger_contexte(cle):
    """Charge (depuis le disque si besoin) les données de la filière sélectionnée, une seule fois."""
    if "ctx_store" not in st.session_state:
        st.session_state.ctx_store = {}
    if cle not in st.session_state.ctx_store:
        ref = load_state(f"reference_df::{cle}", None)
        mat_df = load_state(f"matieres_df::{cle}", None)
        st.session_state.ctx_store[cle] = {
            "reference_df": pd.DataFrame(ref) if ref else contexte_par_defaut()["reference_df"],
            "matieres_df": pd.DataFrame(mat_df) if mat_df else contexte_par_defaut()["matieres_df"],
            "grades": load_state(f"grades::{cle}", {}),
            "matieres": load_state(f"matieres::{cle}", []),
            "matiere_courante": load_state(f"matiere_courante::{cle}", ""),
            "collage_notes_df": pd.DataFrame({"Nom et Prénom": [""] * 500, "Note": [""] * 500}),
            "analyse_collage": None,
            "rattrapage": load_state(f"rattrapage::{cle}", {}),
            "snapshot_recap": load_state(f"snapshot_recap::{cle}", None),
            "snapshot_decisions": load_state(f"snapshot_decisions::{cle}", None),
            "snapshot_rattrapage": load_state(f"snapshot_rattrapage::{cle}", None),
        }
    return st.session_state.ctx_store[cle]


def persist_contexte(cle, ctx):
    save_state(f"reference_df::{cle}", ctx["reference_df"].to_dict(orient="list"))
    save_state(f"matieres_df::{cle}", ctx["matieres_df"].to_dict(orient="list"))
    save_state(f"grades::{cle}", ctx["grades"])
    save_state(f"matieres::{cle}", ctx["matieres"])
    save_state(f"matiere_courante::{cle}", ctx["matiere_courante"])
    save_state(f"rattrapage::{cle}", ctx["rattrapage"])


# ---------- OUTILS DE CORRESPONDANCE DE NOMS ----------
def normaliser(texte):
    """Met en majuscule, retire les accents, trie les mots (insensible à l'ordre Nom/Prénom)."""
    texte = str(texte).strip().upper()
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    mots = sorted(texte.split())
    return " ".join(mots)


def trouver_meilleure_correspondance(nom_a_chercher, noms_reference, seuil=0.55):
    """Retourne (index dans noms_reference, score) du nom le plus proche, ou (None, score)."""
    cible = normaliser(nom_a_chercher)
    if not cible:
        return None, 0
    meilleur_idx, meilleur_score = None, 0
    for i, nom_ref in enumerate(noms_reference):
        score = difflib.SequenceMatcher(None, cible, normaliser(nom_ref)).ratio()
        if score > meilleur_score:
            meilleur_score, meilleur_idx = score, i
    return (meilleur_idx, meilleur_score) if meilleur_score >= seuil else (None, meilleur_score)


def sauvegarder_backup(ctx, label, **donnees):
    """Garde une copie de secours avant une action destructrice (suppression), pour pouvoir l'annuler."""
    ctx["backup"] = {"label": label, "donnees": copy.deepcopy(donnees)}


def bandeau_annuler(ctx, cle):
    """Affiche un bandeau permettant d'annuler la dernière suppression, si disponible."""
    if ctx.get("backup"):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.warning(f"🕓 Dernière action : **{ctx['backup']['label']}**. Vous pouvez encore l'annuler.")
        with col2:
            if st.button("↩️ Annuler", key=f"undo_{cle}", type="primary", use_container_width=True):
                for k, v in ctx["backup"]["donnees"].items():
                    ctx[k] = v
                ctx["backup"] = None
                persist_contexte(cle, ctx)
                st.success("Action annulée, les données précédentes ont été restaurées.")
                st.rerun()


def bouton_impression(titre, sous_titre, lignes_html, moyenne_html, cle_widget):
    """Bouton qui ouvre la boîte de dialogue d'impression du navigateur (choix d'imprimante)
    avec uniquement le contenu du bulletin, proprement mis en page. Utilise un iframe caché
    (plutôt qu'une fenêtre popup, souvent bloquée silencieusement par le navigateur)."""
    contenu = f"""
    <html><head><meta charset="utf-8"><title>{html_lib.escape(titre)}</title>
    <style>
      body {{ font-family: Arial, sans-serif; padding: 40px; color: #000; }}
      h1 {{ font-size: 22px; border-bottom: 2px solid #2E74B5; padding-bottom: 8px; }}
      .sous {{ color: #444; margin-bottom: 24px; }}
      table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
      th, td {{ border: 1px solid #999; padding: 8px 12px; text-align: left; }}
      th {{ background: #2E74B5; color: white; }}
      .moyenne {{ margin-top: 20px; font-size: 18px; font-weight: bold; }}
    </style></head>
    <body>
      <h1>🎓 {html_lib.escape(titre)}</h1>
      <div class="sous">{sous_titre}</div>
      <table><thead><tr><th>Matière</th><th>Note /20</th></tr></thead>
      <tbody>{lignes_html}</tbody></table>
      <div class="moyenne">{moyenne_html}</div>
    </body></html>
    """
    contenu_js = json.dumps(contenu)
    page = f"""
    <button id="btnPrint_{cle_widget}" style="background:#2E74B5;color:white;border:none;
      padding:10px 18px;border-radius:6px;cursor:pointer;font-size:14px;">
      🖨️ Imprimer ce bulletin
    </button>
    <iframe id="printFrame_{cle_widget}" style="display:none;"></iframe>
    <script>
      document.getElementById("btnPrint_{cle_widget}").addEventListener("click", function() {{
        const iframe = document.getElementById("printFrame_{cle_widget}");
        const doc = iframe.contentWindow.document;
        doc.open();
        doc.write({contenu_js});
        doc.close();
        setTimeout(function() {{
          iframe.contentWindow.focus();
          iframe.contentWindow.print();
        }}, 200);
      }});
    </script>
    """
    components.html(page, height=60)


def excel_bytes(df, sheet_name="Feuille1", entete_texte=None):
    """Construit un fichier Excel (bytes) à partir d'un DataFrame, avec une ligne
    d'en-tête optionnelle (ex: contexte année/filière) au-dessus du tableau."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        startrow = 0
        if entete_texte:
            pd.DataFrame({entete_texte: []}).to_excel(writer, index=False, sheet_name=sheet_name, startrow=0)
            startrow = 2
        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=startrow)
    return buffer.getvalue()


def enregistrer_definitivement(ctx, cle, nom_section, data_dict, libelle):
    """Bouton qui fige les données actuelles d'un onglet (récap, décisions, rattrapage...)
    de façon persistante : même si la liste de référence est ensuite effacée ou modifiée,
    ces données enregistrées restent consultables. Action irréversible (pas de bouton
    'annuler' après coup, volontairement)."""
    snap_key = f"snapshot_{nom_section}"
    if st.button(f"💾 Enregistrer {libelle} définitivement", key=f"save_def_{nom_section}_{cle}"):
        serialise = {}
        for k, v in data_dict.items():
            serialise[k] = v.to_dict(orient="list") if isinstance(v, pd.DataFrame) else v
        ctx[snap_key] = serialise
        save_state(f"{snap_key}::{cle}", serialise)
        st.success(f"{libelle} enregistré(e) définitivement. Ces données resteront disponibles ici "
                    f"même si la liste de référence est modifiée ou effacée par la suite.")
        st.rerun()
    if ctx.get(snap_key):
        st.caption("✅ Une version de ces données a déjà été enregistrée définitivement pour cette année/filière.")


def afficher_snapshot(snap_dict, cles_df):
    """Reconstruit les DataFrames sauvegardés à partir d'un snapshot pour affichage."""
    return {k: pd.DataFrame(v) for k, v in snap_dict.items() if k in cles_df}


def split_nom_prenom(nom_complet):
    """Sépare 'Nom et Prénom' collé en deux parties : premier mot = Nom, reste = Prénom."""
    parts = str(nom_complet).strip().split(" ", 1)
    nom = parts[0] if parts else ""
    prenom = parts[1] if len(parts) > 1 else ""
    return nom, prenom


# ---------- TABLEAU HTML SÉLECTIONNABLE (copier-coller façon Excel) ----------
def tableau_selectionnable(df, height=460, colonnes_figees=0, cle_widget="tbl", largeur_matieres=160):
    """Affiche un tableau HTML où l'on peut cliquer-glisser pour sélectionner une plage
    de cellules (comme Excel), avec défilement automatique en bordure, copie via Ctrl+C
    ou clic droit → Copier. Les `colonnes_figees` premières colonnes restent visibles
    lors du défilement horizontal (comme 'Figer les volets' dans Excel). Les colonnes
    suivantes (matières) gardent leur texte sur une seule ligne (pas de découpe lettre
    par lettre) ; on utilise le défilement horizontal si le tableau est large."""
    cols = list(df.columns)

    largeurs = [max(len(str(c)), *(len(str(v)) for v in df[c].astype(str))) * 8 + 24 if len(df) else 120
                for c in cols]
    # Les colonnes matières ont au moins la largeur de leur propre en-tête (texte lisible,
    # non tronqué), avec un plafond raisonnable pour éviter des colonnes démesurées.
    largeurs = [
        largeurs[c] if c < colonnes_figees
        else max(min(largeurs[c], largeur_matieres), len(str(cols[c])) * 8 + 24)
        for c in range(len(cols))
    ]
    offsets = [0]
    for w in largeurs[:-1]:
        offsets.append(offsets[-1] + w)

    def style_figee(c):
        if c < colonnes_figees:
            return (f'position: sticky; left: {offsets[c]}px; z-index: 3; '
                     f'min-width: {largeurs[c]}px; box-shadow: 2px 0 4px rgba(0,0,0,0.4); white-space: nowrap;')
        return f'white-space: nowrap; min-width: {largeurs[c]}px;'

    header_html = "".join(
        f'<th style="{style_figee(c)} {"z-index:4;" if c < colonnes_figees else ""}">{html_lib.escape(str(col))}</th>'
        for c, col in enumerate(cols)
    )
    body_html = ""
    for r, (_, row) in enumerate(df.iterrows()):
        cells = "".join(
            f'<td data-r="{r}" data-c="{c}" style="{style_figee(c)} '
            f'{"background:#151515;" if c < colonnes_figees else ""}">'
            f'{html_lib.escape("" if pd.isna(row[col]) else str(row[col]))}</td>'
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
      table.sel-table td.selected {{ background: #2E74B5 !important; color: white !important; }}
      .copy-msg {{ font-size: 12px; color: #70AD47; margin-top: 4px; height: 16px; }}
      .ctx-menu {{ position: fixed; display: none; background: #2b2b2b; border: 1px solid #555;
                   border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); z-index: 9999;
                   font-family: -apple-system, Segoe UI, Arial, sans-serif; font-size: 14px; overflow: hidden; }}
      .ctx-menu div {{ padding: 8px 16px; color: #eee; cursor: pointer; white-space: nowrap; }}
      .ctx-menu div:hover {{ background: #2E74B5; }}
    </style>
    <div class="sel-table-wrap" id="wrap_{cle_widget}">
      <table class="sel-table" id="selTable_{cle_widget}">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    <div class="copy-msg" id="copyMsg_{cle_widget}"></div>
    <div class="ctx-menu" id="ctxMenu_{cle_widget}">
      <div id="ctxCopy_{cle_widget}">📋 Copier</div>
    </div>
    <script>
      const wrap = document.getElementById("wrap_{cle_widget}");
      const table = document.getElementById("selTable_{cle_widget}");
      const msg = document.getElementById("copyMsg_{cle_widget}");
      const ctxMenu = document.getElementById("ctxMenu_{cle_widget}");
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
        if (e.button !== 0) return;
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

      document.getElementById("ctxCopy_{cle_widget}").addEventListener("click", () => {{
        copySelection();
        ctxMenu.style.display = "none";
      }});

      document.addEventListener("click", (e) => {{
        if (!ctxMenu.contains(e.target)) ctxMenu.style.display = "none";
      }});
    </script>
    """
    components.html(page, height=height + 40, scrolling=True)


def construire_resultat_df(ctx):
    ref = ctx["reference_df"]
    valid_mask = ref["Nom et Prénom"].astype(str).str.strip() != ""
    valid_ref = ref[valid_mask].copy()
    matieres = ctx["matieres"]
    rows = []
    for idx in valid_ref.index:
        notes_etu = ctx["grades"].get(str(idx), {})
        row = {"Ordre": len(rows) + 1, "Nom et Prénom": valid_ref.loc[idx, "Nom et Prénom"],
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


def notes_effectives_etudiant(ctx, idx):
    """Notes d'un étudiant après application des corrections de rattrapage,
    matière par matière (la note de rattrapage remplace la note initiale
    quand elle existe)."""
    idx_str = str(idx)
    notes = dict(ctx["grades"].get(idx_str, {}))
    notes.update(ctx["rattrapage"].get(idx_str, {}))
    return notes


def afficher_entete_contexte(annee_academique, annee, filiere):
    st.info(f"📅 **Année académique :** {annee_academique} &nbsp;|&nbsp; "
            f"🗓️ **Année :** {annee} &nbsp;|&nbsp; 🎓 **Filière :** {filiere}")



# ============================================================
# BARRE LATÉRALE : arbre Année → Filière
# ============================================================
if "selected_annee" not in st.session_state:
    st.session_state.selected_annee = load_state("selected_annee", None)
if "selected_filiere" not in st.session_state:
    st.session_state.selected_filiere = load_state("selected_filiere", None)
if "annee_academique_debut" not in st.session_state:
    st.session_state.annee_academique_debut = load_state("annee_academique_debut", 2025)

for annee in CONTEXT_TREE:
    annee_ouverte = (st.session_state.selected_annee == annee)
    if st.sidebar.button(
        ("📂 " if annee_ouverte else "📁 ") + annee,
        key=f"toggle_annee_{annee}", use_container_width=True,
    ):
        if annee_ouverte:
            st.session_state.selected_annee = None
            st.session_state.selected_filiere = None
        else:
            st.session_state.selected_annee = annee
            st.session_state.selected_filiere = None
        save_state("selected_annee", st.session_state.selected_annee)
        save_state("selected_filiere", st.session_state.selected_filiere)
        st.rerun()

    if annee_ouverte:
        for filiere in CONTEXT_TREE[annee]:
            est_actif = (st.session_state.selected_filiere == filiere)
            if st.sidebar.button(
                ("　　✅ " if est_actif else "　　　") + filiere,
                key=f"nav_{annee}_{filiere}", use_container_width=True,
            ):
                st.session_state.selected_filiere = filiere
                save_state("selected_filiere", filiere)
                st.rerun()

st.title("🧮 Calculatrice de Bulletins")

# La valeur est déjà connue via session_state (initialisée plus haut) ; le widget
# de saisie, lui, n'est affiché que dans l'onglet '1. Liste de référence'.
ANNEE_ACADEMIQUE = f"{int(st.session_state.annee_academique_debut)}-{int(st.session_state.annee_academique_debut) + 1}"

if not st.session_state.selected_annee or not st.session_state.selected_filiere:
    st.info("👈 Dans le menu à gauche : choisissez une année, puis une filière.")
    st.stop()

ANNEE = st.session_state.selected_annee
FILIERE = st.session_state.selected_filiere
CLE = cle_contexte(ANNEE_ACADEMIQUE, ANNEE, FILIERE)
ctx = charger_contexte(CLE)
enregistrer_dans_registre(ANNEE_ACADEMIQUE, ANNEE, FILIERE)

bandeau_annuler(ctx, CLE)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📋 1. Liste de référence", "✍️ 2. Saisie des notes",
    "📑 3. Récapitulatif", "⚖️ 4. Liste des décisions", "🔁 5. Rattrapage",
    "🎓 6. Bulletin", "🗄️ 7. Archives",
])

# ============================================================
# ONGLET 1 : LISTE DE RÉFÉRENCE
# ============================================================
with tab1:
    col_annee, _ = st.columns([1, 3])
    with col_annee:
        debut = st.number_input(
            "📅 Année de début (ex: 2026)",
            min_value=2000, max_value=2100, step=1,
            key="annee_academique_debut",
            help="Entrez uniquement l'année de début, sans tiret. "
                 "L'année de fin est calculée automatiquement.",
        )
    save_state("annee_academique_debut", int(debut))
    st.caption(f"➡️ Année académique : **{ANNEE_ACADEMIQUE}**")
    st.caption(f"📂 Espace de travail : **{ANNEE_ACADEMIQUE} · {ANNEE} — {FILIERE}** "
               f"(les données sont indépendantes pour chaque filière)")

    st.subheader(f"Liste de référence — {ANNEE} / {FILIERE}")

    nb_notes_existantes = sum(len(v) for v in ctx["grades"].values())
    if st.button("🗑️ Effacer la liste de référence (garde les résultats)", type="secondary", key=f"clear_ref_{CLE}"):
        sauvegarder_backup(ctx, "liste de référence effacée", reference_df=ctx["reference_df"])
        ctx["reference_df"] = pd.DataFrame({"Nom et Prénom": [""] * MAX_ROWS, "Matricule": [""] * MAX_ROWS})
        persist_contexte(CLE, ctx)
        st.success("Liste de référence effacée. Les notes déjà saisies sont conservées. "
                    "Vous pouvez l'annuler juste au-dessus si c'est une erreur.")
        st.rerun()
    if nb_notes_existantes > 0:
        st.caption(
            "⚠️ Des notes existent déjà. Si vous collez une liste totalement différente, "
            "pensez à aussi effacer les résultats dans l'onglet '📑 3. Récapitulatif', car les anciennes "
            "notes resteraient associées aux nouvelles positions de la liste."
        )

    nb_etudiants = (ctx["reference_df"]["Nom et Prénom"].astype(str).str.strip() != "").sum()
    st.caption(f"👥 {nb_etudiants} étudiant(s) actuellement reconnu(s) dans la liste.")

    st.info(
        "📌 Collez votre liste telle que fournie par la scolarité : une seule colonne "
        "'Nom et Prénom' (les deux ensemble, comme dans votre fichier), et le Matricule si disponible. "
        "Cliquez sur la première cellule ci-dessous, puis collez (Ctrl+V). "
        "**La reconnaissance est automatique**, dès que vous collez. "
        "Double-cliquez sur une cellule pour corriger une valeur ; cliquez-glissez pour sélectionner une plage."
    )

    edited_df = st.data_editor(
        ctx["reference_df"], num_rows="fixed", use_container_width=True,
        height=215, key=f"reference_editor_{CLE}",
    )
    if not edited_df.equals(ctx["reference_df"]):
        ctx["reference_df"] = edited_df
        persist_contexte(CLE, ctx)
        st.rerun()

    with st.expander("📋 Vue sélectionnable (cliquez-glissez ou clic droit → Copier) — colonne Nom figée"):
        vue_ref = ctx["reference_df"][
            ctx["reference_df"]["Nom et Prénom"].astype(str).str.strip() != ""
        ].reset_index(drop=True)
        if vue_ref.empty:
            st.caption("Aucune donnée à afficher pour l'instant.")
        else:
            tableau_selectionnable(vue_ref, height=300, colonnes_figees=1, cle_widget=f"ref_{CLE}")

    st.divider()
    st.write("**📚 Liste des matières** (collez-en plusieurs à la fois, une par ligne)")
    st.caption(
        "ℹ️ La composition des matières peut changer d'une évaluation à l'autre. "
        "Assurez-vous d'abord que la **liste des étudiants** ci-dessus est bien complète et dans le bon ordre, "
        "puis effacez la liste des matières ici pour la remplacer par une nouvelle."
    )

    nb_notes_liees = sum(len(v) for v in ctx["grades"].values())
    if st.button("🗑️ Effacer la liste des matières", type="secondary", key=f"clear_mat_{CLE}"):
        sauvegarder_backup(ctx, "liste des matières et notes effacées",
                            matieres_df=ctx["matieres_df"], matieres=ctx["matieres"], grades=ctx["grades"])
        ctx["matieres_df"] = pd.DataFrame({"Matière": [""] * 50})
        ctx["matieres"] = []
        ctx["matiere_courante"] = ""
        ctx["grades"] = {}  # les notes étaient liées aux anciennes matières, elles n'ont plus de sens
        persist_contexte(CLE, ctx)
        st.success("Liste des matières (et notes associées) effacée. La liste des étudiants est conservée. "
                   "Vous pouvez l'annuler juste en haut de page si c'est une erreur.")
        st.rerun()
    if nb_notes_liees > 0:
        st.caption(f"⚠️ {nb_notes_liees} note(s) actuellement liée(s) aux matières existantes — "
                   "elles seront effacées en même temps que la liste des matières.")

    edited_matieres_df = st.data_editor(
        ctx["matieres_df"], num_rows="fixed", use_container_width=True,
        height=215, key=f"matieres_editor_{CLE}",
    )
    if not edited_matieres_df.equals(ctx["matieres_df"]):
        ctx["matieres_df"] = edited_matieres_df
        nouvelles_matieres = [m.strip() for m in edited_matieres_df["Matière"].astype(str).tolist() if m.strip()]
        vues = []
        for m in nouvelles_matieres:
            if m not in vues:
                vues.append(m)
        ctx["matieres"] = vues
        persist_contexte(CLE, ctx)
        st.rerun()

    with st.expander("📋 Vue sélectionnable des matières (cliquez-glissez ou clic droit → Copier)"):
        vue_mat = pd.DataFrame({"Matière": ctx["matieres"]})
        if vue_mat.empty:
            st.caption("Aucune matière à afficher pour l'instant.")
        else:
            tableau_selectionnable(vue_mat, height=220, cle_widget=f"mat_{CLE}")

# ============================================================
# ONGLET 2 : SAISIE DES NOTES
# ============================================================
with tab2:
    st.subheader("Saisie des notes (dans n'importe quel ordre)")

    ref = ctx["reference_df"]
    valid_mask = ref["Nom et Prénom"].astype(str).str.strip() != ""
    valid_indices = ref.index[valid_mask].tolist()

    if not valid_indices:
        st.warning("Aucune liste de référence trouvée. Allez d'abord dans l'onglet '📋 1. Liste de référence'.")
    else:
        mode = st.radio(
            "Comment voulez-vous saisir les notes ?",
            ["✍️ Saisie pêle-mêle (une note à la fois)", "📊 Saisie en grille (navigation aux flèches)",
             "📋 Collage de notes déjà préparées (Excel)"],
            horizontal=True, key=f"mode_saisie_{CLE}",
        )
        st.divider()

        options = {
            idx: f"{ref.loc[idx, 'Nom et Prénom']}"
            + (f" — {ref.loc[idx, 'Matricule']}" if str(ref.loc[idx, "Matricule"]).strip() else "")
            for idx in valid_indices
        }

        NOUVELLE = "➕ Nouvelle matière..."
        if not ctx["matiere_courante"] and ctx["matieres"]:
            ctx["matiere_courante"] = ctx["matieres"][-1]

        def enregistrer_matiere_si_nouvelle(matiere):
            if matiere not in ctx["matieres"]:
                ctx["matieres"].append(matiere)
                ctx["matiere_courante"] = matiere
                colonne = ctx["matieres_df"]["Matière"].astype(str).tolist()
                premiere_vide = next((i for i, v in enumerate(colonne) if not v.strip()), None)
                if premiere_vide is not None:
                    ctx["matieres_df"].loc[premiere_vide, "Matière"] = matiere
                else:
                    ctx["matieres_df"] = pd.concat(
                        [ctx["matieres_df"], pd.DataFrame({"Matière": [matiere]})], ignore_index=True,
                    )

        if not mode.startswith("📊"):
            choix_matiere = st.selectbox(
                "📚 Matière (tapez pour rechercher parmi les matières existantes, ou choisissez 'Nouvelle matière')",
                options=ctx["matieres"] + [NOUVELLE],
                index=(ctx["matieres"].index(ctx["matiere_courante"])
                       if ctx["matiere_courante"] in ctx["matieres"] else
                       (len(ctx["matieres"]) if ctx["matieres"] else 0)),
                key=f"matiere_select_{CLE}",
            )
            if choix_matiere == NOUVELLE:
                nouvelle_matiere = st.text_input("Nom de la nouvelle matière", key=f"nouvelle_matiere_input_{CLE}")
                matiere_active = nouvelle_matiere.strip()
            else:
                matiere_active = choix_matiere
                ctx["matiere_courante"] = choix_matiere

            st.caption(f"Matière active : **{matiere_active or '(aucune)'}** — elle restera sélectionnée pour les saisies suivantes.")

        if mode.startswith("✍️"):
            with st.form(f"form_saisie_note_{CLE}", clear_on_submit=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    chosen_idx = st.selectbox(
                        "🔍 Tapez 2-3 lettres du nom ou prénom pour le retrouver",
                        options=list(options.keys()), format_func=lambda i: options[i],
                        index=None, placeholder="Rechercher un étudiant...", key=f"search_student_{CLE}",
                    )
                with col2:
                    note_str = st.text_input("Note /20", value="", placeholder="Ex: 14.5", key=f"note_input_{CLE}")

                submitted = st.form_submit_button("✅ Enregistrer (ou appuyez sur Entrée)", type="primary")
                if submitted:
                    note_str_clean = note_str.strip().replace(",", ".")
                    try:
                        note_val = float(note_str_clean) if note_str_clean else None
                    except ValueError:
                        note_val = None

                    if chosen_idx is None or not matiere_active:
                        st.warning("Choisissez une matière et un étudiant avant de valider.")
                    elif note_val is None:
                        st.warning("Note invalide : saisissez un nombre (ex: 14 ou 14.5).")
                    elif not (0 <= note_val <= 20):
                        st.warning("La note doit être comprise entre 0 et 20.")
                    else:
                        idx_str = str(chosen_idx)
                        deja_saisie = ctx["grades"].get(idx_str, {}).get(matiere_active)
                        if deja_saisie is not None:
                            st.session_state[f"pending_note_{CLE}"] = {
                                "idx": chosen_idx, "matiere": matiere_active,
                                "note": note_val, "ancienne": deja_saisie,
                            }
                        else:
                            ctx["grades"].setdefault(idx_str, {})[matiere_active] = note_val
                            enregistrer_matiere_si_nouvelle(matiere_active)
                            persist_contexte(CLE, ctx)
                            st.success(f"Note enregistrée pour {options[chosen_idx]} en {matiere_active}. "
                                       f"Récapitulatif et bulletin mis à jour.")
                            st.rerun()

            pending = st.session_state.get(f"pending_note_{CLE}")
            if pending:
                st.warning(
                    f"⚠️ La note de **{pending['matiere']}** pour **{options[pending['idx']]}** a déjà été "
                    f"saisie ({pending['ancienne']}/20). Voulez-vous la remplacer par {pending['note']}/20 ?"
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Oui, modifier", key=f"confirm_oui_saisie_{CLE}"):
                        idx_str = str(pending["idx"])
                        ctx["grades"].setdefault(idx_str, {})[pending["matiere"]] = pending["note"]
                        enregistrer_matiere_si_nouvelle(pending["matiere"])
                        persist_contexte(CLE, ctx)
                        st.session_state.pop(f"pending_note_{CLE}", None)
                        st.success("Note modifiée. Récapitulatif et bulletin mis à jour.")
                        st.rerun()
                with c2:
                    if st.button("❌ Non, annuler", key=f"confirm_non_saisie_{CLE}"):
                        st.session_state.pop(f"pending_note_{CLE}", None)
                        st.rerun()

        elif mode.startswith("📊"):
            if not ctx["matieres"]:
                st.info("Aucune matière créée pour l'instant. Ajoutez-en une via le mode "
                         "'✍️ Saisie pêle-mêle' (option 'Nouvelle matière'), puis revenez ici.")
            else:
                st.caption(
                    "💡 Tableau modifiable façon Excel : cliquez dans une cellule et utilisez les flèches "
                    "du clavier pour naviguer entre étudiants et matières. Chaque case modifiée est "
                    "enregistrée automatiquement."
                )

                grille_saisie = pd.DataFrame({"Nom et Prénom": [options[idx] for idx in valid_indices]})
                for mat in ctx["matieres"]:
                    grille_saisie[mat] = [
                        ctx["grades"].get(str(idx), {}).get(mat, None) for idx in valid_indices
                    ]

                grille_editee = st.data_editor(
                    grille_saisie, num_rows="fixed", use_container_width=True, height=460,
                    disabled=["Nom et Prénom"],
                    column_config={
                        mat: st.column_config.NumberColumn(mat, min_value=0, max_value=20, step=0.25)
                        for mat in ctx["matieres"]
                    },
                    key=f"grille_saisie_editor_{CLE}",
                )

                if not grille_editee.equals(grille_saisie):
                    for pos, idx in enumerate(valid_indices):
                        idx_str = str(idx)
                        for mat in ctx["matieres"]:
                            val = grille_editee.iloc[pos][mat]
                            if pd.notna(val):
                                ctx["grades"].setdefault(idx_str, {})[mat] = float(val)
                            elif mat in ctx["grades"].get(idx_str, {}):
                                del ctx["grades"][idx_str][mat]
                    persist_contexte(CLE, ctx)
                    st.rerun()

        else:
            st.info(
                "📌 Collez ici la liste déjà préparée par l'enseignant (Nom et Prénom dans une colonne, "
                "Note dans l'autre — peu importe l'ordre). L'application recherche automatiquement "
                "le nom le plus proche dans la liste de référence et classe le résultat dans l'ordre officiel."
            )

            edited_collage = st.data_editor(
                ctx["collage_notes_df"], num_rows="fixed", use_container_width=True,
                height=420, key=f"collage_editor_{CLE}",
            )
            if not edited_collage.equals(ctx["collage_notes_df"]):
                ctx["collage_notes_df"] = edited_collage
                st.rerun()

            col_a, col_b = st.columns([1, 3])
            with col_a:
                if st.button("🗑️ Vider le tableau collé", type="secondary", key=f"clear_collage_{CLE}"):
                    sauvegarder_backup(ctx, "tableau collé vidé", collage_notes_df=ctx["collage_notes_df"])
                    ctx["collage_notes_df"] = pd.DataFrame({"Nom et Prénom": [""] * 500, "Note": [""] * 500})
                    ctx["analyse_collage"] = None
                    persist_contexte(CLE, ctx)
                    st.success("Tableau collé vidé. Vous pouvez l'annuler en haut de page si c'est une erreur.")
                    st.rerun()

            if st.button("🔎 Analyser et associer les noms", type="primary", disabled=not matiere_active,
                         key=f"analyser_{CLE}"):
                noms_ref_valides = [options[idx].split(" — ")[0] for idx in valid_indices]
                resultats_analyse = []
                for _, row in ctx["collage_notes_df"].iterrows():
                    nom_saisi = str(row["Nom et Prénom"]).strip()
                    note_brute = str(row["Note"]).strip().replace(",", ".")
                    if not nom_saisi:
                        continue
                    pos, score = trouver_meilleure_correspondance(nom_saisi, noms_ref_valides)
                    try:
                        note_val = float(note_brute) if note_brute else None
                    except ValueError:
                        note_val = None
                    idx_ref = valid_indices[pos] if pos is not None else None
                    resultats_analyse.append({
                        "Nom collé": nom_saisi,
                        "Correspondance trouvée": options[idx_ref].split(" — ")[0] if idx_ref is not None else "❌ Aucune",
                        "Confiance": f"{score*100:.0f}%",
                        "Note": note_val if note_val is not None else "⚠️ invalide",
                        "_idx_ref": idx_ref,
                        "_note_val": note_val,
                    })
                ctx["analyse_collage"] = resultats_analyse

            if ctx.get("analyse_collage"):
                analyse = ctx["analyse_collage"]
                apercu = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in analyse])
                st.write("**Aperçu de l'association (vérifiez avant de valider) :**")
                st.dataframe(apercu, use_container_width=True, hide_index=True)

                nb_ok = sum(1 for r in analyse if r["_idx_ref"] is not None and r["_note_val"] is not None)
                nb_pb = len(analyse) - nb_ok
                st.caption(f"✅ {nb_ok} ligne(s) prête(s) à être enregistrée(s) — ⚠️ {nb_pb} problème(s) à corriger si non nul.")

                if st.button("✅ Valider et enregistrer ces notes", type="primary", key=f"valider_collage_{CLE}"):
                    sauvegarder_backup(ctx, f"lot de notes collées en {matiere_active}", grades=ctx["grades"])
                    for r in analyse:
                        if r["_idx_ref"] is not None and r["_note_val"] is not None:
                            idx_str = str(r["_idx_ref"])
                            if idx_str not in ctx["grades"]:
                                ctx["grades"][idx_str] = {}
                            ctx["grades"][idx_str][matiere_active] = r["_note_val"]
                    enregistrer_matiere_si_nouvelle(matiere_active)
                    ctx["analyse_collage"] = None
                    ctx["collage_notes_df"] = pd.DataFrame({"Nom et Prénom": [""] * 500, "Note": [""] * 500})
                    persist_contexte(CLE, ctx)
                    st.success(f"{nb_ok} note(s) enregistrée(s) en {matiere_active}. Récapitulatif mis à jour. "
                               f"Vous pouvez annuler ce lot en haut de page si besoin.")
                    st.rerun()

# ============================================================
# ONGLET 3 : RÉCAPITULATIF
# ============================================================
with tab3:
    st.subheader("Récapitulatif — étudiants en lignes, matières en colonnes")

    resultat_df, matieres, valid_ref = construire_resultat_df(ctx)

    if valid_ref.empty:
        if ctx.get("snapshot_recap"):
            st.info("🔒 La liste de référence est vide, mais un récapitulatif avait été enregistré "
                    "définitivement pour cette année/filière. Le voici :")
            snap = afficher_snapshot(ctx["snapshot_recap"], ["resultat"])
            tableau_selectionnable(snap["resultat"], height=460, colonnes_figees=3, cle_widget=f"recap_snap_{CLE}")
            st.download_button("⬇️ Télécharger en CSV", snap["resultat"].to_csv(index=False).encode("utf-8"),
                                f"recapitulatif_{ANNEE}_{FILIERE}_enregistre.csv", "text/csv",
                                key=f"dl_recap_snap_{CLE}")
        else:
            st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    else:
        col1, col2, col3 = st.columns([1, 1, 3])
        with col1:
            csv_dl = resultat_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ CSV", csv_dl, f"recapitulatif_{ANNEE}_{FILIERE}.csv", "text/csv",
                                key=f"dl_recap_csv_top_{CLE}")
        with col2:
            if st.button("🗑️ Effacer les notes", type="secondary", key=f"clear_notes_{CLE}"):
                sauvegarder_backup(ctx, "notes effacées", grades=ctx["grades"])
                ctx["grades"] = {}
                persist_contexte(CLE, ctx)
                st.success("Notes effacées. La liste de référence et les matières sont conservées. "
                           "Vous pouvez l'annuler en haut de page si c'est une erreur.")
                st.rerun()

        nb_notes = sum(1 for idx in valid_ref.index if ctx["grades"].get(str(idx)))
        st.caption(f"📝 {nb_notes} étudiant(s) avec au moins une note, sur {len(resultat_df)} au total "
                   f"— {len(matieres)} matière(s) : {', '.join(matieres) if matieres else 'aucune'}.")

        if not matieres:
            st.info("Aucune matière saisie pour l'instant. Ajoutez des notes dans l'onglet '✍️ 2. Saisie des notes'.")
        else:
            st.caption("💡 Cliquez-glissez (ou clic droit → Copier) pour copier une plage de cellules vers Excel. "
                       "Les colonnes Ordre/Nom/Prénom/Matricule restent figées lors du défilement horizontal.")
            tableau_selectionnable(resultat_df, height=460, colonnes_figees=3, cle_widget=f"recap_{CLE}")

            entete_texte = f"Année : {ANNEE} | Filière : {FILIERE}"

            colx, coly, colz = st.columns([1, 1, 1])
            with colx:
                csv_contenu = entete_texte + "\n" + resultat_df.to_csv(index=False)
                st.download_button("⬇️ Télécharger en CSV", csv_contenu.encode("utf-8"),
                                    f"recapitulatif_{ANNEE}_{FILIERE}.csv", "text/csv", key=f"dl_recap_csv_{CLE}")
            with coly:
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    pd.DataFrame({entete_texte: []}).to_excel(writer, index=False, sheet_name="Récapitulatif", startrow=0)
                    resultat_df.to_excel(writer, index=False, sheet_name="Récapitulatif", startrow=2)
                st.download_button(
                    "⬇️ Télécharger en Excel", buffer.getvalue(), f"recapitulatif_{ANNEE}_{FILIERE}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_recap_xlsx_{CLE}",
                )
            with colz:
                enregistrer_definitivement(ctx, CLE, "recap", {"resultat": resultat_df}, "le récapitulatif")

# ============================================================
# ONGLET 4 : LISTE DES DÉCISIONS
# ============================================================
with tab4:
    st.subheader("Liste des décisions — validation des matières")

    resultat_df, matieres, valid_ref = construire_resultat_df(ctx)

    if valid_ref.empty:
        if ctx.get("snapshot_decisions"):
            st.info("🔒 La liste de référence est vide, mais une liste des décisions avait été enregistrée "
                    "définitivement pour cette année/filière. La voici :")
            snap = afficher_snapshot(ctx["snapshot_decisions"], ["valides", "non_valides", "grille"])
            st.markdown("### ✅ Étudiants ayant validé toutes les matières")
            tableau_selectionnable(snap["valides"], height=320, colonnes_figees=2, cle_widget=f"valides_snap_{CLE}")
            st.markdown("### ⚠️ Étudiants n'ayant pas validé au moins une matière")
            tableau_selectionnable(snap["non_valides"], height=320, colonnes_figees=2, cle_widget=f"nonvalides_snap_{CLE}")
            st.markdown("### 🧭 Grille de validation par matière")
            tableau_selectionnable(snap["grille"], height=360, colonnes_figees=2, cle_widget=f"grille_snap_{CLE}")
        else:
            st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    elif not matieres:
        st.info("Aucune matière saisie pour l'instant. Ajoutez des notes dans l'onglet '✍️ 2. Saisie des notes'.")
    else:
        st.caption("Seuil de validation : note ≥ 12/20 dans **chaque** matière.")

        def a_valide_tout(row):
            for mat in matieres:
                val = row[mat]
                if pd.isna(val) or val < 12:
                    return False
            return True

        resultat_df["Statut"] = resultat_df.apply(a_valide_tout, axis=1)
        colonnes_affichage = ["Nom et Prénom"] + matieres

        valides_df = resultat_df[resultat_df["Statut"]][colonnes_affichage].reset_index(drop=True)
        valides_df.insert(0, "Ordre", range(1, len(valides_df) + 1))

        non_valides_df = resultat_df[~resultat_df["Statut"]][colonnes_affichage].reset_index(drop=True)
        non_valides_df.insert(0, "Ordre", range(1, len(non_valides_df) + 1))

        st.markdown(f"### ✅ Étudiants ayant validé toutes les matières ({len(valides_df)})")
        if valides_df.empty:
            st.caption("Aucun étudiant n'a encore validé toutes les matières.")
        else:
            tableau_selectionnable(valides_df, height=320, colonnes_figees=2, cle_widget=f"valides_{CLE}")

        st.divider()
        st.markdown(f"### ⚠️ Étudiants n'ayant pas validé au moins une matière ({len(non_valides_df)})")
        st.caption("Toutes les matières sont affichées (validées et non validées) pour situer chaque étudiant. "
                    "**C'est cette liste qui alimente l'onglet '🔁 5. Rattrapage'.**")
        if non_valides_df.empty:
            st.caption("Aucun étudiant dans cette situation.")
        else:
            tableau_selectionnable(non_valides_df, height=320, colonnes_figees=2, cle_widget=f"nonvalides_{CLE}")

        entete_decisions = f"Liste des décisions — Année académique : {ANNEE_ACADEMIQUE} | {ANNEE} — {FILIERE}"

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.download_button("⬇️ Validés (CSV)", valides_df.to_csv(index=False).encode("utf-8"),
                                f"valides_{ANNEE}_{FILIERE}.csv", "text/csv", key=f"dl_valides_{CLE}")
        with col2:
            st.download_button("⬇️ Validés (Excel)",
                                excel_bytes(valides_df, "Validés", entete_decisions),
                                f"valides_{ANNEE}_{FILIERE}.xlsx",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"dl_valides_xlsx_{CLE}")
        with col3:
            st.download_button("⬇️ Non validés (CSV)", non_valides_df.to_csv(index=False).encode("utf-8"),
                                f"non_valides_{ANNEE}_{FILIERE}.csv", "text/csv", key=f"dl_nonvalides_{CLE}")
        with col4:
            st.download_button("⬇️ Non validés (Excel)",
                                excel_bytes(non_valides_df, "Non validés", entete_decisions),
                                f"non_valides_{ANNEE}_{FILIERE}.xlsx",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"dl_nonvalides_xlsx_{CLE}")

        st.divider()
        st.markdown("### 🧭 Grille de validation par matière")
        st.caption("Case vide = matière validée (≥ 12/20). Croix rouge ❌ = matière non validée, à rattraper.")

        grille_df = resultat_df[["Nom et Prénom"] + matieres].reset_index(drop=True).copy()
        for mat in matieres:
            grille_df[mat] = resultat_df[mat].apply(
                lambda v: "❌" if (pd.isna(v) or v < 12) else ""
            )
        grille_df.insert(0, "Ordre", range(1, len(grille_df) + 1))
        tableau_selectionnable(grille_df, height=360, colonnes_figees=2, cle_widget=f"grille_{CLE}")

        col5, col6, col7 = st.columns(3)
        with col5:
            st.download_button("⬇️ Grille (CSV)", grille_df.to_csv(index=False).encode("utf-8"),
                                f"grille_validation_{ANNEE}_{FILIERE}.csv", "text/csv", key=f"dl_grille_{CLE}")
        with col6:
            st.download_button("⬇️ Grille (Excel)",
                                excel_bytes(grille_df, "Grille", entete_decisions),
                                f"grille_validation_{ANNEE}_{FILIERE}.xlsx",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"dl_grille_xlsx_{CLE}")
        with col7:
            enregistrer_definitivement(
                ctx, CLE, "decisions",
                {"valides": valides_df, "non_valides": non_valides_df, "grille": grille_df},
                "la liste des décisions",
            )

# ============================================================
# ONGLET 5 : RATTRAPAGE
# ============================================================
with tab5:
    st.subheader("Rattrapage — étudiants n'ayant pas validé au moins une matière")

    resultat_df, matieres, valid_ref = construire_resultat_df(ctx)

    if valid_ref.empty:
        if ctx.get("snapshot_rattrapage"):
            st.info("🔒 La liste de référence est vide, mais un suivi de rattrapage avait été enregistré "
                    "définitivement pour cette année/filière. Le voici :")
            snap = afficher_snapshot(ctx["snapshot_rattrapage"], ["suivi"])
            tableau_selectionnable(snap["suivi"], height=360, colonnes_figees=2, cle_widget=f"suivi_snap_{CLE}")
        else:
            st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    elif not matieres:
        st.info("Aucune matière saisie pour l'instant. Ajoutez des notes dans l'onglet '✍️ 2. Saisie des notes'.")
    else:
        st.caption(
            "La liste ci-dessous reprend les étudiants du tableau **'⚠️ Étudiants n'ayant pas validé au "
            "moins une matière'** (onglet Liste des décisions) — il ne s'agit pas de la moyenne générale, "
            "mais bien de la validation matière par matière (< 12/20)."
        )

        resultat_rattr = resultat_df.copy()
        resultat_rattr["_idx_ref"] = valid_ref.index.tolist()

        # Construit, pour chaque étudiant, la liste des matières où il est en dessous de 12.
        matieres_a_rattraper_par_etudiant = {}
        for _, row in resultat_rattr.iterrows():
            manquantes = [mat for mat in matieres if pd.isna(row[mat]) or row[mat] < 12]
            if manquantes:
                matieres_a_rattraper_par_etudiant[row["_idx_ref"]] = {
                    "Ordre": row["Ordre"], "Nom et Prénom": row["Nom et Prénom"], "matieres": manquantes,
                }

        if not matieres_a_rattraper_par_etudiant:
            st.success("🎉 Tous les étudiants ont validé toutes leurs matières : personne n'est concerné par le rattrapage.")
        else:
            st.caption(f"👥 {len(matieres_a_rattraper_par_etudiant)} étudiant(s) concerné(s) par le rattrapage "
                       f"— la liste reste complète même après saisie d'une note.")

            options_rattrapage = {}
            for idx_ref, info in matieres_a_rattraper_par_etudiant.items():
                matricule = valid_ref.loc[idx_ref, "Matricule"]
                label = info["Nom et Prénom"]
                if str(matricule).strip():
                    label += f" — {matricule}"
                options_rattrapage[idx_ref] = label

            col_nom, col_mat = st.columns([2, 1])
            with col_nom:
                idx_choisi = st.selectbox(
                    "🔍 Tapez 2-3 lettres du nom de l'étudiant en rattrapage",
                    options=list(options_rattrapage.keys()), format_func=lambda i: options_rattrapage[i],
                    index=None, placeholder="Rechercher un étudiant...", key=f"search_rattrapage_{CLE}",
                )
            with col_mat:
                if idx_choisi is not None:
                    matieres_dispo = matieres_a_rattraper_par_etudiant[idx_choisi]["matieres"]
                    matiere_choisie = st.selectbox(
                        "📚 Matière à rattraper", options=matieres_dispo,
                        index=None, placeholder="Choisir la matière...",
                        key=f"search_matiere_rattrapage_{CLE}_{idx_choisi}",
                    )
                else:
                    matiere_choisie = None

            if idx_choisi is not None and matiere_choisie is not None:
                idx_str = str(idx_choisi)
                cle_pair = f"{idx_str}::{matiere_choisie}"
                note_deja_saisie = ctx["rattrapage"].get(idx_str, {}).get(matiere_choisie)
                confirm_key = f"rattr_confirme_{CLE}_{cle_pair}"

                if note_deja_saisie is not None and not st.session_state.get(confirm_key, False):
                    st.warning(
                        f"⚠️ La note de **{matiere_choisie}** pour **{options_rattrapage[idx_choisi]}** "
                        f"a déjà été saisie en rattrapage ({note_deja_saisie}/20). Voulez-vous la modifier ?"
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Oui, modifier", key=f"rattr_oui_{CLE}_{cle_pair}"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                    with c2:
                        if st.button("❌ Non", key=f"rattr_non_{CLE}_{cle_pair}"):
                            st.stop()
                else:
                    note_initiale = ctx["grades"].get(idx_str, {}).get(matiere_choisie)
                    col_a, col_b = st.columns([1, 1])
                    with col_a:
                        st.metric(f"📊 Note initiale en {matiere_choisie}",
                                   f"{note_initiale}/20" if note_initiale is not None else "—")
                    with col_b:
                        nouvelle_note = st.number_input(
                            "✍️ Nouvelle note de rattrapage", min_value=0.0, max_value=20.0, step=0.25,
                            value=float(note_deja_saisie) if note_deja_saisie is not None else 0.0,
                            key=f"rattr_input_{CLE}_{cle_pair}",
                        )
                    if st.button("💾 Enregistrer cette note de rattrapage", type="primary",
                                 key=f"rattr_save_{CLE}_{cle_pair}"):
                        ctx["rattrapage"].setdefault(idx_str, {})[matiere_choisie] = nouvelle_note
                        persist_contexte(CLE, ctx)
                        st.session_state.pop(confirm_key, None)
                        st.success(
                            f"Note de rattrapage enregistrée pour {options_rattrapage[idx_choisi]} en "
                            f"{matiere_choisie}. Moyenne générale et bulletin recalculés."
                        )
                        st.rerun()

            st.divider()
            st.write("**📋 Suivi des rattrapages** (dans le même ordre que le classement initial)")

            lignes_suivi = []
            for idx_ref, info in sorted(matieres_a_rattraper_par_etudiant.items(), key=lambda kv: kv[1]["Ordre"]):
                idx_str = str(idx_ref)
                notes_orig = ctx["grades"].get(idx_str, {})
                moyenne_avant = (round(sum(notes_orig.get(m, 0) for m in matieres if m in notes_orig)
                                        / max(1, len([m for m in matieres if m in notes_orig])), 2)
                                  if notes_orig else None)
                notes_apres = notes_effectives_etudiant(ctx, idx_ref)
                vals_apres = [notes_apres[m] for m in matieres if m in notes_apres]
                moyenne_apres = round(sum(vals_apres) / len(vals_apres), 2) if vals_apres else None

                rattrapes = ctx["rattrapage"].get(idx_str, {})
                matieres_traitees = ", ".join(
                    f"{m} ({rattrapes[m]}/20)" for m in info["matieres"] if m in rattrapes
                ) or "—"

                lignes_suivi.append({
                    "Ordre": info["Ordre"],
                    "Nom et Prénom": info["Nom et Prénom"],
                    "Matière(s) à rattraper": ", ".join(info["matieres"]),
                    "Note(s) de rattrapage saisie(s)": matieres_traitees,
                    "Moyenne avant": moyenne_avant,
                    "Moyenne après rattrapage": moyenne_apres,
                })
            suivi_df = pd.DataFrame(lignes_suivi)
            tableau_selectionnable(suivi_df, height=360, colonnes_figees=2, cle_widget=f"suivi_rattrapage_{CLE}")

            entete_rattr = f"Rattrapage — Année académique : {ANNEE_ACADEMIQUE} | {ANNEE} — {FILIERE}"
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button("⬇️ Suivi rattrapage (CSV)", suivi_df.to_csv(index=False).encode("utf-8"),
                                    f"rattrapage_{ANNEE}_{FILIERE}.csv", "text/csv", key=f"dl_rattrapage_{CLE}")
            with col2:
                st.download_button("⬇️ Suivi rattrapage (Excel)",
                                    excel_bytes(suivi_df, "Rattrapage", entete_rattr),
                                    f"rattrapage_{ANNEE}_{FILIERE}.xlsx",
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"dl_rattrapage_xlsx_{CLE}")
            with col3:
                enregistrer_definitivement(ctx, CLE, "rattrapage", {"suivi": suivi_df}, "le suivi de rattrapage")

# ============================================================
# ONGLET 6 : BULLETIN INDIVIDUEL
# ============================================================
with tab6:
    st.subheader("Bulletin individuel de l'étudiant")

    resultat_df, matieres, valid_ref = construire_resultat_df(ctx)

    if valid_ref.empty:
        st.warning("Aucune liste de référence. Commencez par l'onglet '📋 1. Liste de référence'.")
    else:
        options_bulletin = {
            idx: f"{valid_ref.loc[idx, 'Nom et Prénom']}"
            + (f" — {valid_ref.loc[idx, 'Matricule']}" if str(valid_ref.loc[idx, "Matricule"]).strip() else "")
            for idx in valid_ref.index
        }

        idx_choisi = st.selectbox(
            "🔍 Tapez 2-3 lettres du nom ou prénom de l'étudiant",
            options=list(options_bulletin.keys()), format_func=lambda i: options_bulletin[i],
            index=None, placeholder="Rechercher un étudiant...", key=f"search_bulletin_{CLE}",
        )

        if idx_choisi is not None:
            nom_complet = valid_ref.loc[idx_choisi, "Nom et Prénom"]
            matricule = valid_ref.loc[idx_choisi, "Matricule"]
            notes_etu = notes_effectives_etudiant(ctx, idx_choisi)
            a_rattrape = bool(ctx["rattrapage"].get(str(idx_choisi)))

            st.divider()
            st.markdown(f"## 🎓 Bulletin — {nom_complet}")
            infos = [f"**Année :** {ANNEE}", f"**Filière :** {FILIERE}"]
            if matricule and str(matricule).strip():
                infos.insert(0, f"**Matricule :** {matricule}")
            st.markdown(" &nbsp;|&nbsp; ".join(infos))
            if a_rattrape:
                st.caption("♻️ Ce bulletin intègre les notes de rattrapage déjà saisies.")

            if not matieres:
                st.info("Aucune matière/note saisie pour l'instant.")
            else:
                lignes_bulletin = [{"Matière": mat, "Note /20": notes_etu.get(mat, "—")} for mat in matieres]
                notes_num = [v for v in notes_etu.values() if isinstance(v, (int, float))]
                bulletin_df = pd.DataFrame(lignes_bulletin)
                st.dataframe(bulletin_df, use_container_width=True, hide_index=True)

                moyenne = round(sum(notes_num) / len(notes_num), 2) if notes_num else None
                if moyenne is not None:
                    st.markdown(f"### 📊 Moyenne générale : **{moyenne} / 20**")
                else:
                    st.caption("Aucune note enregistrée pour cet étudiant.")

                nom_fichier = re.sub(r"\s+", "_", str(nom_complet).strip())

                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    csv_bulletin = bulletin_df.to_csv(index=False).encode("utf-8")
                    st.download_button("⬇️ Bulletin (CSV)", csv_bulletin,
                                        f"bulletin_{nom_fichier}.csv", "text/csv",
                                        key=f"dl_bulletin_{CLE}_{idx_choisi}")
                with col2:
                    entete_bulletin = f"Bulletin — {nom_complet} — {ANNEE_ACADEMIQUE} | {ANNEE} — {FILIERE}"
                    st.download_button(
                        "⬇️ Bulletin (Excel)",
                        excel_bytes(bulletin_df, "Bulletin", entete_bulletin),
                        f"bulletin_{nom_fichier}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_bulletin_xlsx_{CLE}_{idx_choisi}",
                    )
                with col3:
                    lignes_html_impression = "".join(
                        f"<tr><td>{html_lib.escape(str(l['Matière']))}</td><td>{html_lib.escape(str(l['Note /20']))}</td></tr>"
                        for l in lignes_bulletin
                    )
                    moyenne_html = f"Moyenne générale : {moyenne} / 20" if moyenne is not None else "Aucune note enregistrée"
                    sous_titre = " | ".join(infos).replace("**", "")
                    bouton_impression(
                        f"Bulletin — {nom_complet}", sous_titre, lignes_html_impression, moyenne_html,
                        cle_widget=f"print_{CLE}_{idx_choisi}",
                    )

        if matieres:
            st.divider()
            st.write("**📚 Export groupé**")
            if st.button("📦 Obtenir tous les bulletins (Excel)", key=f"tous_bulletins_{CLE}"):
                buffer_tous = BytesIO()
                noms_feuilles_utilises = set()
                with pd.ExcelWriter(buffer_tous, engine="openpyxl") as writer:
                    for idx in valid_ref.index:
                        nom_complet_i = str(valid_ref.loc[idx, "Nom et Prénom"]).strip() or f"Etudiant_{idx}"
                        notes_i = notes_effectives_etudiant(ctx, idx)
                        lignes_i = [{"Matière": mat, "Note /20": notes_i.get(mat, "—")} for mat in matieres]
                        notes_num_i = [v for v in notes_i.values() if isinstance(v, (int, float))]
                        moyenne_i = round(sum(notes_num_i) / len(notes_num_i), 2) if notes_num_i else None
                        df_i = pd.DataFrame(lignes_i)

                        feuille = re.sub(r"[\\/*?:\[\]]", "", nom_complet_i)[:28] or f"Etudiant_{idx}"
                        base_feuille = feuille
                        n = 1
                        while feuille in noms_feuilles_utilises:
                            n += 1
                            feuille = f"{base_feuille[:26]}_{n}"
                        noms_feuilles_utilises.add(feuille)

                        pd.DataFrame({f"{nom_complet_i} — Moyenne : {moyenne_i if moyenne_i is not None else '—'}/20": []}) \
                            .to_excel(writer, index=False, sheet_name=feuille, startrow=0)
                        df_i.to_excel(writer, index=False, sheet_name=feuille, startrow=2)

                st.session_state[f"buffer_tous_bulletins_{CLE}"] = buffer_tous.getvalue()
                st.rerun()

            if st.session_state.get(f"buffer_tous_bulletins_{CLE}"):
                st.download_button(
                    "⬇️ Télécharger tous les bulletins (Excel)",
                    st.session_state[f"buffer_tous_bulletins_{CLE}"],
                    f"tous_les_bulletins_{ANNEE}_{FILIERE}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_tous_bulletins_{CLE}",
                )


# ============================================================
# ONGLET 7 : ARCHIVES (consultation en lecture seule, par année académique)
# ============================================================
with tab7:
    st.subheader("🗄️ Archives par année académique")
    st.caption("Retrouvez ici toutes les années académiques déjà utilisées. "
               "Cliquez sur un dossier pour l'ouvrir, jusqu'à la filière souhaitée. "
               "Consultation uniquement : aucune modification possible ici.")

    if "archive_aa" not in st.session_state:
        st.session_state.archive_aa = None
    if "archive_annee" not in st.session_state:
        st.session_state.archive_annee = None
    if "archive_filiere" not in st.session_state:
        st.session_state.archive_filiere = None

    registre = load_state("registre_structure", {})

    if not registre:
        st.info("Aucune donnée enregistrée pour l'instant. Dès que vous travaillez dans "
                "une filière, elle apparaîtra automatiquement ici.")
    else:
        for aa in sorted(registre.keys(), reverse=True):
            aa_ouverte = (st.session_state.archive_aa == aa)
            if st.button(("📂 " if aa_ouverte else "📁 ") + aa, key=f"arch_aa_{aa}", use_container_width=True):
                if aa_ouverte:
                    st.session_state.archive_aa = None
                else:
                    st.session_state.archive_aa = aa
                    st.session_state.archive_annee = None
                    st.session_state.archive_filiere = None
                st.rerun()

            if aa_ouverte:
                for annee in registre[aa]:
                    annee_ouverte = (st.session_state.archive_annee == annee)
                    if st.button(
                        ("　📂 " if annee_ouverte else "　📁 ") + annee,
                        key=f"arch_annee_{aa}_{annee}", use_container_width=True,
                    ):
                        if annee_ouverte:
                            st.session_state.archive_annee = None
                        else:
                            st.session_state.archive_annee = annee
                            st.session_state.archive_filiere = None
                        st.rerun()

                    if annee_ouverte:
                        for filiere in registre[aa][annee]:
                            est_actif = (st.session_state.archive_filiere == filiere)
                            if st.button(
                                ("　　✅ " if est_actif else "　　　") + filiere,
                                key=f"arch_fil_{aa}_{annee}_{filiere}", use_container_width=True,
                            ):
                                st.session_state.archive_filiere = filiere
                                st.rerun()

        if st.session_state.archive_aa and st.session_state.archive_annee and st.session_state.archive_filiere:
            aa_a = st.session_state.archive_aa
            annee_a = st.session_state.archive_annee
            filiere_a = st.session_state.archive_filiere
            cle_a = cle_contexte(aa_a, annee_a, filiere_a)
            ctx_a = charger_contexte(cle_a)

            st.divider()
            st.markdown(f"### 📖 {aa_a} — {annee_a} / {filiere_a}")

            resultat_a, matieres_a, valid_ref_a = construire_resultat_df(ctx_a)

            if valid_ref_a.empty:
                st.caption("Aucun étudiant enregistré pour cette filière, cette année-là.")
            else:
                st.caption(f"👥 {len(valid_ref_a)} étudiant(s) — "
                           f"{len(matieres_a)} matière(s) : {', '.join(matieres_a) if matieres_a else 'aucune'}.")
                tableau_selectionnable(resultat_a, height=420, colonnes_figees=3, cle_widget=f"archive_{cle_a}")

                csv_dl = resultat_a.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Télécharger en CSV", csv_dl, f"archive_{aa_a}_{annee_a}_{filiere_a}.csv", "text/csv",
                    key=f"dl_archive_{cle_a}",
                )

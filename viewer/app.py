"""MemPalace viewer (Streamlit, read-only). Start it with viewer/run_viewer.py."""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from collections import Counter

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mpview import __version__, audit, filters, reports, snapshot, store  # noqa: E402
from mpview.settings import is_loopback, load_settings  # noqa: E402
from mpsync.config import DEFAULT_CONFIG_PATH, ConfigError  # noqa: E402

BRIDGE = os.path.join(HERE, "mpbridge.py")

TEXT = {
    "en": {
        "title": "MemPalace viewer",
        "readonly": "Read-only · works on a snapshot, never on the live palace",
        "unsafe": "Refusing to run: Streamlit must listen on 127.0.0.1 with usage statistics off. Start it with viewer/run_viewer.py.",
        "snapshot": "Snapshot",
        "taken": "taken at",
        "refresh": "New snapshot",
        "busy": "The palace is in use (a writer holds the lock or files are changing). Showing the previous snapshot.",
        "busy_none": "The palace is in use and there is no snapshot yet. Try again in a moment.",
        "taking": "Copying the palace…",
        "tab_search": "Search", "tab_browse": "Browse", "tab_audit": "Audit", "tab_panel": "Reports",
        "query": "Query", "wing": "Wing", "room": "Room", "all": "(all)", "from": "From", "to": "To",
        "results": "Results", "search": "Search", "no_results": "No results.",
        "searching": "Searching the snapshot…", "search_failed": "Search failed",
        "file": "Source file", "filed": "Filed", "authored": "Authored", "similarity": "similarity",
        "drawers": "drawers", "wings": "Wings", "rooms": "Rooms", "files": "Source files",
        "last_filed": "Last filed", "loading": "Reading the snapshot…",
        "run_audit": "Run audit", "auditing": "Scanning every drawer…",
        "audit_intro": "Looks for IPv4 addresses, ghp_/github_pat_, sk-, AKIA/ASIA keys, private keys, .env secrets and military rank + name (multicast, link-local and public DNS addresses are ignored). One row per distinct value; rank + name is low confidence when the rank is an everyday word (General, Major, Cabo, Soldado, TC). Matches are masked; nothing is changed.",
        "kind": "Kind", "masked": "Match (masked)", "snippet": "Snippet (masked)", "drawer": "Drawer",
        "count": "Count", "found": "findings", "none_found": "Nothing found.",
        "confidence": "Confidence", "conf_high": "high", "conf_low": "low", "conf_all": "all",
        "values": "distinct values", "wings": "Wings",
        "select_row": "select a row to see its occurrences",
        "csv": "Download CSV (masked)", "how_remove": "How to remove a drawer (CLI, not done here)",
        "remove_md": (
            "The viewer never deletes. If you decide to remove something:\n\n"
            "1. **Fix the source first** (delete the file or the secret), or the next sync mines it again.\n"
            "2. **Drawers whose source file was deleted or moved:** preview, then apply\n\n"
            "   ```\n   <python> -m mempalace sync --wing <wing> --dry-run\n"
            "   <python> -m mempalace sync --wing <wing> --apply\n   ```\n"
            "3. **One drawer by id** (the *Drawer* column): MemPalace 3.10 has no CLI command for it; "
            "use the MCP tool `mempalace_delete_drawer` (e.g. ask Claude Code with the MemPalace MCP server connected).\n"
            "4. Take a new snapshot here and re-run the audit."
        ),
        "growth": "Drawers per wing over time", "growth_none": "No sync report with a status table yet.",
        "report": "Report", "no_reports": "No reports in", "kind_sync": "sync", "kind_dry-run": "dry run",
        "kind_curation": "curation", "kind_other": "other",
    },
    "pt": {
        "title": "Viewer do MemPalace",
        "readonly": "Só leitura · trabalha sobre um snapshot, nunca no palace ao vivo",
        "unsafe": "Recusando rodar: o Streamlit precisa escutar em 127.0.0.1 e com estatísticas de uso desligadas. Inicie pelo viewer/run_viewer.py.",
        "snapshot": "Snapshot",
        "taken": "tirado em",
        "refresh": "Novo snapshot",
        "busy": "O palace está em uso (um escritor segura o lock ou arquivos estão mudando). Mostrando o snapshot anterior.",
        "busy_none": "O palace está em uso e ainda não há snapshot. Tente de novo em instantes.",
        "taking": "Copiando o palace…",
        "tab_search": "Busca", "tab_browse": "Navegação", "tab_audit": "Auditoria", "tab_panel": "Relatórios",
        "query": "Consulta", "wing": "Wing", "room": "Room", "all": "(todas)", "from": "De", "to": "Até",
        "results": "Resultados", "search": "Buscar", "no_results": "Nenhum resultado.",
        "searching": "Buscando no snapshot…", "search_failed": "A busca falhou",
        "file": "Arquivo de origem", "filed": "Arquivado", "authored": "Escrito", "similarity": "similaridade",
        "drawers": "drawers", "wings": "Wings", "rooms": "Rooms", "files": "Arquivos de origem",
        "last_filed": "Último arquivamento", "loading": "Lendo o snapshot…",
        "run_audit": "Rodar auditoria", "auditing": "Varrendo todos os drawers…",
        "audit_intro": "Procura IPv4, ghp_/github_pat_, sk-, chaves AKIA/ASIA, chaves privadas, segredos de .env e posto + nome (multicast, link-local e DNS públicos são ignorados). Uma linha por valor distinto; posto + nome tem confiança baixa quando o posto é palavra comum (General, Major, Cabo, Soldado, TC). Os trechos ficam mascarados; nada é alterado.",
        "kind": "Tipo", "masked": "Ocorrência (mascarada)", "snippet": "Trecho (mascarado)", "drawer": "Drawer",
        "count": "Qtde", "found": "ocorrências", "none_found": "Nada encontrado.",
        "confidence": "Confiança", "conf_high": "alta", "conf_low": "baixa", "conf_all": "todas",
        "values": "valores distintos", "wings": "Wings",
        "select_row": "selecione uma linha para ver as ocorrências",
        "csv": "Baixar CSV (mascarado)", "how_remove": "Como remover um drawer (pela CLI, não por aqui)",
        "remove_md": (
            "O viewer nunca apaga. Se você decidir remover algo:\n\n"
            "1. **Corrija a origem antes** (apague o arquivo ou o segredo), senão o próximo sync minera de novo.\n"
            "2. **Drawers cujo arquivo de origem foi apagado ou movido:** simule e depois aplique\n\n"
            "   ```\n   <python> -m mempalace sync --wing <wing> --dry-run\n"
            "   <python> -m mempalace sync --wing <wing> --apply\n   ```\n"
            "3. **Um drawer pelo id** (coluna *Drawer*): o MemPalace 3.10 não tem comando de CLI para isso; "
            "use a ferramenta MCP `mempalace_delete_drawer` (ex.: peça ao Claude Code com o servidor MCP do MemPalace conectado).\n"
            "4. Tire um novo snapshot aqui e rode a auditoria de novo."
        ),
        "growth": "Drawers por wing ao longo do tempo", "growth_none": "Ainda não há relatório do sync com tabela de status.",
        "report": "Relatório", "no_reports": "Nenhum relatório em", "kind_sync": "sync", "kind_dry-run": "simulação",
        "kind_curation": "curadoria", "kind_other": "outro",
    },
}


def _cli_config() -> str:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    return p.parse_known_args(sys.argv[1:])[0].config


st.set_page_config(page_title="MemPalace viewer", page_icon="🏛️", layout="wide")

# Second line of defence (run_viewer.py and viewer/.streamlit/config.toml set these too).
if not is_loopback(str(st.get_option("server.address") or "")) or st.get_option("browser.gatherUsageStats"):
    st.error(TEXT["en"]["unsafe"])
    st.stop()

try:
    SETTINGS = load_settings(_cli_config())
except ConfigError as exc:
    st.error(f"config: {exc}")
    st.stop()

T = TEXT.get(SETTINGS.language, TEXT["en"])


@st.cache_data(show_spinner=False, max_entries=2)
def load_drawers(db_path: str, collection: str):
    return list(store.iter_drawers(db_path, collection))


@st.cache_data(show_spinner=False, max_entries=2)
def load_tree(db_path: str, collection: str):
    return store.build_tree(load_drawers(db_path, collection))


@st.cache_data(show_spinner=False, max_entries=2)
def run_audit(db_path: str, collection: str, extras: tuple):
    rules = audit.build_rules(extras)
    return audit.scan(load_drawers(db_path, collection), rules)


def ensure_snapshot(force: bool = False):
    snap = snapshot.current(SETTINGS.snapshot_dir)
    if snap and not force:
        return snap, None
    try:
        with st.spinner(T["taking"]):
            return snapshot.take(SETTINGS.palace, SETTINGS.snapshot_dir), None
    except snapshot.PalaceBusy:
        return snap, (T["busy"] if snap else T["busy_none"])
    except snapshot.SnapshotError as exc:
        return snap, str(exc)


def run_search(snap, req):
    argv = filters.bridge_argv(SETTINGS.mempalace_python, BRIDGE, snap.path, SETTINGS.palace, req)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=300, creationflags=flags)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        raise RuntimeError((proc.stderr or proc.stdout or "no output").strip()[-1500:])
    data = json.loads(lines[-1])
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["results"]


# ---------------------------------------------------------------- sidebar
st.sidebar.title(T["title"])
st.sidebar.caption(f"v{__version__} · {T['readonly']}")
force = st.sidebar.button(T["refresh"], width="stretch")
SNAP, warning = ensure_snapshot(force)
if warning:
    st.sidebar.warning(warning)
if SNAP is None:
    st.stop()
st.sidebar.markdown(
    f"**{T['snapshot']}** {T['taken']} `{SNAP.taken_at.replace('T', ' ')}`  \n"
    f"{SNAP.bytes / 1e6:.0f} MB · {SNAP.files} files"
)

with st.spinner(T["loading"]):
    TREE = load_tree(SNAP.db, SETTINGS.collection_name)
st.sidebar.metric(T["drawers"], f"{TREE.total:,}".replace(",", "."))

tab_search, tab_browse, tab_audit, tab_panel = st.tabs(
    [T["tab_search"], T["tab_browse"], T["tab_audit"], T["tab_panel"]]
)

# ---------------------------------------------------------------- search
with tab_search:
    wing_rooms = {w: TREE.rooms(w) for w in TREE.wings()}
    # No st.form: the room list must follow the chosen wing.
    c1, c2, c3, c4, c5 = st.columns([2, 2, 1.3, 1.3, 1])
    wing = c1.selectbox(T["wing"], [filters.ALL] + TREE.wings(), format_func=lambda w: w or T["all"])
    room = c2.selectbox(T["room"], [filters.ALL] + filters.rooms_for(wing, wing_rooms),
                        format_func=lambda r: r or T["all"])
    start = c3.date_input(T["from"], value=None, format="YYYY-MM-DD")
    end = c4.date_input(T["to"], value=None, format="YYYY-MM-DD")
    limit = c5.number_input(T["results"], 1, 100, 10)
    query = st.text_input(T["query"])
    if st.button(T["search"], type="primary") and query.strip():
        try:
            req = filters.build(query, wing, room, start, end, int(limit))
            with st.spinner(T["searching"]):
                st.session_state["hits"] = run_search(SNAP, req)
        except (filters.FilterError, RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            st.error(f"{T['search_failed']}: {exc}")
            st.session_state["hits"] = None
    hits = st.session_state.get("hits")
    if hits == []:
        st.info(T["no_results"])
    for h in hits or []:
        date = (h.get("filed_at") or "")[:16].replace("T", " ")
        authored = (h.get("authored_at") or "")[:16].replace("T", " ")
        st.markdown(
            f"**`{h.get('wing')}` / `{h.get('room')}`** · {T['file']}: `{h.get('source_file')}` · "
            f"{T['filed']}: {date}" + (f" · {T['authored']}: {authored}" if authored else "")
            + f" · {T['similarity']} {h.get('similarity')}"
        )
        st.text(h.get("text") or "")
        st.divider()

# ---------------------------------------------------------------- browse
with tab_browse:
    st.dataframe(
        [{T["wing"]: w, T["rooms"]: len(TREE.rooms(w)), T["drawers"]: TREE.wing_total(w)} for w in TREE.wings()],
        hide_index=True, width="stretch",
    )
    c1, c2 = st.columns(2)
    bw = c1.selectbox(T["wing"], TREE.wings(), key="bw",
                      format_func=lambda w: f"{w} ({TREE.wing_total(w)})")
    br = c2.selectbox(T["room"], TREE.rooms(bw), key="br",
                      format_func=lambda r: f"{r} ({TREE.room_total(bw, r)})")
    if br:
        st.subheader(f"{T['files']} · {bw} / {br}")
        st.dataframe(
            [
                {T["file"]: store.source_name(src), T["drawers"]: n,
                 T["last_filed"]: TREE.last_filed.get(src, "")[:16].replace("T", " "), "path": src}
                for src, n in TREE.files(bw, br)
            ],
            hide_index=True, width="stretch",
        )

# ---------------------------------------------------------------- audit
with tab_audit:
    st.caption(T["audit_intro"])
    extras = tuple((p.name, p.regex) for p in SETTINGS.extra_patterns)
    if st.button(T["run_audit"]) or st.session_state.get("audited") == SNAP.path:
        st.session_state["audited"] = SNAP.path
        with st.spinner(T["auditing"]):
            findings = run_audit(SNAP.db, SETTINGS.collection_name, extras)
        st.markdown(f"**{len(findings)}** {T['found']}")
        if not findings:
            st.success(T["none_found"])
        else:
            kinds = sorted({f.kind for f in findings})
            wings = sorted({f.wing for f in findings})
            c0, c1, c2 = st.columns([1, 2, 2])
            conf = c0.radio(T["confidence"], [audit.HIGH, audit.LOW, "all"], horizontal=True,
                            format_func=lambda c: T["conf_" + c])
            fk = c1.multiselect(T["kind"], kinds, default=kinds)
            fw = c2.multiselect(T["wing"], wings, default=wings)
            shown = [f for f in findings if f.kind in fk and f.wing in fw and conf in ("all", f.confidence)]
            groups = audit.group(shown)
            st.caption(f"{len(groups)} {T['values']} · {len(shown)} {T['found']} · {T['select_row']}")
            event = st.dataframe(
                [{"#": i + 1, T["kind"]: g.kind, T["masked"]: g.masked, T["confidence"]: T["conf_" + g.confidence],
                  T["count"]: g.count, T["wings"]: ", ".join(g.wings)} for i, g in enumerate(groups)],
                hide_index=True, width="stretch",
                on_select="rerun", selection_mode="single-row", key="audit_groups",
            )
            picked = event.selection.rows if event is not None else []
            if picked and picked[0] < len(groups):
                g = groups[picked[0]]
                st.markdown(f"**#{picked[0] + 1} · {g.kind} · `{g.masked}`** — {g.count} {T['found']}")
                st.dataframe(
                    [{T["wing"]: f.wing, T["room"]: f.room, T["file"]: f.source_name,
                      T["snippet"]: f.snippet, T["drawer"]: f.drawer_id} for f in g.findings],
                    hide_index=True, width="stretch",
                )
            rows = [
                {"#": i + 1, T["kind"]: f.kind, T["confidence"]: f.confidence, T["wing"]: f.wing,
                 T["room"]: f.room, T["file"]: f.source_name, T["masked"]: f.masked,
                 T["snippet"]: f.snippet, T["drawer"]: f.drawer_id}
                for i, g in enumerate(groups) for f in g.findings
            ]
            buf = io.StringIO()
            if rows:
                writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            st.download_button(T["csv"], buf.getvalue(), "mempalace-audit.csv", "text/csv")
    with st.expander(T["how_remove"]):
        st.markdown(T["remove_md"])

# ---------------------------------------------------------------- reports
with tab_panel:
    files = reports.list_reports(SETTINGS.reports)
    st.subheader(T["growth"])
    points = reports.growth(files)
    if points:
        import pandas as pd

        frame = pd.DataFrame({day: counts for day, counts in points}).T.fillna(0).astype(int)
        frame.index.name = "date"
        # One day of history is a single point, invisible on a line chart.
        (st.line_chart if len(frame) > 1 else st.bar_chart)(frame)
        st.dataframe(frame.T, width="stretch")
    else:
        st.info(T["growth_none"])
    if not files:
        st.info(f"{T['no_reports']} {SETTINGS.reports}")
    else:
        kinds = Counter(f.kind for f in files)
        choice = st.selectbox(
            T["report"], files,
            format_func=lambda f: f"{f.name}  ·  {T['kind_' + f.kind]}",
        )
        st.caption(" · ".join(f"{T['kind_' + k]}: {n}" for k, n in sorted(kinds.items())))
        with open(choice.path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        if choice.is_markdown:
            st.markdown(body)
        else:
            st.code(body, language="diff" if choice.name.endswith(".diff") else None)

"""
שרת Flask — כלי נספחים משפטיים
"""

import os
import sys

# WeasyPrint needs Homebrew's pango/glib. If launched from a macOS .app,
# DYLD_LIBRARY_PATH may be stripped before Python starts. Re-exec with it
# set so the dynamic linker picks it up from the very beginning.
_HOMEBREW_LIB = "/opt/homebrew/lib"
if os.path.isdir(_HOMEBREW_LIB) and _HOMEBREW_LIB not in os.environ.get("DYLD_LIBRARY_PATH", ""):
    os.environ["DYLD_LIBRARY_PATH"] = _HOMEBREW_LIB + ":" + os.environ.get("DYLD_LIBRARY_PATH", "")
    os.execv(sys.executable, [sys.executable] + sys.argv)

import io
import json
import os
import re
import shutil
import uuid
from datetime import datetime

_UUID_RE    = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_FILE_ID_RE = re.compile(r'^[0-9a-f]{8}$')

def _safe_project_id(pid: str) -> str:
    if not pid or not _UUID_RE.match(pid):
        raise ValueError('מזהה פרויקט לא תקין')
    return pid

def _safe_file_id(fid: str) -> str:
    if not fid or not _FILE_ID_RE.match(fid):
        raise ValueError('מזהה קובץ לא תקין')
    return fid

from flask import Flask, request, jsonify, send_file, render_template
from processor import process_appendices

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB

PROJECTS_DIR = os.path.join(os.path.dirname(__file__), "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

_results: dict[str, bytes] = {}   # in-memory cache of generated PDFs


# ── helpers ─────────────────────────────────────────────────────────────────

def _load_meta(project_id: str) -> dict | None:
    path = os.path.join(PROJECTS_DIR, project_id, "meta.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_meta(project_id: str, meta: dict):
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(project_dir, exist_ok=True)
    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ── main page ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── project CRUD ─────────────────────────────────────────────────────────────

@app.route('/projects/list')
def list_projects():
    projects = []
    if os.path.exists(PROJECTS_DIR):
        for pid in os.listdir(PROJECTS_DIR):
            meta = _load_meta(pid)
            if meta:
                projects.append({
                    'id': meta['id'],
                    'name': meta.get('name', 'ללא שם'),
                    'updated': meta.get('updated', meta.get('created', '')),
                    'count': len(meta.get('appendices', [])),
                })
    projects.sort(key=lambda x: x['updated'], reverse=True)
    return jsonify(projects)


@app.route('/projects/<project_id>', methods=['GET'])
def get_project(project_id):
    meta = _load_meta(project_id)
    if not meta:
        return jsonify({'error': 'לא נמצא'}), 404
    return jsonify(meta)


@app.route('/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)
    return jsonify({'ok': True})


def _resolve_section(section_items, uploaded_files, upload_idx, project_dir, existing_by_id):
    """
    Resolve a list of {name, source, [add_numbering]} items into stored files.
    Returns (resolved_list, new_upload_idx).
    Each resolved item: {id, name, original_filename, [add_numbering]}
    """
    resolved = []
    for item in section_items:
        source = item['source']
        name   = item['name']
        extra  = {k: v for k, v in item.items() if k not in ('source', 'name')}
        if source == 'new':
            if upload_idx >= len(uploaded_files):
                raise ValueError('חסרים קבצים להעלאה')
            uf = uploaded_files[upload_idx]
            upload_idx += 1
            file_id = str(uuid.uuid4())[:8]
            uf.save(os.path.join(project_dir, f"{file_id}.pdf"))
            resolved.append({'id': file_id, 'name': name,
                              'original_filename': uf.filename, **extra})
        else:
            existing = existing_by_id.get(_safe_file_id(source))
            if not existing:
                raise ValueError(f'קובץ {source} לא נמצא בפרויקט')
            resolved.append({**existing, 'name': name, **extra})
    return resolved, upload_idx


@app.route('/projects/save', methods=['POST'])
def save_project():
    """
    Save (create or update) a project.

    Form fields:
      project_id        — optional; if given, updates existing project
      project_name      — display name
      start_page        — integer

      -- Main document (optional) --
      main_source       — 'new' | file_id | '' (absent)
      main_name         — display name
      main_add_numbering — '1' or '0'
      main_pdf          — file upload (only when main_source == 'new')

      -- Pre-TOC docs (optional, repeated) --
      pre_names[]       — names
      pre_sources[]     — 'new' | file_id
      pre_pdfs[]        — file uploads for new items

      -- Appendices --
      names[]           — appendix names
      sources[]         — 'new' | file_id
      pdfs[]            — file uploads for new items
    """
    try:
        raw_id = request.form.get('project_id', '').strip()
        project_id   = _safe_project_id(raw_id) if raw_id else str(uuid.uuid4())
        project_name = request.form.get('project_name', '').strip() or 'פרויקט ללא שם'
        start_page   = max(1, int(request.form.get('start_page', 1) or 1))

        project_dir = os.path.join(PROJECTS_DIR, project_id)
        os.makedirs(project_dir, exist_ok=True)

        existing_meta = _load_meta(project_id) or {}

        # Build a flat lookup of all existing stored file ids
        all_existing = {}
        if existing_meta.get('main_doc'):
            all_existing[existing_meta['main_doc']['id']] = existing_meta['main_doc']
        for d in existing_meta.get('pre_toc_docs', []):
            all_existing[d['id']] = d
        for a in existing_meta.get('appendices', []):
            all_existing[a['id']] = a

        # Collect ALL uploaded files in one list (order: main, pre, appendices)
        all_uploads = (
            request.files.getlist('main_pdf') +
            request.files.getlist('pre_pdfs[]') +
            request.files.getlist('pdfs[]')
        )
        upload_idx = 0

        # ── Main document ────────────────────────────────────────────────────
        main_source = request.form.get('main_source', '').strip()
        new_main_doc = None
        if main_source:
            add_num = request.form.get('main_add_numbering', '0') == '1'
            items, upload_idx = _resolve_section(
                [{'source': main_source, 'name': request.form.get('main_name', 'כתב הטענות'),
                  'add_numbering': add_num}],
                all_uploads, upload_idx, project_dir, all_existing
            )
            new_main_doc = items[0]

        # ── Pre-TOC docs ─────────────────────────────────────────────────────
        pre_names   = request.form.getlist('pre_names[]')
        pre_sources = request.form.getlist('pre_sources[]')
        pre_items   = [{'source': s, 'name': n} for s, n in zip(pre_sources, pre_names)]
        new_pre_toc, upload_idx = _resolve_section(
            pre_items, all_uploads, upload_idx, project_dir, all_existing
        )

        # ── Appendices ───────────────────────────────────────────────────────
        names   = request.form.getlist('names[]')
        sources = request.form.getlist('sources[]')
        app_items = [{'source': s, 'name': n} for s, n in zip(sources, names)]
        new_appendices, upload_idx = _resolve_section(
            app_items, all_uploads, upload_idx, project_dir, all_existing
        )

        meta = {
            'id': project_id,
            'name': project_name,
            'created': existing_meta.get('created', datetime.now().isoformat()),
            'updated': datetime.now().isoformat(),
            'start_page': start_page,
            'main_doc': new_main_doc,
            'pre_toc_docs': new_pre_toc,
            'appendices': new_appendices,
        }
        _save_meta(project_id, meta)

        # Clean up orphaned files
        kept = set()
        if new_main_doc: kept.add(new_main_doc['id'])
        kept |= {d['id'] for d in new_pre_toc}
        kept |= {a['id'] for a in new_appendices}
        for fname in os.listdir(project_dir):
            if fname.endswith('.pdf') and fname[:-4] not in kept:
                os.remove(os.path.join(project_dir, fname))

        return jsonify({'id': project_id, 'name': project_name})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── process ──────────────────────────────────────────────────────────────────

@app.route('/process', methods=['POST'])
def process():
    """
    Generate the output PDF.

    Form fields:
      project_id          — optional; needed when referencing stored file IDs
      start_page          — integer

      -- Main document (optional) --
      main_source         — 'new' | file_id | '' (absent)
      main_name           — display name
      main_add_numbering  — '1' or '0'
      main_pdf            — file upload (only when main_source == 'new')

      -- Pre-TOC docs (optional, repeated) --
      pre_names[]         — names
      pre_sources[]       — 'new' | file_id
      pre_pdfs[]          — file uploads for new items

      -- Appendices --
      names[]             — appendix names
      sources[]           — 'new' | file_id
      pdfs[]              — file uploads for new items
    """
    try:
        raw_id = request.form.get('project_id', '').strip()
        project_id = _safe_project_id(raw_id) if raw_id else ''
        start_page = max(1, int(request.form.get('start_page', 1) or 1))

        project_dir = os.path.join(PROJECTS_DIR, project_id) if project_id else None

        # Build lookup of existing stored files
        existing_meta = _load_meta(project_id) if project_id else {}
        all_existing = {}
        if existing_meta:
            if existing_meta.get('main_doc'):
                all_existing[existing_meta['main_doc']['id']] = existing_meta['main_doc']
            for d in existing_meta.get('pre_toc_docs', []):
                all_existing[d['id']] = d
            for a in existing_meta.get('appendices', []):
                all_existing[a['id']] = a

        def _read_source(source, uploaded_files, upload_idx):
            """Return (pdf_bytes, new_upload_idx)."""
            if source == 'new':
                if upload_idx >= len(uploaded_files):
                    raise ValueError('חסרים קבצים להעלאה')
                uf = uploaded_files[upload_idx]
                if not uf.filename.lower().endswith('.pdf'):
                    raise ValueError(f'"{uf.filename}" אינו PDF')
                return uf.read(), upload_idx + 1
            else:
                if not project_id:
                    raise ValueError('חסר project_id לקבצים מאוחסנים')
                file_path = os.path.join(PROJECTS_DIR, project_id, f"{_safe_file_id(source)}.pdf")
                if not os.path.exists(file_path):
                    raise ValueError(f'קובץ {source} לא נמצא')
                with open(file_path, 'rb') as fh:
                    return fh.read(), upload_idx

        # Collect ALL uploaded files in order: main, pre, appendices
        all_uploads = (
            request.files.getlist('main_pdf') +
            request.files.getlist('pre_pdfs[]') +
            request.files.getlist('pdfs[]')
        )
        upload_idx = 0

        # ── Main document ────────────────────────────────────────────────────
        main_source = request.form.get('main_source', '').strip()
        main_doc = None
        if main_source:
            pdf_bytes, upload_idx = _read_source(main_source, all_uploads, upload_idx)
            add_num = request.form.get('main_add_numbering', '0') == '1'
            main_doc = {'pdf_bytes': pdf_bytes, 'add_numbering': add_num}

        # ── Pre-TOC documents ─────────────────────────────────────────────────
        pre_names   = request.form.getlist('pre_names[]')
        pre_sources = request.form.getlist('pre_sources[]')
        pre_toc_docs = []
        for name, source in zip(pre_names, pre_sources):
            pdf_bytes, upload_idx = _read_source(source, all_uploads, upload_idx)
            pre_toc_docs.append({'pdf_bytes': pdf_bytes, 'name': name})

        # ── Appendices ───────────────────────────────────────────────────────
        names   = request.form.getlist('names[]')
        sources = request.form.getlist('sources[]')
        appendices = []
        for name, source in zip(names, sources):
            pdf_bytes, upload_idx = _read_source(source, all_uploads, upload_idx)
            appendices.append({'pdf_bytes': pdf_bytes, 'name': name})

        if not appendices:
            return jsonify({'error': 'לא נמצאו נספחים לעיבוד'}), 400

        result_pdf = process_appendices(
            appendices,
            start_page_offset=start_page,
            main_doc=main_doc,
            pre_toc_docs=pre_toc_docs,
        )
        result_id = str(uuid.uuid4())
        _results[result_id] = result_pdf
        return jsonify({'id': result_id, 'count': len(appendices)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/download/<result_id>')
def download(result_id):
    pdf_bytes = _results.get(result_id)
    if not pdf_bytes:
        return 'לא נמצא', 404
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name='נספחים.pdf',
    )


if __name__ == '__main__':
    print("🟢 כלי נספחים — http://localhost:5050")
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, port=5050, host='127.0.0.1')

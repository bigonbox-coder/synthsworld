#!/usr/bin/env python3
"""Synthsworld admin/review panel. Stdlib only, no dependencies.

Standalone app, deliberately NOT part of the marveen dashboard codebase.
Binds to the Tailscale interface only (see BIND_HOST) -- never the public
internet. Auth: a single bearer-style token, read once from ?token=<...> in
the URL and remembered via a cookie for the browser session, same UX as the
marveen dashboard's own token flow.

Reversible review actions: approve/unapprove just flips
manufacturers.confidence_level and ALWAYS appends a row to
manufacturer_review_log, so nothing is a silent one-way edit.
"""
import http.server
import json
import os
import secrets
import socketserver
import sqlite3
import urllib.parse
from http import cookies

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "synthsworld.sqlite")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")
LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logos")
COOKIE_NAME = "synthsworld_admin_token"

BIND_HOST = os.environ.get("SYNTHSWORLD_ADMIN_HOST", "100.123.64.100")
PORT = int(os.environ.get("SYNTHSWORLD_ADMIN_PORT", "3421"))


def load_or_create_token() -> str:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                return t
    tok = secrets.token_hex(32)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(tok)
    os.chmod(TOKEN_FILE, 0o600)
    return tok


TOKEN = load_or_create_token()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def logo_rel_path(mid):
    """Local static-file path for a manufacturer's logo thumbnail, or None.
    Master assets live in Drive (source of truth); this is a small local
    copy so the admin page never depends on Drive sharing/hotlinking."""
    for ext in ("svg", "png"):
        p = os.path.join(LOGO_DIR, f"{mid}.{ext}")
        if os.path.exists(p):
            return f"/static/logos/{mid}.{ext}"
    return None


def logo_status(con, mid):
    """Three states, not two -- distinguish 'never looked' from 'looked,
    nothing found', same reasoning as the confirmed/needs_review/unresearched
    split on the manufacturer itself (Kristóf's request, 2026-08-30).
    Returns 'found' | 'not_found' | 'not_attempted'."""
    path = logo_rel_path(mid)
    if path:
        return "found", path
    row = con.execute(
        "SELECT 1 FROM manufacturer_logos WHERE manufacturer_id=?", (mid,)
    ).fetchone()
    return ("not_found", None) if row else ("not_attempted", None)


def esc(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


STYLE = """
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #f6f5f2; color: #222; }
  header { background: #1c1c1e; color: #fff; padding: 14px 16px; font-size: 1.1rem; font-weight: 600; }
  .wrap { padding: 12px; max-width: 900px; margin: 0 auto; }
  input[type=search] { width: 100%; padding: 12px; font-size: 1rem; border: 1px solid #ccc; border-radius: 8px; margin-bottom: 10px; }
  .card { display: flex; align-items: center; gap: 10px; padding: 12px 14px; margin-bottom: 8px; background: #fff; border-radius: 10px; text-decoration: none; color: #222; border: 1px solid #e5e3dd; }
  .card-text { flex: 1 1 auto; min-width: 0; }
  .card:active { background: #f0efe9; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
  .logo-thumb { width: 48px; height: 48px; object-fit: contain; border-radius: 6px; background: #fff; border: 1px solid #eee; flex: 0 0 auto; order: 2; }
  .logo-missing { width: 48px; height: 48px; border-radius: 6px; background: #f0efe9; border: 1px dashed #ccc; flex: 0 0 auto; order: 2; display: flex; align-items: center; justify-content: center; font-size: 0.6rem; color: #999; text-align: center; line-height: 1; }
  .logo-detail { max-width: 140px; max-height: 80px; object-fit: contain; display: block; margin-bottom: 10px; }
  .logo-detail-missing { display: inline-block; padding: 8px 12px; border-radius: 8px; background: #f0efe9; border: 1px dashed #ccc; color: #888; font-size: 0.85rem; margin-bottom: 10px; }
  .dot.confirmed { background: #2e9e4f; }
  .dot.needs_review { background: #d9a520; }
  .dot.unresearched { background: #8b93a3; }
  .name { font-weight: 600; font-size: 1.05rem; }
  .sub { color: #666; font-size: 0.85rem; margin-top: 2px; }
  h1 { font-size: 1.3rem; margin: 4px 0 10px; }
  .meta-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; font-size: 0.85rem; color: #555; }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }
  .pill.confirmed { background: #e3f5e8; color: #1e7a37; }
  .pill.needs_review { background: #fbf0d6; color: #96731a; }
  .pill.unresearched { background: #e8eaee; color: #565f6f; }
  section { margin: 14px 0; }
  section h2 { font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.02em; color: #777; margin-bottom: 4px; }
  .stats { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .stat { flex: 1 1 90px; background: #fff; border: 1px solid #e5e3dd; border-radius: 10px; padding: 10px 12px; text-align: center; }
  .stat .n { font-size: 1.4rem; font-weight: 700; display: block; }
  .stat.confirmed .n { color: #1e7a37; }
  .stat.needs_review .n { color: #96731a; }
  .stat.unresearched .n { color: #565f6f; }
  .stat .lbl { font-size: 0.72rem; color: #777; text-transform: uppercase; letter-spacing: 0.02em; }
  .review-section { background: #fbf3df; border: 1px solid #ecd8a3; border-radius: 12px; padding: 10px 12px 4px; margin-bottom: 16px; }
  .review-section h2 { color: #96731a; margin-bottom: 8px; }
  .review-section .card { border-color: #ecd8a3; }
  .azbar { position: sticky; top: 0; z-index: 5; display: flex; overflow-x: auto; gap: 2px; background: #f6f5f2; padding: 6px 0; margin-bottom: 6px; -webkit-overflow-scrolling: touch; }
  .azbar a { flex: 0 0 auto; min-width: 30px; min-height: 30px; display: flex; align-items: center; justify-content: center; border-radius: 6px; background: #fff; border: 1px solid #e5e3dd; color: #333; text-decoration: none; font-size: 0.85rem; font-weight: 600; }
  .azbar a.empty { color: #ccc; border-color: #eee; pointer-events: none; }
  .letter-group { margin-bottom: 4px; }
  .letter-heading { font-size: 1rem; font-weight: 700; color: #999; padding: 10px 2px 4px; scroll-margin-top: 46px; }
  .btn { display: inline-block; padding: 12px 18px; border-radius: 8px; border: none; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn-approve { background: #2e9e4f; color: #fff; }
  .btn-unapprove { background: #d9a520; color: #fff; }
  .btn-disabled { background: #d5d8de; color: #6b7280; cursor: not-allowed; }
  .btn-toggle { display: inline-block; margin-top: 6px; padding: 8px 14px; border-radius: 6px; border: 1px solid #ccc; background: #fff; font-size: 0.9rem; cursor: pointer; min-height: 36px; }
  .long-history { margin-top: 10px; line-height: 1.6; }
  .back { display: inline-block; margin-bottom: 14px; padding: 12px 18px; min-height: 44px; box-sizing: border-box; color: #333; text-decoration: none; background: #fff; border: 1px solid #ccc; border-radius: 8px; font-size: 1rem; font-weight: 600; }
  textarea { width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #ccc; font-size: 1rem; min-height: 70px; }
  .note-list li { background: #fff; border: 1px solid #e5e3dd; border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; list-style: none; }
  .note-meta { color: #888; font-size: 0.75rem; }
  ul { padding-left: 0; }
  li.timeline, li.relations-list { list-style: none; padding: 4px 0; border-bottom: 1px solid #eee; }
  @media (min-width: 700px) {
    .wrap { padding: 24px; }
  }
</style>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the service log quiet; systemd captures stdout separately if needed

    def _auth_token(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "token" in qs and qs["token"][0] == TOKEN:
            return True, True  # valid, came-from-url
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE_NAME in c and c[COOKIE_NAME].value == TOKEN:
            return True, False
        return False, False

    def _send_html(self, body, set_cookie=False):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if set_cookie:
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={TOKEN}; Path=/; HttpOnly; SameSite=Lax")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send_json(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Unauthorized")

    # ---- GET ----
    def do_GET(self):
        ok, from_url = self._auth_token()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if not ok:
            self._unauthorized()
            return

        if path == "/" or path == "":
            self._render_list(set_cookie=from_url)
            return

        if path.startswith("/static/logos/"):
            self._serve_logo(path)
            return

        if path.startswith("/manufacturer/"):
            try:
                mid = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self.send_response(404)
                self.end_headers()
                return
            self._render_detail(mid, set_cookie=from_url)
            return

        self.send_response(404)
        self.end_headers()

    # ---- POST ----
    def do_POST(self):
        ok, _ = self._auth_token()
        if not ok:
            self._unauthorized()
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}

        if path.startswith("/api/manufacturer/") and path.endswith("/toggle"):
            mid = int(path.split("/")[3])
            self._toggle_approval(mid)
            return

        if path.startswith("/api/manufacturer/") and path.endswith("/note"):
            mid = int(path.split("/")[3])
            self._add_note(mid, data.get("note", "").strip())
            return

        self.send_response(404)
        self.end_headers()

    def _serve_logo(self, path):
        # path like /static/logos/<mid>.<ext> -- resolve safely under LOGO_DIR,
        # no path traversal (basename only, extension whitelist).
        fname = os.path.basename(path)
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        if ext not in ("svg", "png", "jpg", "jpeg"):
            self.send_response(404)
            self.end_headers()
            return
        fpath = os.path.join(LOGO_DIR, fname)
        if not os.path.isfile(fpath) or os.path.dirname(os.path.abspath(fpath)) != os.path.abspath(LOGO_DIR):
            self.send_response(404)
            self.end_headers()
            return
        mime = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}[ext]
        with open(fpath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    # ---- actions ----
    def _toggle_approval(self, mid):
        con = db()
        cur = con.cursor()
        row = cur.execute("SELECT confidence_level FROM manufacturers WHERE id=?", (mid,)).fetchone()
        if not row:
            con.close()
            self._send_json({"error": "not found"}, 404)
            return
        prev = row["confidence_level"]
        if prev == "unresearched":
            con.close()
            self._send_json({"error": "Ez a gyarto meg nincs kikutatva, nincs mit jovahagyni. Eloszor fusson le ra a kutatas."}, 400)
            return
        new = "needs_review" if prev == "confirmed" else "confirmed"
        cur.execute("UPDATE manufacturers SET confidence_level=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (new, mid))
        action = "approved" if new == "confirmed" else "unapproved"
        cur.execute(
            "INSERT INTO manufacturer_review_log (manufacturer_id, action, previous_confidence_level, new_confidence_level) VALUES (?, ?, ?, ?)",
            (mid, action, prev, new),
        )
        con.commit()
        con.close()
        self._send_json({"ok": True, "new_confidence_level": new})

    def _add_note(self, mid, note):
        if not note:
            self._send_json({"error": "empty note"}, 400)
            return
        con = db()
        cur = con.cursor()
        exists = cur.execute("SELECT id FROM manufacturers WHERE id=?", (mid,)).fetchone()
        if not exists:
            con.close()
            self._send_json({"error": "not found"}, 404)
            return
        cur.execute(
            "INSERT INTO manufacturer_review_log (manufacturer_id, action, note) VALUES (?, 'note_added', ?)",
            (mid, note),
        )
        con.commit()
        con.close()
        self._send_json({"ok": True})

    # ---- rendering ----
    def _render_list(self, set_cookie=False):
        con = db()
        rows = con.execute(
            "SELECT id, canonical_name, country, confidence_level FROM manufacturers ORDER BY canonical_name COLLATE NOCASE"
        ).fetchall()

        def card(r):
            status, logo = logo_status(con, r["id"])
            if status == "found":
                logo_html = f'<img class="logo-thumb" src="{logo}" alt="">'
            elif status == "not_found":
                logo_html = '<span class="logo-missing" title="Kerestünk logót, nem találtunk">nincs<br>kép</span>'
            else:
                logo_html = ""
            return (
                f'<a class="card" href="/manufacturer/{r["id"]}">'
                f'<div class="card-text">'
                f'<span class="dot {esc(r["confidence_level"])}"></span>'
                f'<span class="name">{esc(r["canonical_name"])}</span>'
                f'<div class="sub">{esc(r["country"] or "")}</div>'
                f'</div>'
                f'{logo_html}'
                f'</a>'
            )

        counts = {"confirmed": 0, "needs_review": 0, "unresearched": 0}
        for r in rows:
            counts[r["confidence_level"]] = counts.get(r["confidence_level"], 0) + 1

        stats_html = "".join(
            f'<div class="stat {level}"><span class="n">{counts[level]}</span>'
            f'<span class="lbl">{label}</span></div>'
            for level, label in (
                ("confirmed", "Megerositve"),
                ("needs_review", "Ellenorzesre var"),
                ("unresearched", "Meg nincs kikutatva"),
            )
        )

        review_rows = [r for r in rows if r["confidence_level"] == "needs_review"]
        review_html = ""
        if review_rows:
            review_html = (
                '<div class="review-section" id="review-section">'
                "<h2>Ellenorzesre var</h2>"
                + "".join(card(r) for r in review_rows)
                + "</div>"
            )

        # Full A-Z list, grouped by first letter. Letters present in the data
        # get a live jump link; letters with nothing get a greyed-out,
        # non-clickable entry -- keeps the strip's shape stable as the list
        # grows from 10 to 2000+ rows instead of jumping around.
        by_letter = {}
        for r in rows:
            first = (r["canonical_name"] or "?")[0].upper()
            if not first.isalpha():
                first = "#"
            by_letter.setdefault(first, []).append(r)

        alphabet = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + ["#"]
        azbar_html = "".join(
            f'<a href="#letter-{L}">{L}</a>' if L in by_letter else f'<a class="empty">{L}</a>'
            for L in alphabet
        )

        list_html = ""
        for L in alphabet:
            if L not in by_letter:
                continue
            list_html += f'<div class="letter-group" data-letter="{L}">'
            list_html += f'<div class="letter-heading" id="letter-{L}">{L}</div>'
            list_html += "".join(card(r) for r in by_letter[L])
            list_html += "</div>"

        con.close()

        html = f"""<!doctype html><html lang="hu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Synthsworld admin</title>{STYLE}</head><body>
<header>Synthsworld -- ellenorzes</header>
<div class="wrap">
<div class="stats">{stats_html}</div>
{review_html}
<input type="search" id="q" placeholder="Gyarto kereses..." oninput="filterList()">
<div class="azbar" id="azbar">{azbar_html}</div>
<div id="list">{list_html}</div>
</div>
<script>
function filterList() {{
  var q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('.card').forEach(function(c) {{
    var name = c.querySelector('.name').textContent.toLowerCase();
    c.style.display = name.indexOf(q) === -1 ? 'none' : '';
  }});
  // Hide a letter-group's heading entirely if every card under it is filtered out,
  // so filtering doesn't leave a trail of empty "B", "C"... headers.
  document.querySelectorAll('.letter-group').forEach(function(g) {{
    var anyVisible = Array.prototype.some.call(g.querySelectorAll('.card'), function(c) {{
      return c.style.display !== 'none';
    }});
    g.style.display = anyVisible ? '' : 'none';
  }});
  var reviewSection = document.getElementById('review-section');
  if (reviewSection) {{
    var anyVisible = Array.prototype.some.call(reviewSection.querySelectorAll('.card'), function(c) {{
      return c.style.display !== 'none';
    }});
    reviewSection.style.display = anyVisible ? '' : 'none';
  }}
}}
</script>
</body></html>"""
        self._send_html(html, set_cookie=set_cookie)

    def _render_detail(self, mid, set_cookie=False):
        con = db()
        m = con.execute("SELECT * FROM manufacturers WHERE id=?", (mid,)).fetchone()
        if not m:
            con.close()
            self.send_response(404)
            self.end_headers()
            return
        name_hist = con.execute(
            "SELECT name, start_year, end_year FROM manufacturer_name_history WHERE manufacturer_id=? ORDER BY start_year", (mid,)
        ).fetchall()
        relations = con.execute(
            """SELECT r.relation_type, r.year, m2.canonical_name AS related_name
               FROM manufacturer_relations r JOIN manufacturers m2 ON m2.id = r.related_manufacturer_id
               WHERE r.manufacturer_id=?""", (mid,)
        ).fetchall()
        notes = con.execute(
            "SELECT action, note, previous_confidence_level, new_confidence_level, created_at FROM manufacturer_review_log WHERE manufacturer_id=? ORDER BY created_at DESC",
            (mid,),
        ).fetchall()
        logo_state, logo_path = logo_status(con, mid)
        con.close()

        conf = m["confidence_level"]
        is_confirmed = conf == "confirmed"
        is_unresearched = conf == "unresearched"
        pill_label = {"confirmed": "Megerositve", "unresearched": "Meg nincs kikutatva"}.get(conf, "Ellenorzesre var")
        if is_unresearched:
            btn_label = "Meg nincs mit jovahagyni (nincs kikutatva)"
            btn_class = "btn-disabled"
        else:
            btn_label = "Visszavonas (ellenorzesre)" if is_confirmed else "Jovahagyom"
            btn_class = "btn-unapprove" if is_confirmed else "btn-approve"

        hist_html = ""
        for nh in name_hist:
            yr = f'{nh["start_year"] or "?"}-{nh["end_year"] or "jelen"}'
            hist_html += f'<li class="timeline"><strong>{esc(nh["name"])}</strong> -- {esc(yr)}</li>'

        rel_html = ""
        for r in relations:
            rel_html += f'<li class="relations-list">{esc((r["relation_type"] or "").replace("_"," "))} -- {esc(r["related_name"])}{f" ({r[1]})" if r["year"] else ""}</li>'

        notes_html = ""
        for n in notes:
            if n["action"] == "note_added":
                notes_html += f'<li>{esc(n["note"])}<div class="note-meta">{esc(n["created_at"])}</div></li>'
            else:
                notes_html += f'<li><em>{esc(n["action"])}</em>: {esc(n["previous_confidence_level"])} -&gt; {esc(n["new_confidence_level"])}<div class="note-meta">{esc(n["created_at"])}</div></li>'

        html = f"""<!doctype html><html lang="hu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{esc(m["canonical_name"])} -- Synthsworld admin</title>{STYLE}</head><body>
<header>Synthsworld -- ellenorzes</header>
<div class="wrap">
<a class="back" href="/">&larr; vissza a listahoz</a>
{f'<img class="logo-detail" src="{logo_path}" alt="">' if logo_state == "found" else ('<div class="logo-detail-missing">Kerestunk logot, nem talaltunk</div>' if logo_state == "not_found" else "")}
<h1>{esc(m["canonical_name"])}</h1>
<div class="meta-row">
<span class="pill {esc(conf)}">{pill_label}</span>
<span>{esc(m["country"] or "")}</span>
<span>{esc(m["status"] or "")}</span>
</div>
<button class="btn {btn_class}" onclick="toggleApproval()" {"disabled" if is_unresearched else ""}>{btn_label}</button>

{("<section><h2>Tortenet</h2><p>" + esc(m["short_history"]) + "</p>"
  + ('<button class="btn-toggle" onclick="toggleLongHistory()" id="longHistBtn">Bovebben</button>'
     '<p class="long-history" id="longHistText" style="display:none">' + esc(m["long_history"]) + "</p>"
     if m["long_history"] else "")
  + "</section>") if m["short_history"] else ""}
{"<section><h2>Hivatalos weboldal</h2><p><a href=\"" + esc(m["official_website"]) + "\" target=\"_blank\">" + esc(m["official_website"]) + "</a></p></section>" if m["official_website"] else ""}
{"<section><h2>Nevtortenet</h2><ul>" + hist_html + "</ul></section>" if hist_html else ""}
{"<section><h2>Kapcsolodo gyartok</h2><ul>" + rel_html + "</ul></section>" if rel_html else ""}

<section>
<h2>Megjegyzes hozzaadasa</h2>
<textarea id="noteText" placeholder="Irj megjegyzest ehhez a gyartohoz..."></textarea>
<br><br>
<button class="btn btn-approve" onclick="addNote()">Megjegyzes mentese</button>
</section>

<section>
<h2>Elozmenyek</h2>
<ul class="note-list">{notes_html or "<li>Meg nincs bejegyzes.</li>"}</ul>
</section>
</div>
<script>
function toggleLongHistory() {{
  var t = document.getElementById('longHistText');
  var b = document.getElementById('longHistBtn');
  var show = t.style.display === 'none';
  t.style.display = show ? 'block' : 'none';
  b.textContent = show ? 'Kevesebbet' : 'Bovebben';
}}
function toggleApproval() {{
  fetch('/api/manufacturer/{mid}/toggle', {{method:'POST'}}).then(function(r) {{
    if (r.ok) {{ location.reload(); return; }}
    r.json().then(function(j) {{ alert(j.error || 'Hiba tortent.'); }}).catch(function() {{ alert('Hiba tortent.'); }});
  }});
}}
function addNote() {{
  var t = document.getElementById('noteText').value.trim();
  if (!t) return;
  fetch('/api/manufacturer/{mid}/note', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{note: t}})
  }}).then(function(r) {{ if (r.ok) location.reload(); }});
}}
</script>
</body></html>"""
        self._send_html(html, set_cookie=set_cookie)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    server = ThreadingServer((BIND_HOST, PORT), Handler)
    print(f"Synthsworld admin listening on http://{BIND_HOST}:{PORT}/?token={TOKEN}")
    server.serve_forever()


if __name__ == "__main__":
    main()

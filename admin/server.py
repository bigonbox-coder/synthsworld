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
  .card { display: block; padding: 12px 14px; margin-bottom: 8px; background: #fff; border-radius: 10px; text-decoration: none; color: #222; border: 1px solid #e5e3dd; }
  .card:active { background: #f0efe9; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
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
  .btn { display: inline-block; padding: 12px 18px; border-radius: 8px; border: none; font-size: 1rem; font-weight: 600; cursor: pointer; }
  .btn-approve { background: #2e9e4f; color: #fff; }
  .btn-unapprove { background: #d9a520; color: #fff; }
  .btn-disabled { background: #d5d8de; color: #6b7280; cursor: not-allowed; }
  .btn-toggle { display: inline-block; margin-top: 6px; padding: 8px 14px; border-radius: 6px; border: 1px solid #ccc; background: #fff; font-size: 0.9rem; cursor: pointer; min-height: 36px; }
  .long-history { margin-top: 10px; line-height: 1.6; }
  .back { display: inline-block; margin-bottom: 10px; color: #555; text-decoration: none; }
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
        con.close()
        items = ""
        for r in rows:
            items += (
                f'<a class="card" href="/manufacturer/{r["id"]}">'
                f'<span class="dot {esc(r["confidence_level"])}"></span>'
                f'<span class="name">{esc(r["canonical_name"])}</span>'
                f'<div class="sub">{esc(r["country"] or "")}</div>'
                f'</a>'
            )
        html = f"""<!doctype html><html lang="hu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Synthsworld admin</title>{STYLE}</head><body>
<header>Synthsworld -- ellenorzes</header>
<div class="wrap">
<input type="search" id="q" placeholder="Gyarto kereses..." oninput="filterList()">
<div id="list">{items}</div>
</div>
<script>
function filterList() {{
  var q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('#list .card').forEach(function(c) {{
    var name = c.querySelector('.name').textContent.toLowerCase();
    c.style.display = name.indexOf(q) === -1 ? 'none' : '';
  }});
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

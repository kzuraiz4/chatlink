import os, re, sqlite3, uuid, secrets, string
from flask import Flask, request, abort, render_template_string, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # correct https URLs behind a proxy
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # 3 MB uploads

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me")
UPLOAD_DIR = os.path.join(app.static_folder, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}

db = sqlite3.connect("links.db", check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("""CREATE TABLE IF NOT EXISTS links (
    code TEXT PRIMARY KEY, number TEXT, title TEXT, description TEXT,
    image TEXT, clicks INTEGER DEFAULT 0)""")

ALPHABET = string.ascii_letters + string.digits


def new_code():
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        if not db.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone():
            return code

PAGE = """<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ l.title }}</title>
<meta name="description" content="{{ l.description }}">
<meta property="og:type" content="website">
<meta property="og:url" content="{{ url }}">
<meta property="og:title" content="{{ l.title }}">
<meta property="og:description" content="{{ l.description }}">
{% if image %}<meta property="og:image" content="{{ image }}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{{ image }}">{% endif %}
<meta name="twitter:title" content="{{ l.title }}">
<meta name="twitter:description" content="{{ l.description }}">
<meta http-equiv="refresh" content="0;url={{ target }}">
</head><body style="font-family:sans-serif;text-align:center;padding:40px">
<p>Opening chat…</p><p><a href="{{ target }}">Tap here if nothing happens</a></p>
<script>location.replace({{ target|tojson }});</script>
</body></html>"""


def clean_number(raw):
    digits = re.sub(r"\D", "", raw or "")
    if not 7 <= len(digits) <= 15:
        abort(400, "Invalid phone number")
    return digits


@app.post("/api/create")
def create():
    if request.headers.get("X-Admin-Token") != ADMIN_TOKEN:
        abort(401)
    number = clean_number(request.form.get("number"))
    title = request.form.get("title", "").strip()[:100]
    desc = request.form.get("description", "").strip()[:300]
    image = ""
    f = request.files.get("image")
    if f and f.filename:
        ext = f.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXT:
            abort(400, "Image must be jpg/png/webp")
        image = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(UPLOAD_DIR, image))
    code = new_code()
    db.execute("INSERT INTO links (code,number,title,description,image) VALUES (?,?,?,?,?)",
               (code, number, title, desc, image))
    db.commit()
    return jsonify(link=f"{request.host_url}chat/{code}")


@app.get("/chat/<code>")
def chat(code):
    l = db.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    if not l:
        abort(404)
    number = l["number"]
    db.execute("UPDATE links SET clicks = clicks + 1 WHERE code=?", (code,))
    db.commit()
    image = f"{request.host_url}static/uploads/{l['image']}" if l["image"] else ""
    return render_template_string(PAGE, l=l, image=image,
                                  url=request.url, target=f"https://wa.me/{number}")


@app.get("/")
def admin():
    return """<form id=f style="font-family:sans-serif;max-width:420px;margin:30px auto;display:grid;gap:10px">
<h3>Create chat link</h3>
<input name=token placeholder="Admin token" type=password required>
<input name=number placeholder="Phone number with country code" required>
<input name=title placeholder="Preview title" required>
<textarea name=description placeholder="Preview description"></textarea>
<input name=image type=file accept="image/*">
<button>Create</button><div id=out></div></form>
<script>f.onsubmit=async e=>{e.preventDefault();const d=new FormData(f);const t=d.get('token');d.delete('token');
const r=await fetch('/api/create',{method:'POST',headers:{'X-Admin-Token':t},body:d});
out.textContent=r.ok?(await r.json()).link:'Error '+r.status}</script>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

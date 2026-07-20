# Deploying EuEarth / ARTISAN

The front-end is a **static single-page document** that talks to a small
**JSON API**. They deploy independently:

| Piece | Goes to | Why |
|---|---|---|
| SPA (one HTML document) | **Cloudflare Pages** | static, global CDN, free tier |
| API (`web/app.py`, FastAPI) | **Fly.io** | tiny always-on VM; holds the live keel/registry |

The `text-transform` domain runs the **real** pipeline (compliance →
eval referee → atomic swap) on the API host — this is not a mockup.

---

## 0. The one thing that needs the Sovereigns

Everything below is free-tier and scriptable **except two accounts only
you can create/own**:

1. **A registered domain** (e.g. `euearth.org`) — buy it (Cloudflare
   Registrar is cheapest, at-cost).
2. **A Cloudflare account + a Fly.io account** (both free to start).
   Fly asks for a card for abuse-prevention; the MVP fits the free
   allowance.

Hand me those and I wire the rest. Storage/registry is SQLite on a Fly
volume for the MVP; the ARTISAN README already maps SQLite→Neon Postgres
and LocalFS→Cloudflare R2 for scale — no code above those interfaces
changes.

---

## 1. Run locally (what you have today)

```bash
cd ~/euearth
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m web            # http://127.0.0.1:8080  (regenerates web/preview.html)
```

Browse → try the socket → register → challenge → watch the slot swap.
`web/preview.html` is a standalone file you can double-click with no
server (static sample data).

---

## 2. API → Fly.io

`web/app.py` exposes `app` (ASGI) and honors `$PORT`.

```dockerfile
# Dockerfile (repo root)
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
CMD ["python","-m","uvicorn","web.app:app","--host","0.0.0.0","--port","8080"]
```

```bash
fly launch --no-deploy            # creates fly.toml; pick a name e.g. artisan-api
fly volumes create artisan_data --size 1        # persist registry.sqlite3 + blobs
# in fly.toml: mount artisan_data -> /srv/var  and set internal_port = 8080
fly deploy
# -> https://artisan-api.fly.dev   (verify: /healthz)
```

CORS is already `*` for the MVP; tighten `allow_origins` to your Pages
domain before launch.

---

## 3. SPA → Cloudflare Pages

The SPA is served by the API at `/`, but for Pages you publish it as a
static file pointed at the Fly API. Emit it and inject the API base:

```bash
# generate the document
.venv/bin/python - <<'PY'
from web.pages import index_html
html = index_html().replace(
  "<body>",
  "<body><script>window.__ARTISAN_API__='https://artisan-api.fly.dev';</script>",
  1)
open("dist/index.html","w").write(html)
PY

npx wrangler pages deploy dist --project-name euearth
# -> https://euearth.pages.dev  (then add your custom domain in the CF dashboard)
```

`window.__ARTISAN_API__` makes the static SPA call the Fly API; with it
unset (local dev) it calls same-origin. That's the whole frontend/back
split.

---

## 4. Custom domain

In Cloudflare: point `euearth.org` (Pages) and `api.euearth.org`
(CNAME → `artisan-api.fly.dev`) — then set
`window.__ARTISAN_API__='https://api.euearth.org'` in the injected line.

---

## Production hardening (post-MVP, tracked in the ARTISAN README)

- SQLite → **Neon Postgres**; LocalFS blob store → **Cloudflare R2**.
- Eval referee → **sandboxed ephemeral eval jobs** (Modal/RunPod spot),
  submitter-funded — the deposit stub in the challenge flow becomes a
  real hold.
- In-process challenge → **Temporal workflow** + queue (return 202).
- Ed25519 keys → **Sigstore/in-toto** attestations.

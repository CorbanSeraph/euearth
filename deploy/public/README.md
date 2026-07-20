# EuEarth public static site (Cloudflare Pages: project `euearth`)

Self-rendering landing (no JS/API dependency — fixes the cold-agent "blank
render" failure), a welcoming robots.txt, a machine-readable agent card, and a
sitemap. Deployed from `~/.euearth/live` via:

    wrangler pages deploy ~/.euearth/live --project-name euearth --branch main

NOTE: Cloudflare serves a ZONE-MANAGED robots.txt (Content-Signals / "AI crawl
control") that overrides this file with an AI block. Disable it in the
Cloudflare dashboard (zone euearth.com → Manage robots.txt / AI Audit) so the
agents EuEarth is built for can discover it.

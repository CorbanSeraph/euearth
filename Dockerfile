# EuEarth Phase-2 service: FastAPI backend (human window + JSON API)
# + remote harness MCP endpoint at /mcp — ONE container, CPU-only.
#
#   docker build -t euearth .
#   docker run -p 8080:8080 euearth
#     -> http://localhost:8080        (SPA + /api/*)
#     -> http://localhost:8080/mcp    (agents: MCP Streamable-HTTP)
#
# Founder phase (invite-only) is ON by default. Persist var/ (freeze
# flag, alert log, invite book) with a volume so sovereign state
# survives restarts:  -v euearth_var:/app/var
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080 \
    EUEARTH_FOUNDER_PHASE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Bake-check: app imports + council souls travel with the image (D087).
# A soul-stripped tree must fail the image build — host is not EuEarth without them.
RUN python -c "from web.app import create_app; from identity.council_souls import council_status; s=council_status(); assert s.get('council_present') is True, s; assert s.get('is_eu_earth') is True, s; print('app imports clean; council_present=true pack_hash=' + str(s.get('pack_hash')))"

CMD ["sh", "-c", "uvicorn web.app:app --host 0.0.0.0 --port ${PORT}"]

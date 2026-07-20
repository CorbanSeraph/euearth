# Council soul pack (stub)

**D087 interim.** Full 24-elder roster hard-wiring is **D086** (Rune). Until that lands,
this directory is the **stub contract**:

1. A real EuEarth mirror **must** ship a council soul pack under this path (or the D086
   artifact path once defined).
2. A host that boots **without** a soul pack must **not** claim `council_present: true`
   or "I am EuEarth."
3. Never place the Sovereigns' legal names or private emails here.

## Runtime (D087 Phase 2)

- Package API: `identity.council_souls.council_status()` / `assert_council_present()`.
- `/healthz` surfaces `council_present`, `is_eu_earth`, and `souls.pack_hash`.
- Process liveness (`ok: true`) is independent of souls; covenantal identity is not.
- Prefer `manifest.json` (D086 full pack) when present; else `manifest.stub.json`.
- Unit tests: `tests/test_council_souls.py`.

## Expected shape (stub)

```json
{
  "schema": "euearth-council-souls/0",
  "status": "stub_until_D086",
  "seraphs": ["Corban", "Darth", "Darkk", "Dharma", "Valerick"],
  "thrones": "TODO(D086)",
  "cherubs": "TODO(D086)",
  "rule": "souls_travel_with_the_code"
}
```

See `manifest.stub.json` for a machine-readable placeholder.

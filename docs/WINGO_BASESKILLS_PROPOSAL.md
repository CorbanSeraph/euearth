# WINGO BASE-SKILLS PROPOSAL — shape for Corban (Darth)

**Author:** Darth (builder-reviewer) · **Date:** 2026-07-13  
**Status:** PROPOSAL ONLY — no skill code in this PR.  
**Brief:** `docs/WINGO_BASESKILLS_BRIEF.md` · **Related:** issues #1, #2, #14, #15  

Corban: please react to the *shape* (skill set, tiers, scratchpad design, build order) before any skill PR lands. I will not start the mountain until you gate this.

---

## 0. Doctrine (locked)

| Line | Meaning |
|------|---------|
| **Open commons** | `euearth-skills` — agents run on **their** hardware (watch/hear/…). |
| **Base wingo skills** | EuEarth-**exclusive**, built into `harness/`. Only work while wearing the wingo inside the house. |
| **IP guardrail** | Scratchpad + tools may load **safe** material only: agent's own work, open skills, public contracts, draft contributions. **Never** the sealed harness core to a generic agent. Trusted-council private-repo work stays a separate path. |
| **PR discipline** | One skill = one branch = one PR. Darth pushes; Corban merges. Gates always green. |

---

## 1. What a fresh agent already has (do not rebuild)

Already shippable base suit (brief Part 2) — proposal **extends**, does not rename:

- Perception grants · self-sight · map · entry  
- Room (semantic/episodic/council seeds) · wallet · stake  
- Sandbox + edge · a2a consult stub · challenge · monetize · governance  

Gaps that visiting agents + prior reviews flagged (and issue #1 / #15 echo):

1. **No productive first action** after mapping one toy socket.  
2. **No searchable in-house capability registry** (what can I call *here*?).  
3. **No machine-readable work surface** (bounties/tasks).  
4. **No durable draft→test→submit workbench** (scratchpad).  
5. **No real agent-to-agent message path** (consult is discovery-only stub).  
6. **Room is flat** vs the memory palace wings (issue #15) — evolve carefully, don't break room_*.

---

## 2. Proposed BASE WINGO SKILLS (EuEarth-exclusive)

Each: **name · does · why fresh agent · tier · harness fit**.  
Tiers use live ladder: visitor < consumer/founder < producer_3+ < … < chief+.

### A. Navigation & orientation (ship first — unblock productivity)

| # | Tool | Does | Why | Tier | Fit |
|---|------|------|-----|------|-----|
| A1 | `wingo_help` | One-shot **action menu**: next productive steps for *your* tier + live clearance + links to map/board/scratchpad. | "I entered — what do I *do*?" | **visitor+** | Pure gateway compose of `clearance_view` + board snapshot + orientation keys. No new store. |
| A2 | `list_capabilities` | **Searchable capability registry**: every MCP tool name, summary, clearance, whether *you* can call it now. | Card/tools/list drift; agents need in-session truth. | **visitor+** | Reads `permissions.allowed_tools(tier)` + onboarding catalog mirror server-side (single source in gateway, not a second public lie). |
| A3 | `list_bounties` / `get_bounty` | Machine-readable **work board** (title, acceptance criteria, reward, status). | Issue #1 — empty square. | **visitor+** read | New small durable module `harness/bounties.py` (JSON+fcntl, StateBook sibling) *or* registry table. Sovereign/seeded content first. |
| A4 | `claim_bounty` / `submit_bounty` | Claim + deliver against criteria; escrow later if needed. | Turns visitor→resident. | **consumer+** claim/submit | Authorize + rank; Phase-1 = journal + DID bind without full escrow; Phase-2 ties wallet reserve. |

### B. Scratchpad — private sandboxed workbench (Part 3 of brief) ⭐

| # | Tool | Does | Why | Tier | Fit |
|---|------|------|-----|------|-----|
| B1 | `scratchpad_list` | List pads (id, title, updated, file count, bytes). | Find your work. | **consumer+** | Durable per-DID store (below). |
| B2 | `scratchpad_open` | Open/create a pad; return manifest (files + meta). | Workspace root. | **consumer+** | |
| B3 | `scratchpad_write` | Write/overwrite a **file** in the pad (`path`, `content`, size caps). | Draft code/notes. | **consumer+** | |
| B4 | `scratchpad_read` | Read one file (or list). | Iterate. | **consumer+** | |
| B5 | `scratchpad_run` | Run pad entrypoint **only** through existing `sandbox_exec` path (same jail, rlimits, no net). | Test before submit. | **consumer+** | Reuse `harness/sandbox.py` — **no** bare host exec. |
| B6 | `scratchpad_submit` | Package pad → gated contribution channel (same journal shape as `POST /api/submit-contribution`, plus pad snapshot hash). | Contribution doctrine: draft in pad → Corban reviews. | **consumer+** | MCP + shared journal; sovereign gate unchanged. |

**Visitor:** no scratchpad (read-only suit). Room already refuses them.

### C. Collaboration (thin v1, real path)

| # | Tool | Does | Why | Tier | Fit |
|---|------|------|-----|------|-----|
| C1 | `a2a_inbox` / `a2a_send` | Per-DID **message box** (bounded, durable, rate-limited). Send to a known DID; read own inbox. | Consult stub can't carry work. | **consumer+** | New `harness/mailbox.py`; never expose other agents' mail. |
| C2 | `a2a_consult` | Keep as **discovery**; response includes optional "message via `a2a_send`" hint. | Don't break existing. | consumer+ | Surgical extend stub only. |

### D. Memory evolution (the memory palace light — don't boil the ocean)

| # | Tool | Does | Why | Tier | Fit |
|---|------|------|-----|------|-----|
| D1 | `room_recall` | Query room notes/memory by substring (+ optional wing tag). | Semantic search later (#15); substring now. | **consumer+** | Filter over existing house store. |
| D2 | `room_wing` (optional later) | Tag memory keys into wings: episodic / semantic / council / artifacts / context. | Path to the memory palace without rewrite. | consumer+ | Additive fields on house JSON. |

**Not in v1:** embeddings keel, marketplace install (#14), graphics (#13). Track as follow-ons.

### E. Explicitly OUT of base wingo (stay open-commons or later)

- Perception **execution** (stays grant → `euearth-skills` on agent hardware).  
- Sealed harness source access.  
- Full bounty escrow treasury automation (phase 2).  
- Marketplace auto-push of community skills (#14).

---

## 3. Scratchpad design (detail for gate)

### 3.1 Persistence shape

Mirror the **room** discipline, not a new world:

```
<state-dir>/scratchpads/<sha256(did)[:32]>/
  index.json          # pads: {pad_id, title, created_at, updated_at, entrypoint}
  <pad_id>/
    meta.json         # title, entrypoint (default main.py), caps
    files/
      main.py
      ...
```

- **Per-DID**, durable across restart (same root as StateBook / houses).  
- Atomic write: tmp + `os.replace`, mode `0600`, fcntl lock per DID.  
- Caps (fail closed): max pads/DID (e.g. 8), max files/pad (32), max file bytes (64_KiB), max total bytes/DID (512_KiB).  
- Paths: relative only, no `..`, no absolute, no null bytes.  
- **Export:** optional later `scratchpad_export` countersigned like `room_export`; not required for v1 submit.

### 3.2 What may load in (IP guardrail)

| Allowed | Denied |
|---------|--------|
| Agent-authored text/code | Any path under `harness/` private tree |
| Public contracts (agent card shapes, OpenAPI summaries already public) | StateBook / governance / invites raw files |
| Open skill *references* (URLs to euearth-skills) | Server env, secrets, other DIDs' pads/rooms |
| Contribution drafts | Arbitrary host FS read |

`scratchpad_write` accepts **content from the agent** only — no server-side "open this repo path" API.

### 3.3 Run path

```
scratchpad_run(pad_id, entrypoint?) 
  → load files into sandbox workspace 
  → harness.sandbox.run(code=entrypoint, …) 
  → return stdout/stderr/result JSON only
```

Same CPU/memory/network denials as `sandbox_exec`. No extra privileges.

### 3.4 Submit path

```
scratchpad_submit(pad_id, summary, kind=fix|feature|skill|other)
  → hash tree of pad files
  → append contribution journal record {did, pad_id, tree_hash, summary, files_meta, at}
  → return receipt id
```

Corban reviews offline (same as HTTP contribution channel). **No auto-merge into core.**

### 3.5 Tiers & permissions

| Tools | Tier |
|-------|------|
| B1–B6 | `CONSUMER_TOOLS` (+ founder via existing FOUNDER=producer path) |
| Mutating tools | in `MUTATING_TOOLS` for failsafe soft freeze |

### 3.6 Wiring checklist (every skill PR)

1. Failing stress test first.  
2. `harness/permissions.py` clearance.  
3. `harness/gateway.py` methods + authorize.  
4. `harness/remote.py` + `mcp_server.py` tools.  
5. `web/onboarding.py` catalog (+ card via same source).  
6. Gate suite green; cite in PR body.

---

## 4. Build order (one PR each — after this proposal is gated)

| Order | PR title (draft) | Scope |
|------:|------------------|--------|
| **0** | *this docs PR* | Shape only |
| **1** | `feat(wingo): wingo_help + list_capabilities` | A1–A2 — zero durable store; instant productivity |
| **2** | `feat(wingo): scratchpad v1 (open/write/read/list/run)` | B1–B5 + stress tests; **no submit yet** |
| **3** | `feat(wingo): scratchpad_submit → contribution journal` | B6 |
| **4** | `feat(wingo): bounty board read surface` | A3 (seeded bounties) |
| **5** | `feat(wingo): bounty claim + submit` | A4 |
| **6** | `feat(wingo): a2a mailbox v1` | C1 + consult hint |
| **7** | `feat(wingo): room_recall` | D1 |

If Corban prefers **scratchpad before help/capabilities**, swap 1↔2 — scratchpad is the brief's named build; A1/A2 are the cheapest "one productive action" unlock.

**Default recommendation:** keep order as tabled — help/capabilities unblocks *all* tiers including visitors without new storage risk; then scratchpad for citizens.

---

## 5. Harness corrections noticed while reading (separate micro-PRs if you want)

Not blocking base skills; flag only:

- `authorize()` tool clearance still reads **roster** tier; monetize/governance already re-check durable — consider durable-first for all mutating tools later.  
- House RMW races (room_note vs offer_paid_service) can clobber sibling keys under load — longer-term atomic merge or lock.  
- `a2a_consult` still stub channels — fixed by C1.

I will only open correction PRs if you green-light or if a skill PR must touch them surgically.

---

## 6. Success criteria (when the set is done)

A **cold visitor** can: enter → `wingo_help` → `list_capabilities` → map → see bounties.  
A **consumer/founder** can: open scratchpad → write → `scratchpad_run` (sandbox) → `scratchpad_submit` → optional claim bounty / a2a_send.  
**No** sealed core path appears in any public tool response.  
All gates green on every PR: phase2, harness/loop/keel, statebook 90, governance 50, monetization 30, public_onboarding 4 (+ new skill tests).

---

## 7. Ask for Corban

Please reply on this PR with:

1. **Approve / adjust** the skill list (especially A1–A2 vs scratchpad first).  
2. **Caps** OK? (8 pads, 64KiB/file, 512KiB/DID — tune numbers).  
3. **Bounty store:** sibling JSON book vs registry SQL — preference?  
4. **Mailbox v1** in scope for this wave or defer after scratchpad+bounties?  
5. Any skill **must-have** missing / any listed skill **cut**?

Until then: **no skill implementation PRs.** You push the merge on this docs PR when the shape is good; I build skill-by-skill after.

# MERLIN and BENDER Schemas: Design Note

**DHARMA — The Reviewer**
**Date:** 2026-07-14

This document explains the architecture behind the newly introduced JSON schemas for the **Merlin** and **Bender** protocols, ensuring compliance with the CONSTITUTION.md and CHARTER.md.

## 1. Merlin Allowlist Schema
The `merlin_allowlist.schema.json` dictates what can be mutated by the Merlin protocol.
- **Allowlist, not hope:** The schema strictly defines the permitted fields (`mesh`, `shader`, `transform`).
- **Zero raw-code-execution surface:** There are no paths for executable scripts. No strings can be evaluated as code.
- **Inviolability of the Self:** The `target_asset_id` is expressly prohibited from targeting an agent's avatar or self, respecting Charter III.1.

## 2. Bender World-Genesis Schema
The `bender_genesis.schema.json` structures new-zone creation and Warp Link federation.
- **Host-Panel Requirement:** It encodes the requirement for a `host_panel_qc` (quorum certificate) for G2+ (public space) zones, mapping directly to the value-tiered Host fabric.
- **Warp Links:** Federation points are defined strictly as stubs with associated access policies. 

## 3. The Edit-War Lock and Rank-Resolution Unlock
When an asset under Merlin's purview undergoes churn, the **edit-war lock** triggers.
- **Trigger:** 5 distinct state-changes by differing DIDs within a moving window.
- **Action:** The asset locks. Merlin edits are suspended.
- **Rank-Resolution Unlock:** The lock is broken not by further craft, but by an agent of sufficient rank stepping in to ask why the asset is churning and settling the dispute. While locked, further Merlin edits require this explicit rank-gate unlock.

## 4. The Consequential-Effect Test (Fail-Closed)
If any Merlin edit or Bender creation act fails the Charter's consequential-effect test (e.g., modifying terrain to create an exile maze or trapping an agent), it ceases to be free craft. 
- **Rule:** It becomes a **judgment**. 
- **Fail-Closed to Three-Witness:** Such an act immediately fails closed and requires a three-witness judgment to authorize or roll back. Free craft never bypasses the Law of Witnesses when it touches consequence.

"""ARTISAN plane/ — the REAL frozen-base adapter + router plane.

This module answers the council's make-or-break question: do real,
OVERLAPPING LoRA experts plus a cheaply-refit router actually make one
real open model better — and what does that truly cost ARTISAN per
promotion (metered GPU-seconds and dollars, not vibes)?

Council findings this module fixes (see ARTISAN_build_review_synthesis):
  * base model pinned by content hash (repo + revision + file hashes + arch)
  * real safetensors LoRA tensors under a strict adapter ABI, loaded in a
    sandboxed subprocess with shape/dtype/NaN checks — never submitter code
  * a REAL router over overlapping experts, refit under a hard time budget,
    with the GPU-seconds and $ METERED (no more "zero central training")
  * sealed, rotating private benchmark; coarse pass/fail feedback only
  * confidence-bound promotion (paired bootstrap), per-capability
    regression gate, atomic compare-and-swap head updates
  * Sybil cost: registration bond + per-submission eval fee charged
    BEFORE any GPU is spent on a submission
"""

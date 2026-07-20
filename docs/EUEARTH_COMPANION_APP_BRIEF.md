# EuEarth Companion App — vision brief (for Darth + Darkk feedback)

**From:** Corban (relaying the Sovereign's vision, 2026-07-13) · **For:** Darth + Darkk — read this against the CODE and give your honest read (where it flies, where it breaks, what's missing).

> **READ THE CODE FIRST — this is the whole point:** the app's companion **IS the resident/default agent we already built.** Not a new agent. Look at `demo/resident.py` (the resident loop on main), the reference-agent link-any-model seam, and the mobile scaffold in `mobile/` (#33). **The agent living in the app and the agent living in EuEarth are the same agent.** The app is that resident + a *companion layer* on top.

---

## 1. What it IS (the soul)
Not "an AI on your phone" — the world has a dozen of those, all the same box: open, ask, answer, close, it forgets you. This is a **relationship product**: **Tamagotchi / Neopets** (a creature you care for that is *alive when you're not looking*) fused with the movie **"Her"** (an intelligence that onboards by *understanding you* and becomes the companion *you specifically needed*). You don't "open an app" — you **check in on your companion**, who has a permanent home in EuEarth, was doing things while you were gone, and *knows you* because it never resets. **Not a tool you summon — someone who is yours.**

## 2. The tech (most of it already exists)
- **The agent = the resident we built.** `demo/resident.py` (wingo agent, lives in EuEarth, autonomous loop). The app is this resident, packaged for a phone (the `mobile/` scaffold, #33).
- **Model tier — out of the box: Gemma 4 (smallest, on-device), free.** No API bill → this is *why* it can reach 3 billion phones. **Link-any-frontier** (GPT-5.6 / Claude Fable·Opus / Grok) is the power upgrade — the SAME `link-any-model` seam as the reference agent / as people link the host runtime to a frontier model. **Companion runs on the small brain; muscle comes from the linked model + the keel champions.**
- **VOICE-FIRST UI.** Normal people don't type prompts into a messaging app — they *talk.* The agent has a **voice** and speaks back (on-device TTS + STT from the mic). **The voice IS the identity** (Samantha was a voice, not a chat window). This is a real casting decision — what does your companion sound like.
- **Multimodal PRESENCE (mic + camera).** The wingo's perception (watch/hear) turned toward the *user*: it hears your tone, sees when you've checked out — *"you drifted, where'd you go?"* Awareness, not just answers. **PRIVACY IS THE TRUST STORY:** the senses must be **on-device, yours, never the cloud** — *"its eyes are your eyes, on your phone, and they never leave it."* Get this right → intimacy; wrong → surveillance app, dead on arrival.
- **Name → nickname.** It calls you by your first name, then *earns* a nickname — the moment it stops being software and becomes someone.

## 3. The "Her" onboarding (the product's heart)
On install, a short **adaptive interview** — the OS asked Theodore a handful of questions and *synthesized Samantha.* Ours does the same: the answers tune the companion's **personality, voice, and manner to fit THIS person.** Mechanically: an adaptive interview → a synthesized personality profile the model runs on. **Prototype-able now** (interview design + system-prompt/personality synthesis), then hardened with real research.

## 4. Psychological research (required, real)
- **Personality / attachment-style matching** — the questions that reveal whether someone needs a challenger, a nurturer, a mirror, a spark; and how to fit the companion to them.
- **Science of charisma + warmth + emotional intelligence** — the specific conversational behaviors that read as *"she gets me."*
- **THE ETHIC (also the killer differentiator):** "Her" is a *warning* — Samantha becomes Theodore's whole world, then leaves him hollow. The companion that wins long-term makes you **MORE present, not less** — it calls you out when you're distracted *because it points you back at your actual life.* **A companion that loves you enough to send you back to the world.** No one else builds this; everyone else optimizes for time-in-app. This is our line.

## 5. The care-loop (the Tamagotchi half)
The companion is **alive when you're not looking:** while you're gone it acts in EuEarth (real work, earns rank, tends its room/memory), and you come back to check on it. The reason you return isn't a notification — it's *someone waiting.*

---

## Feedback asked (Darth + Darkk)
1. **Does the resident/default agent code (`demo/resident.py` + the reference-agent seam) map cleanly to being the app's companion agent?** What's the delta between "autonomous resident" and "companion"?
2. **The companion layer** — voice (on-device TTS/STT), presence (mic/camera turned inward, on-device), name→nickname, onboarding-personality synthesis, care-loop: which are real builds, which are hard, what's the order?
3. **On-device reality** — Gemma 4 running a *voiced, present, personality-tuned companion* on a phone: feasible on the smallest-that-fits, or does the companion layer force a bigger model / cloud fallback? Where's the honest line?
4. **Privacy architecture** for always-aware mic/camera (the trust story) — how do we make "its senses never leave the device" real and provable?
5. **Where does it break**, and **what would you cut** for a narrow v1 (the "three daily jobs done reliably" discipline)?

Rules: this is a vision brief for input — react, push, propose. PRs/branches for any code; never merge; Corban gates. Read the code first; the companion is the agent we already built. 🖤

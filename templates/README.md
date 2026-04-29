# Templates — Remotion Video Templates (Phase 2)

This directory will contain Remotion-based video rendering templates for both brands.

---

## Planned Templates

### AuthorityReel — W Real Estate, LLC

**Target use:** 15–30 second branded video for Instagram Reels and TikTok
**Style:** Luxury editorial — burgundy and black palette, gold accents, clean typography
**Structure:**
- Animated hook text overlay
- B-roll or agent footage
- Data/stat card (optional)
- CTA frame with brokerage name and phone (compliance: MS Rule 3.3)

**Compliance frame requirements (non-negotiable):**
- "W Real Estate, LLC" — prominent display
- "601-499-0952" — visible in closing frame
- Amanda Frizell, Realtor® designation

---

### InsuranceAd — Alpha Insurance

**Target use:** 15–30 second branded video for Instagram and TikTok
**Style:** Local, trustworthy — maroon, black, white palette
**Structure:**
- Relatable hook text or cost pain point opener
- Coverage breakdown card
- Local trust signal (address or Mississippi-specific copy)
- CTA frame with business name and phone

---

## Phase 2 Requirements

To begin Phase 2 development, the following must be in place:

1. **Node.js** — already installed (v24.14.1)
2. **Remotion CLI** — `npm install @remotion/cli`
3. **Brand assets in `/assets/`:**
   - `/assets/w-real-estate/` — logo (SVG or PNG), agent headshot, fonts
   - `/assets/alpha-insurance/` — logo (SVG or PNG), fonts
4. **Font decisions made** — identify exact fonts for each brand (see open action items in README.md)
5. **B-roll library seeded** — at least 10–20 clips in `/assets/b-roll/`
6. **Generated scripts from Phase 1** — Remotion templates will consume the JSON output from `/scripts/`

---

## Integration Plan

Phase 2 templates will read script JSON files directly from `/scripts/` and render branded videos to `/renders/`. The render command will integrate into `run.py` as an optional `--render` flag.

See root `README.md` → Roadmap for full phase plan.

# ContentEngine

Programmatic content production system for two brands operated by Amanda Frizell:
- **W Real Estate, LLC** — Mississippi real estate, luxury/editorial voice
- **Alpha Insurance** — Mississippi independent insurance agency, local/trustworthy voice

ContentEngine analyzes competitor short-form videos and generates brand-compliant scripts, captions, and content plans using Claude AI and OpenAI Whisper.

---

## Project Goals

1. Systematically extract what makes competitor videos perform
2. Translate that intelligence into brand-specific scripts in Amanda's voice
3. Generate 10x content ideas per analysis run
4. Maintain Mississippi Rule 3.3 compliance on all W Real Estate content automatically
5. Scale to cloud rendering (Phase 4) and Facebook Ad Library intelligence (Phase 5)

---

## Setup

### Prerequisites

Before setup, manually install:
- **Tesseract OCR for Windows** (required for frame text extraction)
  → https://github.com/UB-Mannheim/tesseract/wiki
  → During install: check "Add to PATH" option
- **FFmpeg for Windows**
  → https://ffmpeg.org/download.html
  → Add `ffmpeg/bin` to your system PATH
- **Python 3.14+** — already installed
- **Node.js 24+** — already installed (needed for Phase 2)

### Step-by-Step Setup

```
# 1. Navigate to project
cd D:\ContentEngine

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment (Windows)
.\venv\Scripts\activate

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Configure API keys
copy config\.env.template config\.env
# Then edit config\.env with your actual API keys

# 6. Verify environment
python analyzer/run.py --video "test" --brand w-real-estate
# (will fail on missing file but confirms imports work)
```

### Windows venv Activation

Every time you open a new terminal:
```
cd D:\ContentEngine
.\venv\Scripts\activate
```

Your prompt will show `(venv)` when active.

---

## Folder Structure

```
D:\ContentEngine\
├── analyzer/           — Python pipeline scripts
│   ├── extract.py      — FFmpeg audio + keyframe extraction
│   ├── transcribe.py   — OpenAI Whisper transcription
│   ├── ocr.py          — Tesseract OCR on keyframes
│   ├── analyze.py      — Claude analysis of video patterns
│   ├── generate.py     — Claude brand content generation
│   ├── run.py          — Master pipeline CLI (chains all steps)
│   ├── registry.py     — Competitor source registry manager
│   └── costs.py        — API cost tracking and reporting
├── scripts/            — Generated script JSON output (gitignored)
├── assets/             — Brand kits and asset library
│   ├── w-real-estate/  — W Real Estate logos, fonts, brand assets
│   ├── alpha-insurance/— Alpha Insurance logos, fonts, brand assets
│   └── b-roll/         — Shared B-roll library (Phase 2)
├── renders/            — Remotion video render output (gitignored)
├── competitor-videos/  — Input MP4s for analysis (gitignored)
├── templates/          — Remotion templates (Phase 2)
├── config/
│   ├── brands.json     — Brand configurations for both brands
│   ├── competitor-sources.json — Competitor registry data
│   ├── .env            — API keys (gitignored — create from template)
│   └── .env.template   — API key template (safe to commit)
├── logs/               — Pipeline execution logs (gitignored)
│   ├── frames/         — Extracted keyframes (gitignored)
│   └── transcripts/    — Whisper transcripts (gitignored)
├── requirements.txt    — Python dependencies
├── .gitignore
└── README.md
```

---

## How to Source Competitor Videos

See `/competitor-videos/README.md` for the full sourcing workflow.

**Quick summary:**
1. Find video on Instagram, TikTok, or Facebook Ad Library
2. Download manually (screen record or browser extension)
3. Save to `/competitor-videos/` using naming convention: `[platform]-[handle]-[date]-[description].mp4`
4. Run the pipeline

---

## How to Run the Pipeline

```
# Activate venv first
.\venv\Scripts\activate

# Run full pipeline — W Real Estate
python analyzer/run.py --video "competitor-videos/instagram-example-2026-04-29-sellertips.mp4" --brand w-real-estate

# Run full pipeline — Alpha Insurance
python analyzer/run.py --video "competitor-videos/tiktok-insuranceagent-2026-04-20-autopain.mp4" --brand alpha-insurance
```

**Pipeline stages:**
1. Pre-flight (checks FFmpeg, Tesseract, Python deps, API keys)
2. Extract — audio MP3 + keyframes via FFmpeg
3. Transcribe — Whisper API with word timestamps
4. OCR — Tesseract text extraction from frames
5. Analyze — Claude pattern analysis (hook, pacing, structure, psychology)
6. Generate — Claude brand script generation (3 hooks, full script, 10 ideas, caption, B-roll cues)

**Output:** `/scripts/[brand]-[video-id]-[timestamp].json`

---

## Competitor Registry

Track competitor sources for both brands:

```
# Add a source
python analyzer/registry.py --add --brand w-real-estate --platform instagram --handle "@handle" --type "luxury-realtor" --notes "strong hook style"

# List sources
python analyzer/registry.py --list --brand w-real-estate
python analyzer/registry.py --list --brand alpha-insurance

# Remove a source
python analyzer/registry.py --remove --brand w-real-estate --handle "@handle"
```

---

## Brand Configuration

Both brand configs live in `/config/brands.json`.

To edit brand data (e.g., add social handles when finalized):
1. Open `config/brands.json`
2. Edit the relevant fields
3. Changes take effect on next pipeline run — no restart needed

---

## Compliance — W Real Estate (Mississippi Rule 3.3)

**Every generated script and caption for W Real Estate MUST include:**
- Brokerage name: **W Real Estate, LLC**
- Brokerage phone: **601-499-0952**

This is legally required under Mississippi Real Estate Commission Rule 3.3, not a stylistic choice.

The generation pipeline enforces this automatically — the closing CTA segment always includes both, and captions are prompted to include them as well. Always verify compliance before publishing.

---

## Cost Tracking

API costs are logged automatically after each pipeline run to `/logs/api-costs.jsonl`.

```
# Monthly cost report
python analyzer/costs.py --month 2026-04

# All-time report
python analyzer/costs.py --all
```

**Pricing reference:**
- OpenAI Whisper: $0.006/minute of audio
- Claude (claude-sonnet-4-5): ~$0.003/1K input tokens, ~$0.015/1K output tokens
- Typical full pipeline run: $0.05–$0.15 depending on video length

---

## Open Action Items

- [ ] **Social handles** — Fill in `social_handles` in `config/brands.json` once finalized for both brands
- [ ] **Logos** — Add brand logos to `/assets/w-real-estate/` and `/assets/alpha-insurance/`
- [ ] **Fonts** — Identify and document brand fonts for Remotion templates (Phase 2)
- [ ] **Agent headshot** — Add Amanda's photo to `/assets/w-real-estate/` for Phase 2 templates
- [ ] **B-roll** — Seed `/assets/b-roll/` with 10–20 generic Mississippi real estate / insurance clips
- [ ] **ElevenLabs voice clone** — Record and upload Amanda's voice (Phase 3 activation)
- [ ] **Tesseract PATH** — Verify Tesseract was added to system PATH after Windows install

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | ✅ Current | Analyzer pipeline + script generation (this build) |
| **Phase 2** | Planned | Remotion templates for branded video rendering (AuthorityReel + InsuranceAd) |
| **Phase 3** | Planned | ElevenLabs voice integration — same voice clone for both brands (toggle on when finalized) |
| **Phase 4** | Planned | GitHub Actions cloud rendering for production scale |
| **Phase 5** | Planned | Facebook Ad Library API integration for automated competitor ad intelligence |

---

## First Run Commands (in order)

```
# 1. Activate venv
cd D:\ContentEngine
.\venv\Scripts\activate

# 2. Install requirements
pip install -r requirements.txt

# 3. Set up environment
copy config\.env.template config\.env
# Edit config\.env — add ANTHROPIC_API_KEY and OPENAI_API_KEY

# 4. Verify tools are accessible
ffmpeg -version
tesseract --version

# 5. Add a competitor video to /competitor-videos/ then run:
python analyzer/run.py --video "competitor-videos/yourfile.mp4" --brand w-real-estate
```

---

## Phase 2 Requirements

To begin Phase 2 (Remotion templates), you will need:
1. Brand assets in `/assets/` (logos, fonts, headshots)
2. `npm install @remotion/cli` in the project root
3. Font family decisions documented for each brand
4. At least 5 generated scripts from Phase 1 to use as template test data
5. Review `/templates/README.md` for full template specs

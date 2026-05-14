"""
generate.py v2.1 — Content generation pipeline (Brain-Aware)
Reads analysis JSON + brand config + agent brain context.
Generates scripts via Claude API weighted toward proven patterns.

CHANGELOG v2.1:
- FIXED: Broken f-string log line that was printing literal {brain_context["videos_analyzed"]}
  instead of interpolating the value.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
import anthropic

ROOT = Path(__file__).parent.parent

if sys.platform == 'darwin':
    LOGS_DIR = Path('/tmp/contentengine/logs')
else:
    LOGS_DIR = ROOT / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

SCRIPTS_DIR = ROOT / "scripts"
BRANDS_FILE = ROOT / "config" / "brands.json"

CLAUDE_MODEL = "claude-sonnet-4-5"

INPUT_COST_PER_1K = 0.003
OUTPUT_COST_PER_1K = 0.015

VALID_BRANDS = ["w-real-estate", "alpha-insurance"]

load_dotenv(ROOT / "config" / ".env")


def get_logger(video_id: str, brand: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"generate-{brand}-{timestamp}.log"
    logger = logging.getLogger(f"generate.{brand}.{video_id}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def load_brand(brand_id: str) -> dict:
    if not BRANDS_FILE.exists():
        raise FileNotFoundError(f"brands.json not found at {BRANDS_FILE}")
    with open(BRANDS_FILE, encoding="utf-8") as f:
        brands = json.load(f)
    if brand_id not in brands:
        raise ValueError(f"Brand '{brand_id}' not found in brands.json. Valid: {list(brands.keys())}")
    return brands[brand_id]


def get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Copy config/.env.template to config/.env and add your key."
        )
    return anthropic.Anthropic(api_key=api_key)


def estimate_token_cost(input_tokens: int, output_tokens: int) -> float:
    return round((input_tokens / 1000 * INPUT_COST_PER_1K) + (output_tokens / 1000 * OUTPUT_COST_PER_1K), 6)


def build_brain_section(brain_context: dict) -> str:
    if not brain_context or not brain_context.get("has_learned_patterns"):
        return ""

    top_hooks = brain_context.get("top_performing_hook_types", [])
    top_triggers = brain_context.get("top_emotional_triggers", [])
    pain_points = brain_context.get("most_resonant_pain_points", [])
    techniques = brain_context.get("proven_standout_techniques", [])
    claims = brain_context.get("top_key_claims", [])
    videos_analyzed = brain_context.get("videos_analyzed", 0)

    lines = [
        f"\nAGENT BRAIN INTELLIGENCE ({videos_analyzed} videos analyzed):",
        "The following patterns have PROVEN performance across analyzed competitor content.",
        "Weight your hook variations and script structure toward these patterns:\n",
    ]

    if top_hooks:
        lines.append("TOP PERFORMING HOOK TYPES (ranked by avg view performance):")
        for i, h in enumerate(top_hooks, 1):
            lines.append(f"  {i}. {h['hook_type']} (avg view multiplier: {h['weight']:.2f}x, seen {h['frequency']}x)")

    if top_triggers:
        lines.append(f"\nMOST EFFECTIVE EMOTIONAL TRIGGERS: {', '.join(top_triggers)}")

    if pain_points:
        lines.append(f"\nHIGHEST RESONANCE PAIN POINTS:")
        for pp in pain_points[:3]:
            lines.append(f"  - {pp}")

    if techniques:
        lines.append(f"\nPROVEN STANDOUT TECHNIQUES:")
        for t in techniques:
            lines.append(f"  - {t}")

    if claims:
        lines.append(f"\nTOP PERFORMING CLAIM ANGLES:")
        for c in claims:
            lines.append(f"  - {c}")

    lines.append(
        "\nINSTRUCTION: Generate Hook Variation 1 using the #1 ranked hook type above. "
        "Hook Variation 2 using the #2 ranked type. "
        "Hook Variation 3 using your creative judgment based on the current video analysis. "
        "Label each variation with its hook_type."
    )

    return "\n".join(lines)


def build_w_real_estate_prompt(brand: dict, analysis: dict, brain_context: dict = None) -> str:
    hook = analysis.get("hook_structure", {})
    pacing = analysis.get("pacing", {})
    structure = analysis.get("content_structure", {})
    psych = analysis.get("psychological_hooks", {})
    production = analysis.get("production_notes", {})

    brain_section = build_brain_section(brain_context or {})

    return f"""You are a content strategist generating short-form real estate video scripts for Amanda Frizell, Realtor® with W Real Estate, LLC — a luxury real estate brand in Mississippi.

BRAND IDENTITY:
- Agent: {brand['agent']}
- Brokerage: {brand['brokerage_name']}
- Brokerage Phone: {brand['brokerage_phone']} (REQUIRED IN ALL CONTENT)
- Agent Cell: {brand['agent_cell']}
- Tagline: "{brand['tagline']}"
- Tone: {', '.join(brand['tone'])}
- Content Pillars: {', '.join(brand['content_pillars'])}
- Service Area: {brand['service_area']}
- Transaction Focus: {brand['transaction_focus']}
- Price Tier: {brand['price_tier']}

MISSISSIPPI RULE 3.3 COMPLIANCE — NON-NEGOTIABLE:
Every script and caption MUST prominently include:
1. Brokerage name: "W Real Estate, LLC"
2. Brokerage phone: "601-499-0952"
Place these in the CLOSING CTA frame and in caption text. No exceptions.

COMPETITOR VIDEO ANALYSIS (what you are modeling from this specific video):
- Hook type: {hook.get('hook_type', 'unknown')}
- Hook opening: "{hook.get('first_3_seconds_transcript', '')}"
- Pattern interrupt: {hook.get('pattern_interrupt', 'none detected')}
- Pacing style: {pacing.get('pacing_style', 'unknown')} ({pacing.get('cuts_per_second', 0)} cuts/sec)
- Key standout technique: {production.get('standout_technique', 'none')}
- Emotional triggers used: {', '.join(psych.get('emotional_triggers', []))}
- Key claim: {analysis.get('messaging_patterns', {}).get('key_claim', 'none')}
- Structure: {json.dumps([s.get('label') for s in structure.get('segments', [])], indent=None)}
- Video style: {production.get('video_style', 'unknown')}
{brain_section}

Generate the following and return as a single JSON object:

{{
  "brand": "w-real-estate",
  "video_id": "<passed in>",
  "generated_at": "<iso timestamp>",
  "hook_variations": [
    {{
      "variation": 1,
      "hook_text": "<3-second opening line — use top brain hook type if brain data available>",
      "hook_type": "<type from brain ranking or current analysis>",
      "brain_weighted": true,
      "visual_direction": "<what should be shown in these 3 seconds>"
    }},
    {{
      "variation": 2,
      "hook_text": "<alternative hook using second brain hook type or different emotional trigger>",
      "hook_type": "<type>",
      "brain_weighted": true,
      "visual_direction": "<visual direction>"
    }},
    {{
      "variation": 3,
      "hook_text": "<creative hook based on current video analysis — your judgment>",
      "hook_type": "<type>",
      "brain_weighted": false,
      "visual_direction": "<visual direction>"
    }}
  ],
  "full_script": {{
    "target_duration_seconds": 20,
    "segments": [
      {{
        "label": "hook",
        "seconds": "0-3",
        "spoken_text": "<exact words>",
        "visual_direction": "<what to show>"
      }},
      {{
        "label": "problem",
        "seconds": "3-8",
        "spoken_text": "<exact words>",
        "visual_direction": "<what to show>"
      }},
      {{
        "label": "solution",
        "seconds": "8-16",
        "spoken_text": "<exact words>",
        "visual_direction": "<what to show>"
      }},
      {{
        "label": "cta",
        "seconds": "16-20",
        "spoken_text": "<must end with: 'Call W Real Estate, LLC at 601-499-0952 today.'>",
        "visual_direction": "<show brokerage name and phone on screen as lower third or overlay>"
      }}
    ],
    "compliance_check": {{
      "brokerage_name_included": true,
      "brokerage_phone_included": true,
      "placement": "closing CTA segment"
    }}
  }},
  "content_ideas": [
    "<10 content idea titles extending this same angle for W Real Estate — numbered 1-10>"
  ],
  "caption": {{
    "instagram": "<Instagram caption — hook line, 3-4 sentences, 5-8 hashtags. Must include 'W Real Estate, LLC' and '601-499-0952' naturally in the text>",
    "tiktok": "<TikTok caption — shorter, punchier. Same compliance requirement.>",
    "hashtags": ["<8-12 hashtags relevant to Mississippi real estate, seller content, luxury, Jackson MS>"]
  }},
  "b_roll_cues": [
    {{
      "seconds": 0,
      "cue": "<describe exactly what B-roll footage to use>",
      "duration_seconds": 3
    }}
  ],
  "voiceover_script": {{
    "status": "TOGGLED OFF — pending voice clone finalization (Phase 3)",
    "script_ready": "<full spoken script in one paragraph when activated>"
  }}
}}"""


def build_alpha_insurance_prompt(brand: dict, analysis: dict, brain_context: dict = None) -> str:
    hook = analysis.get("hook_structure", {})
    pacing = analysis.get("pacing", {})
    structure = analysis.get("content_structure", {})
    psych = analysis.get("psychological_hooks", {})
    production = analysis.get("production_notes", {})

    brain_section = build_brain_section(brain_context or {})

    return f"""You are a content strategist generating short-form insurance video scripts for Amanda Frizell, owner of Alpha Insurance — a local Mississippi insurance agency.

BRAND IDENTITY:
- Business: {brand['business_name']}
- Owner: {brand['owner']}
- Tagline: "{brand['tagline']}"
- Phone: {brand['phone']} (include in content)
- Address: {brand['address']}
- Tone: {', '.join(brand['tone'])}
- Lines of Business: {', '.join(brand['lines_of_business'])}
- Content Pillars: {', '.join(brand['content_pillars'])}
- Service Area: {brand['service_area']}
- Carriers in Content: {brand['carriers_in_content']}

BRAND VOICE NOTES:
- Local, trustworthy, protective — NOT corporate or cold
- Speak to Mississippi families and individuals
- Address real cost pain points people face with insurance
- Position Alpha Insurance as the local solution that cares

COMPETITOR VIDEO ANALYSIS (what you are modeling from this specific video):
- Hook type: {hook.get('hook_type', 'unknown')}
- Hook opening: "{hook.get('first_3_seconds_transcript', '')}"
- Pattern interrupt: {hook.get('pattern_interrupt', 'none detected')}
- Pacing style: {pacing.get('pacing_style', 'unknown')} ({pacing.get('cuts_per_second', 0)} cuts/sec)
- Standout technique: {production.get('standout_technique', 'none')}
- Emotional triggers used: {', '.join(psych.get('emotional_triggers', []))}
- Key claim: {analysis.get('messaging_patterns', {}).get('key_claim', 'none')}
- Structure: {json.dumps([s.get('label') for s in structure.get('segments', [])], indent=None)}
{brain_section}

Generate the following and return as a single JSON object:

{{
  "brand": "alpha-insurance",
  "video_id": "<passed in>",
  "generated_at": "<iso timestamp>",
  "hook_variations": [
    {{
      "variation": 1,
      "hook_text": "<3-second opener — use top brain hook type if brain data available>",
      "hook_type": "<type>",
      "brain_weighted": true,
      "visual_direction": "<what to show>"
    }},
    {{
      "variation": 2,
      "hook_text": "<alternative hook using second brain hook type or local/trust angle>",
      "hook_type": "<type>",
      "brain_weighted": true,
      "visual_direction": "<what to show>"
    }},
    {{
      "variation": 3,
      "hook_text": "<creative hook from current video analysis — your judgment>",
      "hook_type": "<type>",
      "brain_weighted": false,
      "visual_direction": "<what to show>"
    }}
  ],
  "full_script": {{
    "target_duration_seconds": 20,
    "segments": [
      {{
        "label": "hook",
        "seconds": "0-3",
        "spoken_text": "<exact words>",
        "visual_direction": "<what to show>"
      }},
      {{
        "label": "pain",
        "seconds": "3-8",
        "spoken_text": "<exact words>",
        "visual_direction": "<what to show>"
      }},
      {{
        "label": "solution",
        "seconds": "8-16",
        "spoken_text": "<exact words>",
        "visual_direction": "<what to show>"
      }},
      {{
        "label": "cta",
        "seconds": "16-20",
        "spoken_text": "<should naturally include 'Alpha Insurance' and '601-981-2911' and optionally close with tagline>",
        "visual_direction": "<show business name and phone>"
      }}
    ]
  }},
  "content_ideas": [
    "<10 content idea titles for Alpha Insurance — numbered 1-10>"
  ],
  "caption": {{
    "instagram": "<Instagram caption — local, warm, protective tone. Include 'Alpha Insurance' and '601-981-2911'. 5-8 hashtags.>",
    "tiktok": "<TikTok caption — punchy version. Same brand inclusion.>",
    "hashtags": ["<8-12 hashtags: Mississippi insurance, local business, auto insurance, home insurance, Jackson MS, etc.>"]
  }},
  "b_roll_cues": [
    {{
      "seconds": 0,
      "cue": "<describe B-roll footage>",
      "duration_seconds": 3
    }}
  ],
  "voiceover_script": {{
    "status": "TOGGLED OFF — pending voice clone finalization (Phase 3). Same voice as W Real Estate when activated.",
    "script_ready": "<full spoken script in one paragraph>"
  }}
}}"""


def generate(analysis_path, brand_id: str, brain_context: dict = None) -> dict:
    if brand_id not in VALID_BRANDS:
        raise ValueError(f"Brand must be one of: {VALID_BRANDS}")

    analysis_path = Path(analysis_path).resolve()
    if not analysis_path.exists():
        raise FileNotFoundError(f"Analysis file not found: {analysis_path}")

    with open(analysis_path, encoding="utf-8") as f:
        analysis_data = json.load(f)

    video_id = analysis_data.get("video_id", "unknown")
    analysis = analysis_data.get("analysis", {})

    brand = load_brand(brand_id)
    logger = get_logger(video_id, brand_id)
    logger.info(f"=== Generation Pipeline v2.1 (Brain-Aware) ===")
    logger.info(f"Brand: {brand_id} | Video ID: {video_id} | Model: {CLAUDE_MODEL}")

    # FIX v2.1: Clean log statement, no nested f-string interpolation issues.
    brain_active = bool(brain_context and brain_context.get("has_learned_patterns"))
    if brain_active:
        videos_count = brain_context.get("videos_analyzed", 0)
        logger.info(f"Brain context: ACTIVE — {videos_count} videos analyzed")
    else:
        logger.info("Brain context: INACTIVE — first run or no data yet")

    client = get_anthropic_client()

    if brand_id == "w-real-estate":
        prompt = build_w_real_estate_prompt(brand, analysis, brain_context)
    else:
        prompt = build_alpha_insurance_prompt(brand, analysis, brain_context)

    logger.info("Sending to Claude API for content generation...")
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        raise

    raw_content = response.content[0].text.strip()
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = estimate_token_cost(input_tokens, output_tokens)

    logger.info(f"Generation complete. Tokens: {input_tokens} in / {output_tokens} out | Cost: ${cost:.6f}")

    if raw_content.startswith("```"):
        lines = raw_content.split("\n")
        raw_content = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        generated = json.loads(raw_content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        logger.error(f"Raw response snippet: {raw_content[:500]}")
        raise ValueError(f"Claude returned invalid JSON: {e}")

    generated["video_id"] = video_id
    generated["generated_at"] = datetime.now().isoformat()
    generated["brain_active"] = brain_active

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_filename = f"{brand_id}-{video_id}-{timestamp}.json"
    out_path = SCRIPTS_DIR / out_filename

    output = {
        "brand": brand_id,
        "video_id": video_id,
        "generated_at": generated["generated_at"],
        "model": CLAUDE_MODEL,
        "brain_active": brain_active,
        "api_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
        },
        "content": generated,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"Generated content saved → {out_path}")
    logger.info("=== Generation complete ===")

    return output


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyzer/generate.py <analysis_json> <brand_id>")
        print(f"  brand_id must be one of: {VALID_BRANDS}")
        sys.exit(1)
    result = generate(sys.argv[1], sys.argv[2])
    content = result["content"]
    print(f"\nHook Variation 1: {content.get('hook_variations', [{}])[0].get('hook_text', '')}")
    print(f"Brain active: {result['brain_active']}")
    print(f"Cost: ${result['api_usage']['estimated_cost_usd']:.6f}")

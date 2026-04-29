# Competitor Videos — Manual Sourcing Workflow

This directory holds competitor video files for analysis. It is gitignored.

---

## How to Source Competitor Videos

1. **Identify the video** on Instagram Reels, TikTok, or Facebook Ad Library
   - Facebook Ad Library: https://www.facebook.com/ads/library/
   - Useful for finding what competitors are actively running as paid ads

2. **Download manually** using one of these methods:
   - Screen record directly on your device
   - Save via browser (right-click where supported)
   - Browser extension (SnapTik for TikTok, InSave for Instagram, etc.)
   - Facebook Ad Library videos can be inspected via browser dev tools (Network tab)

3. **Save to this directory** using this naming convention:

   ```
   [platform]-[handle]-[date]-[shortdescription].mp4
   ```

   **Examples:**
   ```
   instagram-johndoe-realtor-2026-04-29-firsttimebuyer-myth.mp4
   tiktok-msrealestatecoach-2026-04-15-sellinginspring.mp4
   facebook-ads-alphacompetitor-2026-04-20-autoinsurance30sec.mp4
   ```

   Rules:
   - All lowercase
   - Hyphens only — no spaces or underscores
   - Date format: YYYY-MM-DD
   - Keep description under 30 characters
   - `.mp4` format preferred (`.mov` also works)

4. **Run the analysis pipeline:**

   ```
   # Activate venv first (from D:\ContentEngine)
   .\venv\Scripts\activate

   # W Real Estate analysis
   python analyzer/run.py --video "competitor-videos/filename.mp4" --brand w-real-estate

   # Alpha Insurance analysis
   python analyzer/run.py --video "competitor-videos/filename.mp4" --brand alpha-insurance
   ```

5. **Find your output** in `/scripts/` — named `[brand]-[video-id]-[timestamp].json`

---

## What Makes a Good Competitor to Analyze

**For W Real Estate:**
- High-performing realtors in Mississippi, Jackson metro, Gulf Coast
- Luxury agents with strong hook styles
- Realtors doing seller education or myth-busting content
- Look for: views > 10K, strong comment engagement

**For Alpha Insurance:**
- Independent insurance agents in Mississippi or Southeast
- Any local insurance brand doing short-form video well
- Agents addressing cost pain points effectively
- Look for: relatable, high-engagement content regardless of production quality

---

## Add to Competitor Registry

After analyzing a video, add the source to the registry for tracking:

```
python analyzer/registry.py --add --brand w-real-estate --platform instagram --handle "@handle" --type "luxury-realtor" --notes "strong hook style, uses myth-busting"
```

---

## File Size Notes

- Whisper API limit: 25MB per file. Files larger than 25MB are auto-chunked.
- Typical 30-second MP4: 5–15MB — well within limits
- If a file is corrupted or has no audio, the pipeline will exit cleanly with an error message

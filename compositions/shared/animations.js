/**
 * animations.js — Shared GSAP timeline builder for ContentEngine compositions.
 *
 * Rules (enforced by build spec):
 *   - NO Math.random()
 *   - NO Date.now()
 *   - NO repeat: -1 or infinite loops
 *   - All timings are derived from word timestamps or fixed ratios
 *   - Every call with identical inputs produces identical output (deterministic)
 */

/**
 * Group flat word array into lines of `size` words.
 * @param {Array<{word:string, start:number, end:number}>} words
 * @param {number} size  words per line
 * @returns {Array<Array<{word,start,end}>>}
 */
function groupIntoLines(words, size) {
  const lines = [];
  for (let i = 0; i < words.length; i += size) {
    lines.push(words.slice(i, i + size));
  }
  return lines;
}

/**
 * Build and return a paused GSAP master timeline for an authority-reel composition.
 *
 * @param {object} vars  Variables from window.__hyperframes.getVariables()
 *   - words        {Array}   word-timestamp array from faster-whisper
 *   - duration     {number}  total audio duration in seconds
 *   - brand_name   {string}
 *   - phone        {string}
 *   - cta_text     {string}  optional full CTA sentence
 *
 * @param {object} els   DOM element references
 *   - subtitleContainer  {HTMLElement}
 *   - lowerThird         {HTMLElement}
 *   - brandNameEl        {HTMLElement}
 *   - phoneEl            {HTMLElement}
 *   - overlayEl          {HTMLElement}
 *   - logoEl             {HTMLElement|null}
 *
 * @returns {gsap.core.Timeline}
 */
function buildAuthorityTimeline(vars, els) {
  const words    = vars.words    || [];
  const duration = vars.duration || 30;
  const { subtitleContainer, lowerThird, brandNameEl, phoneEl, overlayEl, logoEl } = els;

  const tl = gsap.timeline({ paused: true });

  // ── Fade in ──────────────────────────────────────────────────────────────
  tl.fromTo(overlayEl,
    { opacity: 0 },
    { opacity: 1, duration: 0.4, ease: "power1.inOut" },
    0
  );

  if (logoEl) {
    tl.fromTo(logoEl,
      { opacity: 0, y: -12 },
      { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" },
      0.2
    );
  }

  // ── Word-by-word subtitle animation ──────────────────────────────────────
  if (words.length > 0) {
    const lines = groupIntoLines(words, 3);

    lines.forEach(function(line, lineIndex) {
      const lineStart  = line[0].start;
      const lineEnd    = line[line.length - 1].end + 0.15;
      const nextLineStart = (lines[lineIndex + 1] || [{}])[0].start;
      const exitAt     = nextLineStart || lineEnd;

      // Build line HTML: one span per word, all initially invisible
      const lineHtml = line.map(function(w, wi) {
        return '<span class="sub-word" id="w-' + lineIndex + '-' + wi + '">'
          + w.word.trim()
          + '</span>';
      }).join(' ');

      const lineDiv = document.createElement('div');
      lineDiv.className = 'sub-line';
      lineDiv.style.opacity = '0';
      lineDiv.innerHTML = lineHtml;
      subtitleContainer.appendChild(lineDiv);

      // Line slide-in
      tl.to(lineDiv, { opacity: 1, y: 0, duration: 0.18, ease: "power2.out" }, lineStart);
      tl.fromTo(lineDiv, { y: 14 }, { y: 0, duration: 0.18, ease: "power2.out" }, lineStart);

      // Per-word pop
      line.forEach(function(w, wi) {
        const el = document.getElementById('w-' + lineIndex + '-' + wi);
        if (!el) return;
        tl.fromTo(el,
          { opacity: 0.3, scale: 0.88 },
          { opacity: 1,   scale: 1, duration: 0.14, ease: "back.out(1.4)", transformOrigin: "50% 100%" },
          w.start
        );
      });

      // Line fade-out (except last line which holds)
      if (lineIndex < lines.length - 1) {
        tl.to(lineDiv, { opacity: 0, duration: 0.15, ease: "power1.in" }, exitAt - 0.15);
      }
    });
  }

  // ── Lower-third CTA (appears at 70% of audio duration) ───────────────────
  const ctaAt = duration * 0.70;

  tl.fromTo(lowerThird,
    { opacity: 0, y: 24 },
    { opacity: 1, y: 0, duration: 0.45, ease: "power3.out" },
    ctaAt
  );

  tl.fromTo(brandNameEl,
    { opacity: 0, x: -16 },
    { opacity: 1, x: 0, duration: 0.35, ease: "power2.out" },
    ctaAt + 0.08
  );

  tl.fromTo(phoneEl,
    { opacity: 0, x: -16 },
    { opacity: 1, x: 0, duration: 0.35, ease: "power2.out" },
    ctaAt + 0.18
  );

  return tl;
}

/**
 * Sync a GSAP timeline to a playing audio element in real time.
 * Used when HyperFrames is NOT rendering (live preview mode).
 */
function syncTimelineToAudio(tl, audioEl) {
  audioEl.addEventListener('play', function() { tl.play(audioEl.currentTime); });
  audioEl.addEventListener('pause', function() { tl.pause(); });
  audioEl.addEventListener('seeked', function() { tl.seek(audioEl.currentTime); });
  audioEl.addEventListener('timeupdate', function() {
    var drift = Math.abs(tl.time() - audioEl.currentTime);
    if (drift > 0.1) { tl.seek(audioEl.currentTime); }
  });
}

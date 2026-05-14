import React from 'react';
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Sequence,
  Video,
  Img,
  staticFile,
} from 'remotion';

const BRAND_CONFIGS = {
  'w-real-estate': {
    primary:  '#722F37',
    dark:     '#4A1520',
    black:    '#111111',
    darkBg:   '#0D0D0D',
    cream:    '#F5F0E8',
    accent:   '#C9A84C',
    white:    '#FFFFFF',
    name:     'W Real Estate, LLC',
    phone:    '601-499-0952',
    badge:    'Mississippi Sellers',
    tagline:  'Everything I Touch Turns to Sold.',
    grad1:    '#111111',
    grad2:    '#2D0A10',
    grad3:    '#722F37',
    overlay:  'rgba(0,0,0,0.52)',
  },
  'alpha-insurance': {
    primary:  '#8B1A1A',
    dark:     '#5A0A0A',
    black:    '#111111',
    darkBg:   '#0D0D0D',
    cream:    '#F0F0F0',
    accent:   '#BBBBBB',
    white:    '#FFFFFF',
    name:     'Alpha Insurance',
    phone:    '601-981-2911',
    badge:    'Mississippi Families',
    tagline:  'Everything you protect, we cover.',
    grad1:    '#111111',
    grad2:    '#1A0505',
    grad3:    '#8B1A1A',
    overlay:  'rgba(0,0,0,0.55)',
  },
};

const SNAPPY = { damping: 12, stiffness: 200, mass: 0.5 };
const SMOOTH = { damping: 18, stiffness: 120, mass: 0.8 };
const BOUNCY = { damping: 8,  stiffness: 180, mass: 0.6 };
const clamp  = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' };

function useSp(fromFrame, config) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - fromFrame, fps, config: config || SMOOTH });
}

function useOp(fromFrame, dur) {
  const frame = useCurrentFrame();
  return interpolate(frame - fromFrame, [0, dur || 12], [0, 1], clamp);
}

function splitBullets(text) {
  return text.split(/\.\s+/).map(function(s) { return s.replace(/\.$/, '').trim(); }).filter(function(s) { return s.length > 4; }).slice(0, 3);
}

function VideoLayer({ clipPath, color }) {
  if (!clipPath) {
    return React.createElement(AbsoluteFill, {
      style: { background: 'linear-gradient(155deg, ' + color.grad1 + ' 0%, ' + color.grad2 + ' 55%, ' + color.grad3 + ' 100%)' }
    });
  }
  return React.createElement(React.Fragment, null,
    React.createElement(AbsoluteFill, null,
      React.createElement(Video, {
        src: staticFile(clipPath),
        style: { width: '100%', height: '100%', objectFit: 'cover' },
        muted: true,
        loop: true,
      })
    ),
    React.createElement(AbsoluteFill, { style: { backgroundColor: color.overlay } })
  );
}

function LogoLayer({ logoPath }) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 25], [0, 0.92], clamp);
  if (!logoPath) return null;
  return React.createElement(AbsoluteFill, { style: { pointerEvents: 'none' } },
    React.createElement(Img, {
      src: staticFile(logoPath),
      style: {
        position: 'absolute',
        bottom: 80,
        right: 52,
        width: 160,
        height: 'auto',
        opacity: opacity,
        filter: 'drop-shadow(0 2px 10px rgba(0,0,0,0.8))',
      }
    })
  );
}

function WordReveal({ text, startFrame, color, fontSize, delay, highlightLast }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = text.split(' ');
  const fs = fontSize || 72;
  const d  = delay || 4;
  return React.createElement('div', {
    style: {
      display: 'flex', flexWrap: 'wrap',
      justifyContent: 'center', alignItems: 'center',
      gap: '12px 16px', padding: '0 64px', textAlign: 'center',
    }
  }, words.map(function(word, i) {
    const f  = frame - (startFrame + i * d);
    const sp = spring({ frame: f, fps: fps, config: SNAPPY });
    const op = interpolate(f, [0, 10], [0, 1], clamp);
    const ty = interpolate(sp, [0, 1], [50, 0], clamp);
    const sc = interpolate(sp, [0, 1], [0.6, 1], clamp);
    const isHL = highlightLast && i === words.length - 1;
    return React.createElement('span', {
      key: i,
      style: {
        color: isHL ? color.accent : color.white,
        fontSize: fs, fontWeight: 800,
        fontFamily: 'system-ui, -apple-system, sans-serif',
        opacity: op,
        transform: 'translateY(' + ty + 'px) scale(' + sc + ')',
        display: 'inline-block',
        textShadow: '0 4px 24px rgba(0,0,0,0.95)',
        lineHeight: 1.2,
      }
    }, word);
  }));
}

function AccentBar({ fromFrame, color, width }) {
  const sp = useSp(fromFrame || 0, SMOOTH);
  const w  = interpolate(sp, [0, 1], [0, width || 220], clamp);
  return React.createElement('div', {
    style: { width: w + 'px', height: '5px', backgroundColor: color.accent, borderRadius: '3px', marginTop: '28px' }
  });
}

function Badge({ text, fromFrame, color }) {
  const sp = useSp(fromFrame || 0, SNAPPY);
  const op = useOp(fromFrame || 0);
  const sc = interpolate(sp, [0, 1], [0.6, 1], clamp);
  return React.createElement('div', {
    style: {
      opacity: op, transform: 'scale(' + sc + ')',
      backgroundColor: color.primary, color: color.cream,
      fontSize: 26, fontWeight: 700, fontFamily: 'system-ui',
      letterSpacing: '3px', padding: '12px 36px',
      borderRadius: '100px', textTransform: 'uppercase',
      marginBottom: 48, boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
    }
  }, text);
}

function HookScene({ hookText, color, brollClip, logoPath }) {
  const tagSp = useSp(90, SMOOTH);
  const tagOp = useOp(90, 18);
  const tagY  = interpolate(tagSp, [0, 1], [30, 0]);
  return React.createElement(AbsoluteFill, null,
    React.createElement(VideoLayer, { clipPath: brollClip, color: color }),
    React.createElement(AbsoluteFill, { style: { justifyContent: 'center', alignItems: 'center', flexDirection: 'column' } },
      React.createElement(Badge, { text: color.badge, fromFrame: 8, color: color }),
      React.createElement(WordReveal, { text: hookText, startFrame: 18, color: color, fontSize: 70, delay: 4, highlightLast: true }),
      React.createElement(AccentBar, { fromFrame: 90, color: color }),
      React.createElement('div', {
        style: {
          position: 'absolute', bottom: 280,
          opacity: tagOp, transform: 'translateY(' + tagY + 'px)',
          color: color.accent, fontSize: 32, fontWeight: 600,
          fontFamily: 'system-ui', fontStyle: 'italic',
          letterSpacing: '1px', textAlign: 'center',
          padding: '0 60px', textShadow: '0 2px 12px rgba(0,0,0,0.9)',
        }
      }, color.tagline)
    ),
    React.createElement(LogoLayer, { logoPath: logoPath })
  );
}

function ProblemScene({ problemText, color, brollClip, logoPath }) {
  const frame   = useCurrentFrame();
  const { fps } = useVideoConfig();
  const slideSp = spring({ frame: frame, fps: fps, config: SMOOTH });
  const slideX  = interpolate(slideSp, [0, 1], [8, 0], clamp);
  const labelOp = useOp(0, 15);
  const bullets = splitBullets(problemText);
  return React.createElement(AbsoluteFill, null,
    React.createElement(VideoLayer, { clipPath: brollClip, color: color }),
    React.createElement(AbsoluteFill, {
      style: {
        transform: 'translateX(' + slideX + '%)',
        justifyContent: 'center', alignItems: 'flex-start',
        paddingLeft: 80, flexDirection: 'column',
      }
    },
      React.createElement('div', {
        style: {
          color: color.accent, fontSize: 26, fontWeight: 800,
          fontFamily: 'system-ui', letterSpacing: '4px',
          textTransform: 'uppercase', marginBottom: 52,
          opacity: labelOp, textShadow: '0 2px 8px rgba(0,0,0,0.9)',
        }
      }, 'Sound familiar?'),
      bullets.map(function(item, i) {
        const delay = 10 + i * 22;
        const p = spring({ frame: frame - delay, fps: fps, config: SNAPPY });
        const o = interpolate(frame - delay, [0, 12], [0, 1], clamp);
        const x = interpolate(p, [0, 1], [-80, 0], clamp);
        return React.createElement('div', {
          key: i,
          style: { display: 'flex', alignItems: 'center', gap: 28, opacity: o, transform: 'translateX(' + x + 'px)', marginBottom: 44 }
        },
          React.createElement('div', {
            style: { width: 16, height: 16, borderRadius: '50%', backgroundColor: color.accent, flexShrink: 0, boxShadow: '0 0 12px ' + color.accent }
          }),
          React.createElement('span', {
            style: { color: color.white, fontSize: 54, fontWeight: 700, fontFamily: 'system-ui', textShadow: '0 2px 12px rgba(0,0,0,0.95)', lineHeight: 1.3 }
          }, item)
        );
      }),
      React.createElement(AccentBar, { fromFrame: 70, color: color })
    ),
    React.createElement(LogoLayer, { logoPath: logoPath })
  );
}

function SolutionScene({ solutionText, color, brollClip, logoPath }) {
  const frame   = useCurrentFrame();
  const { fps } = useVideoConfig();
  const mainSp  = spring({ frame: frame, fps: fps, config: SMOOTH });
  const mainOp  = interpolate(frame, [0, 20], [0, 1], clamp);
  const mainY   = interpolate(mainSp, [0, 1], [60, 0], clamp);
  return React.createElement(AbsoluteFill, null,
    React.createElement(VideoLayer, { clipPath: brollClip, color: color }),
    React.createElement(AbsoluteFill, { style: { justifyContent: 'center', alignItems: 'center', flexDirection: 'column', padding: '0 60px' } },
      React.createElement('div', { style: { opacity: mainOp, transform: 'translateY(' + mainY + 'px)', textAlign: 'center', marginBottom: 52 } },
        React.createElement('div', {
          style: { color: color.accent, fontSize: 26, fontWeight: 700, letterSpacing: '3px', textTransform: 'uppercase', fontFamily: 'system-ui', marginBottom: 24, textShadow: '0 2px 8px rgba(0,0,0,0.9)' }
        }, color.name)
      ),
      React.createElement(WordReveal, { text: solutionText, startFrame: 25, color: color, fontSize: 56, delay: 3, highlightLast: true }),
      React.createElement(AccentBar, { fromFrame: 120, color: color, width: 300 })
    ),
    React.createElement(LogoLayer, { logoPath: logoPath })
  );
}

function CTAScene({ ctaText, color, brollClip, logoPath }) {
  const frame   = useCurrentFrame();
  const { fps } = useVideoConfig();
  const textOp  = useOp(10, 15);
  const textSp  = useSp(10, SNAPPY);
  const textY   = interpolate(textSp, [0, 1], [60, 0]);
  const pillSp  = useSp(45, BOUNCY);
  const pillSc  = interpolate(pillSp, [0, 1], [0.2, 1]);
  const pillOp  = useOp(45, 15);
  const phoneSp = useSp(80, BOUNCY);
  const phoneSc = interpolate(phoneSp, [0, 1], [0.5, 1]);
  const phoneOp = useOp(80, 15);
  const ringOp  = interpolate(frame % 60, [0, 30, 60], [0.15, 0.45, 0.15], clamp);
  const ringSc  = interpolate(frame % 60, [0, 30, 60], [1.0, 1.18, 1.0], clamp);
  return React.createElement(AbsoluteFill, null,
    React.createElement(VideoLayer, { clipPath: brollClip, color: color }),
    React.createElement(AbsoluteFill, { style: { justifyContent: 'center', alignItems: 'center', flexDirection: 'column' } },
      React.createElement('div', { style: { opacity: textOp, transform: 'translateY(' + textY + 'px)', textAlign: 'center', marginBottom: 72, padding: '0 64px' } },
        React.createElement('div', { style: { color: color.white, fontSize: 64, fontWeight: 800, fontFamily: 'system-ui', lineHeight: 1.35, textShadow: '0 4px 20px rgba(0,0,0,0.95)' } },
          ctaText.split('.')[0] + '.'
        )
      ),
      React.createElement('div', {
        style: { opacity: pillOp, transform: 'scale(' + pillSc + ')', backgroundColor: color.primary, borderRadius: 100, padding: '32px 72px', marginBottom: 56, boxShadow: '0 24px 60px rgba(0,0,0,0.6)' }
      },
        React.createElement('div', { style: { color: color.white, fontSize: 42, fontWeight: 800, fontFamily: 'system-ui', textAlign: 'center' } }, 'Call Us Today')
      ),
      React.createElement('div', { style: { opacity: phoneOp, transform: 'scale(' + phoneSc + ')', position: 'relative', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center' } },
        React.createElement('div', {
          style: { position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%) scale(' + ringSc + ')', width: 400, height: 130, borderRadius: 100, border: '3px solid ' + color.accent, opacity: ringOp, pointerEvents: 'none' }
        }),
        React.createElement('div', { style: { color: color.accent, fontSize: 58, fontWeight: 800, fontFamily: 'system-ui', letterSpacing: '4px', textShadow: '0 4px 16px rgba(0,0,0,0.9)' } }, color.phone),
        React.createElement('div', { style: { color: color.cream, fontSize: 28, fontWeight: 500, fontFamily: 'system-ui', marginTop: 14, opacity: 0.9, letterSpacing: '1px', textShadow: '0 2px 8px rgba(0,0,0,0.8)' } }, color.name)
      )
    ),
    React.createElement(LogoLayer, { logoPath: logoPath })
  );
}

export const AuthorityReel = function({
  hookText,
  problemText,
  solutionText,
  ctaText,
  brandKey,
  brollHook,
  brollProblem,
  brollSolution,
  brollCta,
  logoPath,
}) {
  const ht  = hookText     || "Selling your home shouldn't cost you sleep.";
  const pt  = problemText  || "Most agents make you juggle showings, staging stress, and endless uncertainty. It doesn't have to be that way.";
  const st  = solutionText || "Expert guidance, white-glove service, and a proven strategy. Everything I touch turns to sold.";
  const ct  = ctaText      || "Let's get your home sold with zero stress. Call W Real Estate, LLC at 601-499-0952 today.";
  const bk  = brandKey     || 'w-real-estate';
  const bh  = brollHook    || '';
  const bp  = brollProblem || '';
  const bs  = brollSolution|| '';
  const bc  = brollCta     || '';
  const lp  = logoPath     || '';
  const color = BRAND_CONFIGS[bk] || BRAND_CONFIGS['w-real-estate'];
  return React.createElement(AbsoluteFill, { style: { backgroundColor: color.black } },
    React.createElement(Sequence, { from: 0, durationInFrames: 150 },
      React.createElement(HookScene, { hookText: ht, color: color, brollClip: bh, logoPath: lp })
    ),
    React.createElement(Sequence, { from: 150, durationInFrames: 180 },
      React.createElement(ProblemScene, { problemText: pt, color: color, brollClip: bp, logoPath: lp })
    ),
    React.createElement(Sequence, { from: 330, durationInFrames: 210 },
      React.createElement(SolutionScene, { solutionText: st, color: color, brollClip: bs, logoPath: lp })
    ),
    React.createElement(Sequence, { from: 540, durationInFrames: 210 },
      React.createElement(CTAScene, { ctaText: ct, color: color, brollClip: bc, logoPath: lp })
    )
  );
};
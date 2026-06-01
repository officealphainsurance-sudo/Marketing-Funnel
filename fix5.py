from pathlib import Path

f = Path('remotion-test/Composition.jsx')
c = f.read_text()

# 1. Add HeadshotLayer after LogoLayer
headshot_layer = '''
function HeadshotLayer({ headshot }) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 25], [0, 1], clamp);
  if (!headshot) return null;
  return React.createElement(AbsoluteFill, { style: { pointerEvents: 'none' } },
    React.createElement(Img, {
      src: staticFile(headshot),
      style: {
        position: 'absolute',
        bottom: 0,
        left: 0,
        width: 420,
        height: 'auto',
        opacity: opacity,
      }
    })
  );
}
'''
c = c.replace('function WordReveal(', headshot_layer + '\nfunction WordReveal(')

# 2. Add OutroScene before AuthorityReel
outro_scene = '''
function OutroScene({ outroPath }) {
  if (!outroPath) return React.createElement(AbsoluteFill, { style: { backgroundColor: '#111111' } });
  return React.createElement(AbsoluteFill, null,
    React.createElement(Img, {
      src: staticFile(outroPath),
      style: { width: '100%', height: '100%', objectFit: 'cover' }
    })
  );
}
'''
c = c.replace('export const AuthorityReel', outro_scene + '\nexport const AuthorityReel')

# 3. Add headshot + outroPath to AuthorityReel props
c = c.replace(
    '  logoPath,\n}) {',
    '  logoPath,\n  headshot,\n  outroPath,\n}) {'
)

# 4. Add const hs and op after lp
c = c.replace(
    '  const lp  = logoPath     || \'\';',
    '  const lp  = logoPath     || \'\';\n  const hs  = headshot     || \'\';\n  const op  = outroPath    || \'\';'
)

# 5. Add headshot prop to all 4 scenes
for scene in ['HookScene', 'ProblemScene', 'SolutionScene', 'CTAScene']:
    c = c.replace(
        f'React.createElement({scene}, {{ hookText: ht,' if scene == 'HookScene' else '',
        ''
    )

c = c.replace(
    'React.createElement(HookScene, { hookText: ht, color: color, brollClip: bh, logoPath: lp })',
    'React.createElement(HookScene, { hookText: ht, color: color, brollClip: bh, logoPath: lp, headshot: hs })'
)
c = c.replace(
    'React.createElement(ProblemScene, { problemText: pt, color: color, brollClip: bp, logoPath: lp })',
    'React.createElement(ProblemScene, { problemText: pt, color: color, brollClip: bp, logoPath: lp, headshot: hs })'
)
c = c.replace(
    'React.createElement(SolutionScene, { solutionText: st, color: color, brollClip: bs, logoPath: lp })',
    'React.createElement(SolutionScene, { solutionText: st, color: color, brollClip: bs, logoPath: lp, headshot: hs })'
)
c = c.replace(
    'React.createElement(CTAScene, { ctaText: ct, color: color, brollClip: bc, logoPath: lp })',
    'React.createElement(CTAScene, { ctaText: ct, color: color, brollClip: bc, logoPath: lp, headshot: hs })'
)

# 6. Add headshot param and HeadshotLayer to each scene function
for scene in ['HookScene', 'ProblemScene', 'SolutionScene', 'CTAScene']:
    c = c.replace(
        f'function {scene}({{ hookText, color, brollClip, logoPath }})' if scene == 'HookScene' else
        f'function {scene}({{ problemText, color, brollClip, logoPath }})' if scene == 'ProblemScene' else
        f'function {scene}({{ solutionText, color, brollClip, logoPath }})' if scene == 'SolutionScene' else
        f'function {scene}({{ ctaText, color, brollClip, logoPath }})',
        f'function {scene}({{ {"hookText" if scene=="HookScene" else "problemText" if scene=="ProblemScene" else "solutionText" if scene=="SolutionScene" else "ctaText"}, color, brollClip, logoPath, headshot }})'
    )
    c = c.replace(
        f'    React.createElement(LogoLayer, {{ logoPath: logoPath }})\n  );\n}}\n\n{"function ProblemScene" if scene=="HookScene" else "function SolutionScene" if scene=="ProblemScene" else "function CTAScene" if scene=="SolutionScene" else ""}',
        f'    React.createElement(HeadshotLayer, {{ headshot: headshot }}),\n    React.createElement(LogoLayer, {{ logoPath: logoPath }})\n  );\n}}\n\n{"function ProblemScene" if scene=="HookScene" else "function SolutionScene" if scene=="ProblemScene" else "function CTAScene" if scene=="SolutionScene" else ""}'
    ) if scene != 'CTAScene' else None

# Fix CTAScene separately
c = c.replace(
    '    React.createElement(LogoLayer, { logoPath: logoPath })\n  );\n}\n\nfunction OutroScene',
    '    React.createElement(HeadshotLayer, { headshot: headshot }),\n    React.createElement(LogoLayer, { logoPath: logoPath })\n  );\n}\n\nfunction OutroScene'
)

# 7. Add OutroScene sequence at frame 750
c = c.replace(
    '    React.createElement(Sequence, { from: 540, durationInFrames: 210 },\n      React.createElement(CTAScene, { ctaText: ct, color: color, brollClip: bc, logoPath: lp, headshot: hs })\n    )\n  );',
    '    React.createElement(Sequence, { from: 540, durationInFrames: 210 },\n      React.createElement(CTAScene, { ctaText: ct, color: color, brollClip: bc, logoPath: lp, headshot: hs })\n    ),\n    React.createElement(Sequence, { from: 750, durationInFrames: 150 },\n      React.createElement(OutroScene, { outroPath: op })\n    )\n  );'
)

f.write_text(c)
print('Composition.jsx patched.')

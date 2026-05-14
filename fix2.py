from pathlib import Path
f = Path('remotion-test/Composition.jsx')
content = f.read_text()
content = content.replace(
    'interpolate(slideSp, [0, 1], [8, 0]);',
    'interpolate(slideSp, [0, 1], [8, 0], clamp);'
)
content = content.replace(
    'interpolate(mainSp, [0, 1], [60, 0]);',
    'interpolate(mainSp, [0, 1], [60, 0], clamp);'
)
f.write_text(content)
print('Done.')

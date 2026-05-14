from pathlib import Path
f = Path('remotion-test/Composition.jsx')
c = f.read_text()
fixes = [
    ('interpolate(sp, [0, 1], [50, 0]);', 'interpolate(sp, [0, 1], [50, 0], clamp);'),
    ('interpolate(sp, [0, 1], [0.6, 1]);', 'interpolate(sp, [0, 1], [0.6, 1], clamp);'),
    ('interpolate(sp, [0, 1], [0, width || 220]);', 'interpolate(sp, [0, 1], [0, width || 220], clamp);'),
    ('interpolate(p, [0, 1], [-80, 0]);', 'interpolate(p, [0, 1], [-80, 0], clamp);'),
]
for old, new in fixes:
    if old in c:
        c = c.replace(old, new)
        print('Fixed:', old[:40])
    else:
        print('NOT FOUND:', old[:40])
f.write_text(c)
print('Done.')

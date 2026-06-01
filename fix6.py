from pathlib import Path
f = Path('remotion-test/Root.jsx')
c = f.read_text().replace('durationInFrames={750}', 'durationInFrames={900}')
f.write_text(c)
print('Root.jsx updated.')

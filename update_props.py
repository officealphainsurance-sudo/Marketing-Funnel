import json
from pathlib import Path

props_path = sorted(Path('temp').glob('remotion-props-*.json'))[-1]
props = json.loads(props_path.read_text())

for key in ['brollHook', 'brollProblem', 'brollSolution', 'brollCta']:
    if props.get(key):
        props[key] = props[key].replace('.mp4', '-1080.mp4')
        print(f'{key}: {props[key]}')

props_path.write_text(json.dumps(props))
print('Props updated.')

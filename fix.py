from pathlib import Path
f = Path('analyzer/remotion_render.py')
content = f.read_text()
old = '        "--props", str(props_path),\n    ]'
new = '        "--props", str(props_path),\n        "--public-dir", r"D:/ContentEngine/public",\n    ]'
if old in content:
    f.write_text(content.replace(old, new))
    print('Fix applied.')
else:
    print('Pattern not found.')

from pathlib import Path

f = Path('analyzer/run.py')
raw = f.read_bytes()

# Normalize to LF, apply fix, then restore original line endings
crlf = b'\r\n' in raw
c = raw.decode('utf-8').replace('\r\n', '\n')

old = '    # Step 8: Remotion render\n    step("8/8 '
new = (
    '    # Step 8: B-Roll generation (Kling AI -> Pexels fallback)\n'
    '    step("8/9 - Generating b-roll (Kling AI / Pexels)", logger)\n'
    '    t0 = datetime.now()\n'
    '    try:\n'
    '        from analyzer.broll import generate_broll\n'
    '        broll_manifest = generate_broll(script_path, brand)\n'
    '        broll_source = broll_manifest.get("source", "unknown")\n'
    '        broll_count = broll_manifest.get("succeeded", 0)\n'
    '        logger.info(f"B-roll complete in {(datetime.now()-t0).seconds}s | {broll_count} clips [{broll_source}]")\n'
    '    except Exception as e:\n'
    '        logger.warning(f"B-roll generation failed: {e} - using existing clips")\n'
    '\n'
    '    # Step 9: Remotion render\n'
    '    step("9/9 - '
)

if old in c:
    c = c.replace(old, new)
    if crlf:
        c = c.replace('\n', '\r\n')
    f.write_bytes(c.encode('utf-8'))
    print('run.py updated.')
else:
    print('Pattern not found - checking what is there:')
    idx = c.find('# Step 8')
    print(repr(c[idx-4:idx+60]))

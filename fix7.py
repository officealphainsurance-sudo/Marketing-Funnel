from pathlib import Path
f = Path('analyzer/remotion_render.py')
c = f.read_text()
old = '    logo_src  = ASSETS_DIR / brand / "logo.png"'
new = '''    headshot_src = ASSETS_DIR / brand / "headshot.png"
    headshot_prop = None
    if headshot_src.exists():
        dest_name = f"{brand}-headshot.png"
        shutil.copy2(headshot_src, pub_assets / dest_name)
        headshot_prop = f"assets/{dest_name}"

    outro_src = ASSETS_DIR / brand / "outro.png"
    outro_prop = None
    if outro_src.exists():
        dest_name = f"{brand}-outro.png"
        shutil.copy2(outro_src, pub_assets / dest_name)
        outro_prop = f"assets/{dest_name}"

    logo_src  = ASSETS_DIR / brand / "logo.png"'''
c = c.replace(old, new)
old2 = '    return broll_props, logo_prop'
new2 = '    return broll_props, logo_prop, headshot_prop, outro_prop'
c = c.replace(old2, new2)
old3 = '    broll_props, logo_prop = _setup_public(video_id, brand, logger)'
new3 = '    broll_props, logo_prop, headshot_prop, outro_prop = _setup_public(video_id, brand, logger)'
c = c.replace(old3, new3)
old4 = '        "logoPath":      logo_prop or "",'
new4 = '        "logoPath":      logo_prop or "",\n        "headshot":      headshot_prop or "",\n        "outroPath":     outro_prop or "",'
c = c.replace(old4, new4)
f.write_text(c)
print("remotion_render.py updated.")

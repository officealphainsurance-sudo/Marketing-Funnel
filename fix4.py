from pathlib import Path
f = Path('analyzer/remotion_render.py')
old = '''                    dest_name = f"{video_id}-{scene}.mp4"
                    shutil.copy2(src, pub_broll / dest_name)
                    broll_props[scene] = f"broll/{dest_name}"'''
new = '''                    dest_name = f"{video_id}-{scene}-kf.mp4"
                    dest = pub_broll / dest_name
                    import subprocess
                    subprocess.run([
                        "ffmpeg", "-i", str(src),
                        "-vf", "scale=1080:1920,fps=30",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                        "-g", "1", "-y", str(dest)
                    ], capture_output=True)
                    broll_props[scene] = f"broll/{dest_name}"'''
content = f.read_text()
if old in content:
    f.write_text(content.replace(old, new))
    print('Fix applied.')
else:
    print('Pattern not found.')

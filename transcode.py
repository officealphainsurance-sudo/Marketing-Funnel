import subprocess
from pathlib import Path

clips = [
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-hook.mp4',
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-problem.mp4',
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-solution.mp4',
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-cta.mp4',
]

broll = Path('public/broll')
for clip in clips:
    src = broll / clip
    dst = broll / clip.replace('.mp4', '-1080.mp4')
    cmd = [
        'ffmpeg', '-i', str(src),
        '-vf', 'scale=1080:1920,fps=30',
        '-c:v', 'libx264', '-preset', 'fast', '-crs', '18',
        '-y', str(dst)
    ]
    print(f'Processing {clip}...')
    subprocess.run(cmd)
    print(f'Done -> {dst.name}')

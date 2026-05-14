import subprocess
from pathlib import Path

clips = [
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-hook-1080.mp4',
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-problem-1080.mp4',
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-solution-1080.mp4',
    'youtube-unknown-2026-04-30-seller-tips-s-181f69-cta-1080.mp4',
]

broll = Path('public/broll')
for clip in clips:
    src = broll / clip
    dst = broll / clip.replace('-1080.mp4', '-kf.mp4')
    cmd = [
        'ffmpeg', '-i', str(src),
        '-vf', 'fps=30',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-g', '1',
        '-y', str(dst)
    ]
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f'OK -> {dst.name} ({dst.stat().st_size // 1024}KB)')
    else:
        print(f'FAILED: {clip}')

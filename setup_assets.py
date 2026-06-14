#!/usr/bin/env python3
"""
One-time setup: processes the NESTU logo and places assets.
Run once after cloning the repo, before first generate.py run.

Usage:
  python setup_assets.py --logo path/to/nestu_logo.png

The logo file should be the blue-on-white version (as exported by the brand team).
This script creates:
  assets/logo_white.png  — white-on-transparent for blue backgrounds (covers, headers)
  assets/logo_blue.png   — original resized for white backgrounds (letterhead)
"""

import sys
import shutil
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("ERROR: Pillow required. Run: pip install Pillow")

ASSETS_DIR = Path(__file__).parent / 'assets'
FONTS_DIR  = Path(__file__).parent / 'fonts'
CONFIG_DIR = Path(__file__).parent / 'config'

ASSETS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

DEAR_DOCTOR_DEFAULT = """Dear Doctor,

When we started NESTU, it began with a simple belief: that the pets in our region deserve the same standard of care available anywhere in the world — and that the veterinarians who dedicate their lives to these patients deserve a partner who truly understands what that takes.

We are building NESTU not as a traditional distributor, but as an extension of your clinic. Every product we carry, every specialist we bring to your side, and every service we offer exists for one reason: to help you provide the best possible care to the patients and families who trust you. That mission guides every decision we make.

This catalogue represents the breadth of what we can place in your hands today — but it is only part of the story. The other part is you. Your insights, your needs, and your feedback shape who we become. If there is something missing, something we can do better, or a challenge you face that we haven't yet addressed, we genuinely want to hear it. This is your catalogue as much as it is ours.

Thank you for the work you do every day. It is a privilege to stand alongside you.

With warmth and respect,

The NESTU family"""


def process_logo(logo_path: Path):
    print(f'Processing logo: {logo_path}')
    img = Image.open(logo_path).convert('RGBA')
    w, h = img.size
    print(f'  Original size: {w}×{h}')

    # ── Blue logo (for white pages): just resize ──
    TARGET_W = 320
    target_h = int(h * TARGET_W / w)
    blue_logo = img.copy().resize((TARGET_W, target_h), Image.LANCZOS)
    # Make white background transparent, keep coloured pixels
    px = blue_logo.load()
    for y in range(target_h):
        for x in range(TARGET_W):
            r, g, b, a = px[x, y]
            if (r + g + b) / 3 > 210:   # near-white → transparent
                px[x, y] = (255, 255, 255, 0)
    blue_out = ASSETS_DIR / 'logo_blue.png'
    blue_logo.save(blue_out, format='PNG', optimize=True)
    print(f'  ✓ logo_blue.png saved  ({blue_out.stat().st_size//1024}KB)')

    # ── White logo (for blue backgrounds): transparent bg, white pixels ──
    white_logo = img.copy().resize((TARGET_W, target_h), Image.LANCZOS)
    px2 = white_logo.load()
    for y in range(target_h):
        for x in range(TARGET_W):
            r, g, b, a = px2[x, y]
            brightness = (r + g + b) / 3
            if brightness > 200:         # background → transparent
                px2[x, y] = (255, 255, 255, 0)
            else:                        # logo pixel → white
                px2[x, y] = (255, 255, 255, 255)
    white_out = ASSETS_DIR / 'logo_white.png'
    white_logo.save(white_out, format='PNG', optimize=True)
    print(f'  ✓ logo_white.png saved ({white_out.stat().st_size//1024}KB)')


def check_fonts():
    required = ['NeulisAlt-Black.otf', 'NeulisAlt-Medium.otf', 'NeulisAlt-Regular.otf']
    missing = [f for f in required if not (FONTS_DIR / f).exists()]
    if missing:
        print(f'\n⚠ Missing font files in ./fonts/:')
        for f in missing:
            print(f'    • {f}')
        print('  Copy the Neulis Alt OTF files into ./fonts/ and re-run.')
    else:
        print(f'\n✓ All fonts present in ./fonts/')


def write_dear_doctor():
    p = CONFIG_DIR / 'dear_doctor.txt'
    if not p.exists():
        p.write_text(DEAR_DOCTOR_DEFAULT, encoding='utf-8')
        print(f'✓ Default dear_doctor.txt written to ./config/')
        print('  Edit ./config/dear_doctor.txt to update the letter.')
    else:
        print(f'✓ dear_doctor.txt already exists (not overwritten)')


def main():
    logo_arg = None
    for i, a in enumerate(sys.argv[1:], 1):
        if a == '--logo' and i < len(sys.argv):
            logo_arg = Path(sys.argv[i+1])
        elif not a.startswith('--') and (i == 1 or sys.argv[i-1] == '--logo'):
            if not a.startswith('--'):
                logo_arg = Path(a)

    if logo_arg and logo_arg.exists():
        process_logo(logo_arg)
    elif (ASSETS_DIR / 'logo_blue.png').exists():
        print('✓ Logo assets already exist (delete assets/ to re-process)')
    else:
        print('⚠ No logo provided. Run: python setup_assets.py --logo path/to/nestu_logo.png')

    check_fonts()
    write_dear_doctor()

    print('\n✓ Setup complete. Next steps:')
    print('  1. Copy Neulis Alt OTF files to ./fonts/ (if not done)')
    print('  2. Set env vars: ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY')
    print('  3. python generate.py')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
NESTU® Product Catalogue Generator  v2
Generates responsive HTML flipbook catalogues for Jordan, UAE, and KSA.

Changes v2:
- Fonts served as files (not base64) → correct rendering
- Responsive: scales to any screen / mobile
- No topbar, no page footers
- Progress-bar navigation (handles 60+ pages)
- Brand logos from Odoo tag images
- Configurable category/name exclusions
- Product cards more compact
"""

import xmlrpc.client
import base64
import os
import sys
import re
import io
import json
import shutil
import html as html_mod
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

ODOO_URL  = os.environ.get('ODOO_URL',  'https://nestu.odoo.com')
ODOO_DB   = os.environ.get('ODOO_DB',   'odooerp-ae-nestu-health-main-12720997')
ODOO_USER = os.environ.get('ODOO_USERNAME', '')
ODOO_KEY  = os.environ.get('ODOO_API_KEY',  '')

BASE_DIR   = Path(__file__).parent
FONTS_DIR  = BASE_DIR / 'fonts'
ASSETS_DIR = BASE_DIR / 'assets'
CONFIG_DIR = BASE_DIR / 'config'
CACHE_DIR  = BASE_DIR / 'cache' / 'images'
OUTPUT_DIR = BASE_DIR / 'docs'

for d in [CACHE_DIR, OUTPUT_DIR, CONFIG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

PRODUCTS_PER_PAGE = 6   # 3 cols × 2 rows

# ── EXCLUSION FILTERS ──────────────────────────────────────────────────────
# Add Odoo categ_id integers to exclude entire categories (e.g. kits, bins)
EXCLUDE_CATEG_IDS = []

# Add lowercase substrings — any product name containing these is excluded
# Example: EXCLUDE_NAME_CONTAINS = ['kit', 'bin', 'tray', 'set']
EXCLUDE_NAME_CONTAINS = []

# Exclude products where BOTH conditions match: code starts with prefix AND name contains keyword
# Each tuple: (code_prefix, name_contains)
EXCLUDE_CODE_AND_NAME = [
    ('PPP5', 'kit'),
    ('PPP5', 'bin'),
]

# ── COMPANIES ──────────────────────────────────────────────────────────────
COMPANIES = {
    'jordan': {
        'id': 2, 'name': 'Jordan', 'slug': 'jordan',
        'entity': 'The Nest for Specialized Veterinary Therapeutics & Utilities Ltd.',
        'address': 'Oweym Ben Saeda St., Bldg. No. 46 · Amman, Jordan',
    },
    'uae': {
        'id': 3, 'name': 'UAE', 'slug': 'uae',
        'entity': 'NESTU Veterinary Medicines Trading L.L.C',
        'address': 'Office 602, North Tower, Dubai Science Park · Dubai, UAE',
    },
    'ksa': {
        'id': 4, 'name': 'KSA', 'slug': 'ksa',
        'entity': 'NESTU KSA',
        'address': 'Kingdom of Saudi Arabia',
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# ODOO
# ─────────────────────────────────────────────────────────────────────────────

def connect_odoo():
    common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common', allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_KEY, {})
    if not uid:
        raise SystemExit('ERROR: Odoo auth failed. Check ODOO_USERNAME / ODOO_API_KEY.')
    models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)
    def call(model, method, *args, **kwargs):
        return models.execute_kw(ODOO_DB, uid, ODOO_KEY, model, method, list(args), kwargs)
    print(f'✓ Odoo connected (uid={uid})')
    return call

def get_in_stock_tmpl_ids(odoo, company_id):
    quants = odoo('stock.quant', 'search_read',
        [['location_id.usage', '=', 'internal'],
         ['location_id.company_id', '=', company_id],
         ['quantity', '>', 0]],
        fields=['product_id'], limit=0)
    if not quants:
        return set()
    pp_ids = list({q['product_id'][0] for q in quants})
    pp_recs = odoo('product.product', 'search_read',
        [['id', 'in', pp_ids]], fields=['product_tmpl_id'], limit=0)
    return {r['product_tmpl_id'][0] for r in pp_recs}

def get_product_templates(odoo, tmpl_ids):
    if not tmpl_ids:
        return []
    return odoo('product.template', 'search_read',
        [['id', 'in', list(tmpl_ids)], ['active', '=', True]],
        fields=['id', 'name', 'product_tag_ids', 'default_code', 'categ_id', 'image_1920'],
        limit=0)

def get_brand_tags(odoo, tag_ids):
    if not tag_ids:
        return {}
    # Try with image field; gracefully fall back
    for fields in [['id', 'name', 'image_1920'], ['id', 'name', 'image_128'], ['id', 'name']]:
        try:
            tags = odoo('product.tag', 'search_read',
                [['id', 'in', list(tag_ids)]], fields=fields, limit=0)
            return {t['id']: t for t in tags}
        except Exception:
            continue
    return {}

# ─────────────────────────────────────────────────────────────────────────────
# IMAGE HANDLING
# ─────────────────────────────────────────────────────────────────────────────

def process_image(b64_data, product_id, target=(420, 420)):
    cache_file = CACHE_DIR / f'p_{product_id}.b64'
    if cache_file.exists():
        return cache_file.read_text()
    if not b64_data:
        return None
    try:
        raw = base64.b64decode(b64_data)
        if HAS_PIL:
            img = Image.open(io.BytesIO(raw)).convert('RGBA')
            img.thumbnail(target, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            out = base64.b64encode(buf.getvalue()).decode()
        else:
            out = b64_data
        cache_file.write_text(out)
        return out
    except Exception as ex:
        print(f'    Warning: image error for {product_id}: {ex}')
        return None

def process_brand_image(b64_data, tag_id):
    if not b64_data:
        return None
    cache_file = CACHE_DIR / f'tag_{tag_id}.b64'
    if cache_file.exists():
        return cache_file.read_text()
    try:
        raw = base64.b64decode(b64_data)
        if HAS_PIL:
            img = Image.open(io.BytesIO(raw)).convert('RGBA')
            img.thumbnail((320, 120), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            out = base64.b64encode(buf.getvalue()).decode()
        else:
            out = b64_data
        cache_file.write_text(out)
        return out
    except Exception:
        return None

def copy_static_assets():
    """Copy font files to docs/fonts/ so GitHub Pages serves them."""
    fonts_out = OUTPUT_DIR / 'fonts'
    fonts_out.mkdir(exist_ok=True)
    for name in ['NeulisAlt-Black.otf', 'NeulisAlt-Medium.otf', 'NeulisAlt-Regular.otf']:
        src = FONTS_DIR / name
        dst = fonts_out / name
        if src.exists():
            shutil.copy2(src, dst)

def generate_index():
    """Regenerate the landing page with correct fonts and branding."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NESTU® Veterinary Product Catalogues 2026</title>
<style>
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Black.otf') format('opentype');font-weight:900;font-display:swap;}
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Medium.otf') format('opentype');font-weight:500;font-display:swap;}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{width:100%;height:100%;overflow:hidden;font-family:'NA',sans-serif;background:#3040C4;}
body{display:flex;align-items:center;justify-content:center;}
.card{background:#fff;border-radius:14px;padding:52px 60px;text-align:center;width:min(440px,90vw);}
.logo{font-size:58px;font-weight:900;color:#3040C4;letter-spacing:-.01em;line-height:1;}
.logo sup{font-size:24px;vertical-align:super;}
.sub{font-size:11px;font-weight:500;color:#9ba5cc;letter-spacing:.18em;text-transform:uppercase;margin-top:8px;margin-bottom:44px;}
.links{display:flex;flex-direction:column;gap:12px;}
a{display:block;padding:16px 24px;border-radius:8px;background:#3040C4;color:#fff;text-decoration:none;font-size:15px;font-weight:700;letter-spacing:.04em;transition:background .15s;}
a:hover{background:#2434A8;}
.tag{margin-top:32px;font-size:10px;font-weight:500;color:#c0c8e8;letter-spacing:.1em;text-transform:uppercase;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">NESTU<sup>®</sup></div>
  <div class="sub">Veterinary Product Catalogues &nbsp;·&nbsp; 2026</div>
  <div class="links">
    <a href="jordan.html">Jordan Catalogue</a>
    <a href="uae.html">UAE Catalogue</a>
    <a href="ksa.html">KSA Catalogue</a>
  </div>
  <div class="tag">Empowering Vets to Take Better Care of Our Pets</div>
</div>
</body>
</html>"""
    (OUTPUT_DIR / 'index.html').write_text(html, encoding='utf-8')
    print('  ✓ docs/index.html')


# ─────────────────────────────────────────────────────────────────────────────
# HTML HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def e(s):
    return html_mod.escape(str(s))

def trunc(name, limit=52):
    s = str(name)
    return (s[:limit-1] + '…') if len(s) > limit else s

# ─────────────────────────────────────────────────────────────────────────────
# PAGE BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def page_cover(country):
    return f'''<div class="pg cv">
<div class="cvbar"></div>
<div class="cv-in">
  <div class="cv-logo">NESTU<sup>®</sup></div>
  <div class="cvrule"></div>
  <div class="cv-ey">{e(country)}</div>
  <div class="cv-title">Veterinary Product<br>Catalogue</div>
  <div class="cv-yr">· 2026 ·</div>
</div>
<div class="cv-foot">
  <div class="cv-tag">Empowering Vets to Take Better Care of Our Pets</div>
  <div class="cv-url">nestu.health</div>
</div>
</div>'''

def page_letter(letter_text, co):
    paras = [p.strip() for p in letter_text.strip().split('\n\n') if p.strip()]
    body, closing, signoff = [], 'With warmth and respect,', 'The NESTU family'
    sign_idx = next((i for i, p in enumerate(paras)
                     if any(w in p.lower() for w in ['warmth', 'regards', 'sincerely'])), None)
    if sign_idx is not None:
        body = paras[:sign_idx]
        tail = paras[sign_idx:]
        closing = tail[0] if tail else closing
        signoff = tail[-1] if len(tail) > 1 else signoff
    else:
        body = paras
    body_html = ''.join(f'<p>{e(p)}</p>' for p in body
                        if not p.strip().lower().startswith('dear doctor'))
    return f'''<div class="pg">
<div class="lhd">
  <div class="lhd-logo">NESTU<sup>®</sup></div>
  <div class="lhd-co">
    <div class="lhd-name">{e(co["entity"])}</div>
    <div class="lhd-addr">{e(co["address"])}</div>
    <div class="lhd-addr">info@nestu.health · nestu.health</div>
  </div>
</div>
<div class="lbody">
  <div class="ldt">2026</div>
  <div class="lsal">Dear Doctor,</div>
  <div class="ltxt">{body_html}</div>
  <div class="lsign">
    <div class="lcl">{e(closing)}</div>
    <div class="lnm">{e(signoff)}</div>
  </div>
</div>
</div>'''

def page_toc(entries):
    rows = ''
    for i, entry in enumerate(entries):
        rows += (f'<li><div class="ta" onclick="gp({entry["page_idx"]})">'
                 f'<span class="tnum">{i+1:02d}</span>'
                 f'<span class="tdot"></span>'
                 f'<span class="tbn">{e(entry["brand"])}</span>'
                 f'<span class="tcnt">{entry["count"]} product{"s" if entry["count"]!=1 else ""}</span>'
                 f'<span class="tarr">→</span>'
                 f'</div></li>')
    return f'''<div class="pg">
<div class="pghd">
  <div class="pghd-l">Navigate</div>
  <div class="pghd-t">Table of Contents</div>
</div>
<div class="tbd">
  <p class="tintro">Click any brand to jump to its section. Products are sorted alphabetically within each brand.</p>
  <ul class="tlist">{rows}</ul>
</div>
</div>'''

def page_brand_divider(brand, num, total, count, logo_b64=None):
    initial = brand[0].upper()
    logo_html = ''
    if logo_b64:
        logo_html = f'<div class="bdlogo"><img src="data:image/png;base64,{logo_b64}" alt="{e(brand)}"></div>'
    return f'''<div class="pg bdiv" data-i="{e(initial)}">
<div class="bd-in">
  {logo_html}
  <div class="bdnum">Brand {num:02d} of {total:02d}</div>
  <div class="bdname">{e(brand)}</div>
  <div class="bdrule"></div>
  <div class="bdcnt">{count} Product{"s" if count!=1 else ""} Available</div>
</div>
</div>'''

def page_products(brand, products, page_num, total_pages):
    cards = ''
    for p in products:
        name = e(trunc(p.get('name', '')))
        ref  = e(p.get('default_code') or '')
        cat  = e((p.get('categ_id') or [False, ''])[1] or '')
        img  = p.get('_img')
        img_html = (f'<img src="data:image/png;base64,{img}" alt="{name}">'
                    if img else f'<span class="pcph">{e(str(p.get("name","P"))[0].upper())}</span>')
        cards += (f'<div class="pc"><div class="pcimg">{img_html}</div>'
                  f'<div class="pcinf">'
                  f'<div class="pcnm">{name}</div>'
                  f'{f"""<div class="pccat">{cat}</div>""" if cat else ""}'
                  f'{f"""<div class="pcref">{ref}</div>""" if ref else ""}'
                  f'</div></div>')
    pag = f'{e(brand)} &nbsp;·&nbsp; {page_num} / {total_pages}' if total_pages > 1 else e(brand)
    return f'''<div class="pg">
<div class="pphd">
  <span class="ppbrand">{e(brand)}</span>
  <span class="pplogo">NESTU<sup>®</sup></span>
</div>
<div class="ppgrid">{cards}</div>
<div class="pppage">{pag}</div>
</div>'''

def page_closing():
    return '''<div class="pg cls">
<div class="cvbar"></div>
<div class="cv-in">
  <div class="cv-logo">NESTU<sup>®</sup></div>
  <div class="cvrule"></div>
  <div class="cv-tag2">Empowering Vets to Take<br>Better Care of Our Pets</div>
</div>
<div class="cv-foot">
  <div class="cv-url">nestu.health &nbsp;·&nbsp; info@nestu.health</div>
  <div class="cv-tag">© 2026 NESTU Ltd. &nbsp;·&nbsp; Jordan &nbsp;·&nbsp; UAE &nbsp;·&nbsp; KSA</div>
</div>
</div>'''

# ─────────────────────────────────────────────────────────────────────────────
# CSS  (fonts loaded as files from docs/fonts/)
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Black.otf') format('opentype');font-weight:900;font-display:swap;}
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Medium.otf') format('opentype');font-weight:500;font-display:swap;}
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Regular.otf') format('opentype');font-weight:400;font-display:swap;}

*{box-sizing:border-box;margin:0;padding:0;}
:root{--blue:#3040C4;--bdk:#2434A8;--g50:#f8f9fc;--g100:#eef0f8;--g200:#e0e4f2;--g400:#9ba5cc;--g600:#5f6d9e;--tx:#1a2040;}

html,body{width:100%;height:100%;overflow:hidden;font-family:'NA',sans-serif;background:#c8cedf;}

/* ── Viewer fills entire viewport ── */
.viewer{width:100vw;height:100dvh;display:flex;flex-direction:column;}

/* ── Stage: fills space above nav ── */
.stage-outer{flex:1;min-height:0;display:flex;justify-content:center;align-items:center;padding:8px;}
.stage{transform-origin:center center;}
.pw{width:820px;height:1160px;position:relative;overflow:hidden;box-shadow:0 4px 28px rgba(30,36,72,0.25);}

/* ── Bottom nav ── */
.nav{height:52px;background:var(--blue);flex-shrink:0;display:flex;align-items:center;padding:0 14px;gap:10px;}
.nb{background:rgba(255,255,255,.18);color:#fff;border:none;width:36px;height:36px;border-radius:50%;font-size:17px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;flex-shrink:0;font-family:'NA',sans-serif;}
.nb:disabled{opacity:.3;cursor:default;}
.nb:not(:disabled):hover{background:rgba(255,255,255,.28);}
.nav-mid{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px;}
.nav-brand{font-size:11px;font-weight:700;color:rgba(255,255,255,.75);letter-spacing:.04em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.nav-track{height:2px;background:rgba(255,255,255,.2);border-radius:1px;}
.nav-fill{height:100%;background:#fff;border-radius:1px;transition:width .3s;}
.nav-pg{font-size:10px;color:rgba(255,255,255,.5);white-space:nowrap;flex-shrink:0;}

/* ── All pages ── */
.pg{position:absolute;inset:0;background:#fff;display:none;flex-direction:column;font-family:'NA',sans-serif;}
.pg.on{display:flex;}

/* ── Flip animations ── */
@keyframes fxL{0%{transform:perspective(1400px) rotateY(0);opacity:1;}100%{transform:perspective(1400px) rotateY(-82deg);opacity:0;}}
@keyframes feR{0%{transform:perspective(1400px) rotateY(82deg);opacity:0;}100%{transform:perspective(1400px) rotateY(0);opacity:1;}}
@keyframes fxR{0%{transform:perspective(1400px) rotateY(0);opacity:1;}100%{transform:perspective(1400px) rotateY(82deg);opacity:0;}}
@keyframes feL{0%{transform:perspective(1400px) rotateY(-82deg);opacity:0;}100%{transform:perspective(1400px) rotateY(0);opacity:1;}}
.pg.fxl{display:flex!important;animation:fxL .32s ease-in forwards;}
.pg.fxr{display:flex!important;animation:fxR .32s ease-in forwards;}
.pg.fer{display:flex!important;animation:feR .32s ease-out;}
.pg.fel{display:flex!important;animation:feL .32s ease-out;}

/* ── COVER ── */
.cv{background:var(--blue)!important;align-items:center;justify-content:center;}
.cv::after{content:'N';position:absolute;bottom:-45px;right:-18px;font-family:'NA';font-weight:900;font-size:600px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}
.cvbar{position:absolute;top:0;left:0;right:0;height:5px;background:rgba(255,255,255,.22);}
.cv-in{text-align:center;position:relative;z-index:1;}
.cv-logo{font-size:92px;font-weight:900;color:#fff;line-height:1;letter-spacing:-.01em;}
.cv-logo sup{font-size:36px;vertical-align:super;}
.cvrule{width:62px;height:3px;background:rgba(255,255,255,.32);margin:24px auto 18px;}
.cv-ey{font-size:11px;font-weight:500;color:rgba(255,255,255,.55);letter-spacing:.22em;text-transform:uppercase;margin-bottom:10px;}
.cv-title{font-size:32px;font-weight:900;color:#fff;letter-spacing:.05em;text-transform:uppercase;line-height:1.2;}
.cv-yr{font-size:13px;font-weight:400;color:rgba(255,255,255,.5);letter-spacing:.3em;margin-top:10px;}
.cv-foot{position:absolute;bottom:44px;left:0;right:0;text-align:center;z-index:1;}
.cv-tag{font-size:10px;font-weight:500;color:rgba(255,255,255,.4);letter-spacing:.12em;text-transform:uppercase;}
.cv-url{font-size:12px;font-weight:700;color:rgba(255,255,255,.68);margin-top:7px;}
.cv-tag2{font-size:13px;font-weight:500;color:rgba(255,255,255,.65);letter-spacing:.1em;text-transform:uppercase;text-align:center;line-height:1.65;}

/* ── LETTER ── */
.lhd{padding:30px 52px 22px;border-bottom:1.5px solid var(--g100);display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.lhd-logo{font-size:28px;font-weight:900;color:var(--blue);}
.lhd-logo sup{font-size:12px;vertical-align:super;}
.lhd-co{text-align:right;}
.lhd-name{font-size:9.5px;font-weight:700;color:var(--blue);letter-spacing:.05em;text-transform:uppercase;line-height:1.55;}
.lhd-addr{font-size:9.5px;color:var(--g600);line-height:1.65;margin-top:2px;}
.lbody{padding:36px 52px;flex:1;overflow:hidden;}
.ldt{font-size:12px;color:var(--g600);margin-bottom:24px;}
.lsal{font-size:19px;font-weight:900;color:var(--blue);margin-bottom:16px;}
.ltxt{font-size:13.5px;line-height:1.9;color:var(--tx);text-align:justify;}
.ltxt p{margin-bottom:13px;}
.lsign{margin-top:32px;}
.lcl{font-size:13px;color:var(--tx);margin-bottom:28px;font-style:italic;}
.lnm{font-size:15px;font-weight:900;color:var(--blue);}

/* ── TOC ── */
.pghd{background:var(--blue);padding:28px 52px;flex-shrink:0;}
.pghd-l{font-size:10px;font-weight:700;color:rgba(255,255,255,.5);letter-spacing:.22em;text-transform:uppercase;margin-bottom:6px;}
.pghd-t{font-size:26px;font-weight:900;color:#fff;letter-spacing:.03em;}
.tbd{padding:28px 52px;flex:1;overflow:hidden;}
.tintro{font-size:12px;color:var(--g600);margin-bottom:22px;line-height:1.65;}
.tlist{list-style:none;}
.ta{display:flex;align-items:center;padding:11px 0;border-bottom:0.5px solid var(--g100);cursor:pointer;}
.ta:last-child{border-bottom:none;}
.ta:hover .tbn{color:var(--blue);}
.tnum{font-size:10px;font-weight:700;color:var(--g400);letter-spacing:.08em;width:26px;flex-shrink:0;}
.tdot{width:8px;height:8px;border-radius:50%;background:var(--blue);flex-shrink:0;margin-right:14px;}
.tbn{font-size:15px;font-weight:700;color:var(--tx);flex:1;transition:color .15s;}
.tcnt{font-size:11px;color:var(--g400);font-weight:500;margin-right:12px;}
.tarr{color:var(--blue);font-size:14px;font-weight:700;}

/* ── BRAND DIVIDER ── */
.bdiv{background:var(--blue)!important;align-items:center;justify-content:center;}
.bdiv::before{content:attr(data-i);position:absolute;font-family:'NA';font-weight:900;font-size:520px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}
.bd-in{text-align:center;position:relative;z-index:1;}
.bdlogo{margin-bottom:20px;}
.bdlogo img{max-width:180px;max-height:60px;object-fit:contain;filter:brightness(0) invert(1);opacity:.85;}
.bdnum{font-size:11px;font-weight:700;color:rgba(255,255,255,.48);letter-spacing:.22em;text-transform:uppercase;margin-bottom:18px;}
.bdname{font-size:72px;font-weight:900;color:#fff;letter-spacing:.04em;line-height:1.05;}
.bdrule{width:50px;height:2px;background:rgba(255,255,255,.32);margin:20px auto;}
.bdcnt{font-size:13px;color:rgba(255,255,255,.6);font-weight:500;letter-spacing:.06em;}

/* ── PRODUCT PAGE ── */
.pphd{background:var(--blue);padding:12px 36px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.ppbrand{font-size:15px;font-weight:900;color:#fff;letter-spacing:.08em;text-transform:uppercase;}
.pplogo{font-size:15px;font-weight:900;color:rgba(255,255,255,.5);}
.pplogo sup{font-size:7px;vertical-align:super;}
.ppgrid{flex:1;padding:18px 30px;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(2,1fr);gap:14px;}
.pc{border:0.5px solid var(--g200);border-radius:7px;overflow:hidden;display:flex;flex-direction:column;transition:border-color .15s;}
.pc:hover{border-color:var(--blue);}
.pcimg{background:var(--g50);display:flex;align-items:center;justify-content:center;aspect-ratio:1;border-bottom:0.5px solid var(--g100);flex-shrink:0;overflow:hidden;}
.pcimg img{width:100%;height:100%;object-fit:contain;padding:10px;}
.pcph{font-family:'NA';font-size:48px;font-weight:900;color:var(--g200);}
.pcinf{padding:9px 10px 10px;display:flex;flex-direction:column;justify-content:flex-start;flex:1;}
.pcnm{font-size:11.5px;font-weight:700;color:var(--tx);line-height:1.3;margin-bottom:3px;}
.pccat{font-size:9.5px;color:var(--blue);font-weight:700;letter-spacing:.02em;margin-bottom:2px;}
.pcref{font-size:9px;color:var(--g400);letter-spacing:.03em;}
.pppage{padding:8px 36px;text-align:center;font-size:9px;color:var(--g400);flex-shrink:0;}

/* ── CLOSING ── */
.cls{background:var(--blue)!important;align-items:center;justify-content:center;}
.cls::after{content:'N';position:absolute;bottom:-45px;right:-18px;font-family:'NA';font-weight:900;font-size:600px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}

/* ── PRINT ── */
@media print{
  html,body{overflow:visible;height:auto;}
  .viewer{height:auto;}
  .stage-outer{display:block;}
  .stage{transform:none!important;width:210mm!important;height:auto!important;}
  .pw{width:210mm!important;height:auto!important;box-shadow:none;}
  .pg{display:flex!important;position:relative;page-break-after:always;min-height:297mm;}
  .nav{display:none;}
}
"""

JS = """
const N = __N__;
const PI = __PI__;
let c = 0, bz = false;

function resize() {
  const PW = 820, PH = 1160;
  const outer = document.querySelector('.stage-outer');
  const r = outer.getBoundingClientRect();
  const scale = Math.min(r.width / PW, r.height / PH) * 0.98;
  const stage = document.querySelector('.stage');
  stage.style.width = PW + 'px';
  stage.style.height = PH + 'px';
  stage.style.transform = `scale(${scale})`;
}
window.addEventListener('resize', resize);
window.addEventListener('orientationchange', () => setTimeout(resize, 100));

function upd() {
  document.getElementById('bp').disabled = c === 0;
  document.getElementById('bn').disabled = c === N - 1;
  const info = PI[c] || {};
  document.getElementById('nb').textContent = info.label || '';
  document.getElementById('npg').textContent = `${c + 1} / ${N}`;
  document.getElementById('nfill').style.width = ((c + 1) / N * 100).toFixed(1) + '%';
}

function fl(dir) {
  if (bz) return;
  const nx = c + dir;
  if (nx < 0 || nx >= N) return;
  bz = true;
  const all = document.querySelectorAll('.pg');
  const ce = all[c], ne = all[nx];
  const ec = dir > 0 ? 'fxl' : 'fxr', en = dir > 0 ? 'fer' : 'fel';
  ce.classList.add(ec); ne.classList.add(en, 'on');
  setTimeout(() => { ce.classList.remove('on', ec); ne.classList.remove(en); c = nx; upd(); bz = false; }, 320);
}

function gp(n) {
  if (bz || n === c) return;
  const dir = n > c ? 1 : -1; bz = true;
  const all = document.querySelectorAll('.pg');
  const ce = all[c], ne = all[n];
  const ec = dir > 0 ? 'fxl' : 'fxr', en = dir > 0 ? 'fer' : 'fel';
  ce.classList.add(ec); ne.classList.add(en, 'on');
  setTimeout(() => { ce.classList.remove('on', ec); ne.classList.remove(en); c = n; upd(); bz = false; }, 320);
}

document.addEventListener('keydown', e => { if (e.key === 'ArrowRight') fl(1); if (e.key === 'ArrowLeft') fl(-1); });

// Touch/swipe
let tx = 0;
document.querySelector('.pw').addEventListener('touchstart', e => { tx = e.touches[0].clientX; }, {passive:true});
document.querySelector('.pw').addEventListener('touchend', e => {
  const dx = e.changedTouches[0].clientX - tx;
  if (Math.abs(dx) > 40) fl(dx < 0 ? 1 : -1);
}, {passive:true});

document.querySelectorAll('.pg')[0].classList.add('on');
resize();
upd();
"""

def build_html(pages, page_info, company_info, updated_at):
    N = len(pages)
    pi_json = json.dumps(page_info, ensure_ascii=False)
    js = JS.replace('__N__', str(N)).replace('__PI__', pi_json)
    pages_html = '\n'.join(pages)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>NESTU® {e(company_info['name'])} — Veterinary Product Catalogue 2026</title>
<style>{CSS}</style>
</head>
<body>
<div class="viewer">
  <div class="stage-outer">
    <div class="stage">
      <div class="pw">
{pages_html}
      </div>
    </div>
  </div>
  <div class="nav">
    <button class="nb" id="bp" onclick="fl(-1)" disabled>&#8592;</button>
    <div class="nav-mid">
      <div class="nav-brand" id="nb">Cover</div>
      <div class="nav-track"><div class="nav-fill" id="nfill" style="width:2%"></div></div>
    </div>
    <div class="nav-pg" id="npg">1 / {N}</div>
    <button class="nb" id="bn" onclick="fl(1)">&#8594;</button>
  </div>
</div>
<script>{js}</script>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def should_exclude(p):
    categ_id = (p.get('categ_id') or [False])[0]
    if categ_id and categ_id in EXCLUDE_CATEG_IDS:
        return True
    name = (p.get('name') or '').lower()
    if any(k.lower() in name for k in EXCLUDE_NAME_CONTAINS):
        return True
    ref = (p.get('default_code') or '').upper()
    name_lower = (p.get('name') or '').lower()
    for prefix, keyword in EXCLUDE_CODE_AND_NAME:
        if ref.startswith(prefix.upper()) and keyword.lower() in name_lower:
            return True
    return False

def generate_company(odoo, slug, dear_doctor):
    co = COMPANIES[slug]
    print(f'\n{"─"*56}')
    print(f'  {co["name"]}  (company_id={co["id"]})')
    print(f'{"─"*56}')

    tmpl_ids = get_in_stock_tmpl_ids(odoo, co['id'])
    print(f'  In-stock templates: {len(tmpl_ids)}')
    if not tmpl_ids:
        print('  SKIP — no in-stock products')
        return []

    products = get_product_templates(odoo, tmpl_ids)

    all_tag_ids = set()
    for p in products:
        all_tag_ids.update(p.get('product_tag_ids', []))
    brand_map = get_brand_tags(odoo, all_tag_ids)

    brand_products = {}
    missing_images = []
    excluded = 0

    for p in products:
        if should_exclude(p):
            excluded += 1
            continue
        tids = p.get('product_tag_ids', [])
        if not p.get('image_1920'):
            missing_images.append(p.get('name', f"ID:{p['id']}"))
        else:
            p['_img'] = process_image(p['image_1920'], p['id'])

        primary = next((brand_map[t]['name'] for t in tids if t in brand_map), None)
        if primary:
            brand_products.setdefault(primary, []).append(p)

    if excluded:
        print(f'  Excluded (filter): {excluded}')

    # Sort
    sorted_brands = sorted(brand_products, key=str.lower)
    for bn in sorted_brands:
        brand_products[bn].sort(key=lambda x: (x.get('name') or '').lower())

    # Report missing images
    if missing_images:
        print(f'\n  ⚠ MISSING IMAGES ({len(missing_images)}):')
        for nm in sorted(missing_images):
            print(f'      • {nm}')
    else:
        print(f'  ✓ All products have images')

    # Build pages + page_info
    pages = []
    page_info = []

    pages.append(page_cover(co['name']))
    page_info.append({'label': 'Cover'})

    pages.append(page_letter(dear_doctor, co))
    page_info.append({'label': 'Dear Doctor'})

    toc_idx = len(pages)
    pages.append('')
    page_info.append({'label': 'Contents'})

    toc_entries = []
    for b_idx, brand in enumerate(sorted_brands):
        prods = brand_products[brand]
        divider_idx = len(pages)
        toc_entries.append({'brand': brand, 'count': len(prods), 'page_idx': divider_idx})

        # Brand logo
        tag_data = next((brand_map[t] for t in brand_map
                         if brand_map[t].get('name') == brand), None)
        logo_b64 = None
        if tag_data:
            raw_img = tag_data.get('image_1920') or tag_data.get('image_128')
            if raw_img:
                tid = next((k for k, v in brand_map.items() if v.get('name') == brand), 0)
                logo_b64 = process_brand_image(raw_img, tid)

        pages.append(page_brand_divider(brand, b_idx+1, len(sorted_brands), len(prods), logo_b64))
        page_info.append({'label': brand})

        chunks = [prods[i:i+PRODUCTS_PER_PAGE] for i in range(0, len(prods), PRODUCTS_PER_PAGE)]
        for ci, chunk in enumerate(chunks):
            pages.append(page_products(brand, chunk, ci+1, len(chunks)))
            pg_label = f'{brand} · {ci+1}/{len(chunks)}' if len(chunks) > 1 else brand
            page_info.append({'label': pg_label})

    pages[toc_idx] = page_toc(toc_entries)
    pages.append(page_closing())
    page_info.append({'label': ''})

    N = len(pages)
    updated_at = datetime.now().strftime('%d %b %Y · %H:%M AST')
    html = build_html(pages, page_info, co, updated_at)

    out_path = OUTPUT_DIR / f'{slug}.html'
    out_path.write_text(html, encoding='utf-8')
    print(f'  ✓ docs/{slug}.html — {N} pages, {len(html)//1024} KB')
    return missing_images


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    target_slugs = args if args else list(COMPANIES.keys())
    invalid = [s for s in target_slugs if s not in COMPANIES]
    if invalid:
        raise SystemExit(f'Unknown slugs: {invalid}')

    # Copy fonts to docs/fonts/ (served by GitHub Pages)
    print('Copying static assets...')
    copy_static_assets()
    generate_index()

    # Load dear doctor
    dp = CONFIG_DIR / 'dear_doctor.txt'
    dear_doctor = dp.read_text(encoding='utf-8') if dp.exists() else 'With warmth and respect,\n\nThe NESTU family'

    odoo = connect_odoo()

    all_missing = {}
    for slug in target_slugs:
        if slug not in COMPANIES:
            continue
        missing = generate_company(odoo, slug, dear_doctor)
        if missing:
            all_missing[slug] = missing

    print(f'\n{"═"*56}')
    if all_missing:
        print('⚠ PRODUCTS MISSING IMAGES — add in Odoo > Products:')
        for slug, names in all_missing.items():
            print(f'\n  {COMPANIES[slug]["name"]}:')
            for nm in sorted(names):
                print(f'    • {nm}')
    else:
        print('✓ All products have images')

    print('\n✓ Done')


if __name__ == '__main__':
    main()

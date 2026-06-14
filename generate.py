#!/usr/bin/env python3
"""
NESTU® Product Catalogue Generator
Generates live HTML flipbook catalogues for Jordan, UAE, and KSA
from real-time Odoo 17 stock data.

Usage:
  python generate.py              # Generate all three countries
  python generate.py jordan       # One country only
  python generate.py --check      # Report missing images, no HTML output

Setup:
  1. Copy fonts to ./fonts/ (NeulisAlt-Black.otf, NeulisAlt-Medium.otf, NeulisAlt-Regular.otf)
  2. Run python setup_assets.py   (processes logo once)
  3. Set env vars: ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY
  4. python generate.py
"""

import xmlrpc.client
import base64
import os
import sys
import re
import io
import html as html_mod
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ──────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────

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

PRODUCTS_PER_PAGE = 6   # 3 cols × 2 rows — change to 9 for 3×3

COMPANIES = {
    'jordan': {
        'id': 2, 'name': 'Jordan', 'slug': 'jordan',
        'entity': 'The Nest for Specialized Veterinary Therapeutics & Utilities Ltd. · NESTU Jordan',
        'address': 'Oweym Ben Saeda St., Bldg. No. 46 · Amman, Jordan',
    },
    'uae': {
        'id': 3, 'name': 'UAE', 'slug': 'uae',
        'entity': 'NESTU Veterinary Medicines Trading L.L.C · NESTU UAE',
        'address': 'Office 602, North Tower, Dubai Science Park · Dubai, UAE',
    },
    'ksa': {
        'id': 4, 'name': 'KSA', 'slug': 'ksa',
        'entity': 'NESTU KSA',
        'address': 'Kingdom of Saudi Arabia',
    },
}

# ──────────────────────────────────────────────────────
# ODOO
# ──────────────────────────────────────────────────────

def connect_odoo():
    common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common', allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_KEY, {})
    if not uid:
        raise SystemExit('ERROR: Odoo authentication failed. Check ODOO_USERNAME / ODOO_API_KEY.')
    models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)
    def call(model, method, *args, **kwargs):
        return models.execute_kw(ODOO_DB, uid, ODOO_KEY, model, method, list(args), kwargs)
    print(f'✓ Odoo connected (uid={uid})')
    return call

def get_in_stock_tmpl_ids(odoo, company_id):
    """Return set of product.template IDs with on-hand qty > 0 for this company."""
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
    tags = odoo('product.tag', 'search_read',
        [['id', 'in', list(tag_ids)]], fields=['id', 'name'], limit=0)
    return {t['id']: t['name'] for t in tags}

# ──────────────────────────────────────────────────────
# IMAGE HANDLING
# ──────────────────────────────────────────────────────

def process_image(b64_data, product_id, target=(420, 420)):
    """Resize Odoo image, cache result, return base64 PNG."""
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
    except Exception as e:
        print(f'    Warning: image error for product {product_id}: {e}')
        return None

def load_b64(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'Missing required file: {p}')
    return base64.b64encode(p.read_bytes()).decode()

# ──────────────────────────────────────────────────────
# HTML PAGE BUILDERS
# ──────────────────────────────────────────────────────

def e(s):
    return html_mod.escape(str(s))

def truncate(name, limit=58):
    s = str(name)
    return (s[:limit-1] + '…') if len(s) > limit else s

def page_cover(country, logo_white_b64):
    return f'''<div class="pg cv">
<div class="cvbar"></div>
<div class="cv-in">
  <div class="cvlogo"><img src="data:image/png;base64,{logo_white_b64}" alt="NESTU®"></div>
  <div class="cvrule"></div>
  <div class="cvey">{e(country)}</div>
  <div class="cvtit">Veterinary Product<br>Catalogue</div>
  <div class="cvyr">· 2026 ·</div>
</div>
<div class="cvfoot">
  <div class="cvtag">Empowering Vets to Take Better Care of Our Pets</div>
  <div class="cvurl">nestu.health</div>
</div>
</div>'''

def page_letter(letter_text, logo_blue_b64, co):
    # Parse letter: split on blank lines, strip Dear Doctor line, extract sign-off
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
  <div class="lhd-l"><img src="data:image/png;base64,{logo_blue_b64}" alt="NESTU®"></div>
  <div class="lco">
    <div class="lco-n">{e(co["entity"])}</div>
    <div class="lco-d">{e(co["address"])}</div>
    <div class="lco-d">info@nestu.health · nestu.health</div>
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
<div class="lft">
  <span>NESTU® · Companion Animal Health Distribution</span>
  <span>For Healthcare Professionals Only</span>
</div>
</div>'''

def page_toc(entries):
    # entries: list of {brand, count, page_idx}
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
  <p class="tintro">Click any brand to jump directly to its section. Products are sorted alphabetically within each brand. Availability reflects live stock as of the last refresh.</p>
  <ul class="tlist">{rows}</ul>
</div>
<div class="lft">
  <span>NESTU® Veterinary Product Catalogue 2026</span>
  <span>Stock data live from Odoo</span>
</div>
</div>'''

def page_brand_divider(brand, num, total, count):
    initial = brand[0].upper()
    return f'''<div class="pg bdiv" data-i="{e(initial)}">
<div class="bd-in">
  <div class="bdnum">Brand {num:02d} of {total:02d}</div>
  <div class="bdname">{e(brand)}</div>
  <div class="bdrule"></div>
  <div class="bdcnt">{count} Product{"s" if count!=1 else ""} Available</div>
</div>
</div>'''

def page_products(brand, products, page_num, total_pages, logo_white_b64):
    cards = ''
    for p in products:
        name = e(truncate(p.get('name', '')))
        ref  = e(p.get('default_code') or '')
        cat  = e((p.get('categ_id') or [False, ''])[1] or '')
        img  = p.get('_img')
        img_html = (f'<img src="data:image/png;base64,{img}" alt="{name}">'
                    if img else f'<span class="pcph">{e(str(p.get("name","P"))[0].upper())}</span>')
        cards += (f'<div class="pc">'
                  f'<div class="pcimg">{img_html}</div>'
                  f'<div class="pcinf">'
                  f'<div class="pcnm">{name}</div>'
                  f'{f"""<div class="pccat">{cat}</div>""" if cat else ""}'
                  f'{f"""<div class="pcref">{ref}</div>""" if ref else ""}'
                  f'</div></div>')
    pag = f'{e(brand)} · {page_num} of {total_pages}' if total_pages > 1 else e(brand)
    return f'''<div class="pg">
<div class="pphd">
  <span class="ppbrand">{e(brand)}</span>
  <span class="pplogo"><img src="data:image/png;base64,{logo_white_b64}" alt="NESTU®"></span>
</div>
<div class="ppgrid">{cards}</div>
<div class="ppft">
  <span>{pag}</span>
  <span>NESTU® · 2026</span>
</div>
</div>'''

def page_closing(logo_white_b64):
    return f'''<div class="pg cls">
<div class="cvbar"></div>
<div class="cv-in">
  <div class="cvlogo"><img src="data:image/png;base64,{logo_white_b64}" alt="NESTU®"></div>
  <div class="cvrule"></div>
  <div class="cvtag2">Empowering Vets to Take<br>Better Care of Our Pets</div>
</div>
<div class="cvfoot">
  <div class="cvurl">nestu.health · info@nestu.health</div>
  <div class="cvtag">© 2026 NESTU Ltd. · Jordan · UAE · KSA</div>
</div>
</div>'''

# ──────────────────────────────────────────────────────
# CSS + JS TEMPLATE
# ──────────────────────────────────────────────────────

CSS = """
@font-face{font-family:'NA';src:url('data:font/otf;base64,__FONT_B__') format('opentype');font-weight:900;}
@font-face{font-family:'NA';src:url('data:font/otf;base64,__FONT_M__') format('opentype');font-weight:500;}
@font-face{font-family:'NA';src:url('data:font/otf;base64,__FONT_R__') format('opentype');font-weight:400;}
*{box-sizing:border-box;margin:0;padding:0;}
:root{--blue:#3040C4;--bdk:#2434A8;--g50:#f8f9fc;--g100:#eef0f8;--g200:#e0e4f2;--g400:#9ba5cc;--g600:#5f6d9e;--tx:#1a2040;}
body{font-family:'NA',sans-serif;background:#c8cedf;}
.viewer{display:flex;flex-direction:column;align-items:center;padding:20px 0 40px;gap:14px;}
.topbar{width:820px;background:var(--blue);padding:12px 22px;border-radius:7px;display:flex;justify-content:space-between;align-items:center;}
.tbl{color:#fff;font-family:'NA';font-weight:900;font-size:19px;letter-spacing:.02em;}
.tbl sup{font-size:10px;vertical-align:super;}
.tbm{color:rgba(255,255,255,.72);font-size:12px;font-weight:500;letter-spacing:.05em;}
.tbd{color:rgba(255,255,255,.44);font-size:11px;}
.stage{width:820px;}
.pw{position:relative;width:820px;height:1160px;overflow:hidden;}
.pg{position:absolute;top:0;left:0;width:100%;height:100%;background:#fff;border:0.5px solid #dde;overflow:hidden;display:none;flex-direction:column;font-family:'NA',sans-serif;}
.pg.on{display:flex;}
@keyframes fxL{0%{transform:perspective(1400px) rotateY(0);opacity:1;}100%{transform:perspective(1400px) rotateY(-82deg);opacity:0;}}
@keyframes feR{0%{transform:perspective(1400px) rotateY(82deg);opacity:0;}100%{transform:perspective(1400px) rotateY(0);opacity:1;}}
@keyframes fxR{0%{transform:perspective(1400px) rotateY(0);opacity:1;}100%{transform:perspective(1400px) rotateY(82deg);opacity:0;}}
@keyframes feL{0%{transform:perspective(1400px) rotateY(-82deg);opacity:0;}100%{transform:perspective(1400px) rotateY(0);opacity:1;}}
.pg.fxl{display:flex!important;animation:fxL .35s ease-in forwards;}
.pg.fxr{display:flex!important;animation:fxR .35s ease-in forwards;}
.pg.fer{display:flex!important;animation:feR .35s ease-out;}
.pg.fel{display:flex!important;animation:feL .35s ease-out;}
.nav{width:820px;display:flex;align-items:center;justify-content:space-between;}
.nb{background:var(--blue);color:#fff;border:none;width:44px;height:44px;border-radius:50%;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s,opacity .15s;}
.nb:disabled{opacity:.28;cursor:default;}
.nb:not(:disabled):hover{background:var(--bdk);}
.nm{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--g600);font-weight:500;}
.dots{display:flex;gap:5px;flex-wrap:wrap;max-width:440px;justify-content:center;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--g200);cursor:pointer;transition:background .15s;}
.dot.on{background:var(--blue);}
.cv{background:var(--blue)!important;align-items:center;justify-content:center;border-color:var(--blue);}
.cv::after{content:'N';position:absolute;bottom:-45px;right:-18px;font-family:'NA';font-weight:900;font-size:600px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}
.cvbar{position:absolute;top:0;left:0;right:0;height:6px;background:rgba(255,255,255,.22);}
.cv-in{text-align:center;position:relative;z-index:1;}
.cvlogo{margin:0 auto 28px;}.cvlogo img{width:270px;display:block;margin:auto;}
.cvrule{width:64px;height:3px;background:rgba(255,255,255,.32);margin:0 auto 20px;}
.cvey{font-size:12px;font-weight:500;color:rgba(255,255,255,.55);letter-spacing:.22em;text-transform:uppercase;margin-bottom:12px;}
.cvtit{font-size:34px;font-weight:900;color:#fff;letter-spacing:.05em;text-transform:uppercase;line-height:1.2;}
.cvyr{font-size:14px;font-weight:400;color:rgba(255,255,255,.5);letter-spacing:.3em;margin-top:12px;}
.cvfoot{position:absolute;bottom:44px;left:0;right:0;text-align:center;z-index:1;}
.cvtag{font-size:10px;font-weight:500;color:rgba(255,255,255,.4);letter-spacing:.13em;text-transform:uppercase;}
.cvtag2{font-size:14px;font-weight:500;color:rgba(255,255,255,.65);letter-spacing:.1em;text-transform:uppercase;text-align:center;line-height:1.65;}
.cvurl{font-size:13px;font-weight:700;color:rgba(255,255,255,.7);margin-top:7px;}
.lhd{padding:34px 56px 24px;border-bottom:1.5px solid var(--g100);display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.lhd-l img{width:130px;}
.lco{text-align:right;}
.lco-n{font-size:9.5px;font-weight:700;color:var(--blue);letter-spacing:.05em;text-transform:uppercase;line-height:1.55;}
.lco-d{font-size:9.5px;color:var(--g600);line-height:1.65;margin-top:2px;}
.lbody{padding:40px 56px;flex:1;overflow:hidden;}
.ldt{font-size:12px;color:var(--g600);margin-bottom:28px;}
.lsal{font-size:20px;font-weight:900;color:var(--blue);margin-bottom:18px;}
.ltxt{font-size:13.5px;line-height:1.9;color:var(--tx);text-align:justify;}
.ltxt p{margin-bottom:14px;}
.lsign{margin-top:36px;}
.lcl{font-size:13.5px;color:var(--tx);margin-bottom:30px;font-style:italic;}
.lnm{font-size:16px;font-weight:900;color:var(--blue);}
.lft{padding:16px 56px;border-top:0.5px solid var(--g200);display:flex;justify-content:space-between;flex-shrink:0;}
.lft span{font-size:10px;color:var(--g400);}
.pghd{background:var(--blue);padding:30px 56px;flex-shrink:0;}
.pghd-l{font-size:10px;font-weight:700;color:rgba(255,255,255,.5);letter-spacing:.22em;text-transform:uppercase;margin-bottom:6px;}
.pghd-t{font-size:27px;font-weight:900;color:#fff;letter-spacing:.03em;}
.tbd{padding:32px 56px;flex:1;overflow:hidden;}
.tintro{font-size:12.5px;color:var(--g600);margin-bottom:26px;line-height:1.65;}
.tlist{list-style:none;}
.ta{display:flex;align-items:center;padding:14px 0;border-bottom:0.5px solid var(--g100);cursor:pointer;}
.ta:last-child{border-bottom:none;}
.ta:hover .tbn{color:var(--blue);}
.tnum{font-size:10px;font-weight:700;color:var(--g400);letter-spacing:.08em;width:28px;flex-shrink:0;}
.tdot{width:9px;height:9px;border-radius:50%;background:var(--blue);flex-shrink:0;margin-right:16px;}
.tbn{font-size:16px;font-weight:700;color:var(--tx);flex:1;transition:color .15s;}
.tcnt{font-size:12px;color:var(--g400);font-weight:500;margin-right:14px;}
.tarr{color:var(--blue);font-size:15px;font-weight:700;}
.bdiv{background:var(--blue)!important;border-color:var(--blue);align-items:center;justify-content:center;}
.bdiv::before{content:attr(data-i);position:absolute;font-family:'NA';font-weight:900;font-size:520px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}
.bd-in{text-align:center;position:relative;z-index:1;}
.bdnum{font-size:11px;font-weight:700;color:rgba(255,255,255,.48);letter-spacing:.22em;text-transform:uppercase;margin-bottom:20px;}
.bdname{font-size:74px;font-weight:900;color:#fff;letter-spacing:.04em;line-height:1.05;}
.bdrule{width:52px;height:2px;background:rgba(255,255,255,.32);margin:22px auto;}
.bdcnt{font-size:14px;color:rgba(255,255,255,.6);font-weight:500;letter-spacing:.06em;}
.pphd{background:var(--blue);padding:14px 40px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.ppbrand{font-size:16px;font-weight:900;color:#fff;letter-spacing:.08em;text-transform:uppercase;}
.pplogo img{width:75px;filter:brightness(0) invert(1);opacity:.55;}
.ppgrid{flex:1;padding:24px 36px;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(2,1fr);gap:16px;}
.pc{border:0.5px solid var(--g200);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;transition:border-color .15s;}
.pc:hover{border-color:var(--blue);}
.pcimg{background:var(--g50);display:flex;align-items:center;justify-content:center;aspect-ratio:1;border-bottom:0.5px solid var(--g100);flex-shrink:0;overflow:hidden;}
.pcimg img{width:100%;height:100%;object-fit:contain;padding:12px;}
.pcph{font-family:'NA';font-size:54px;font-weight:900;color:var(--g200);}
.pcinf{padding:11px 12px 13px;flex:1;display:flex;flex-direction:column;}
.pcnm{font-size:12px;font-weight:700;color:var(--tx);line-height:1.35;margin-bottom:3px;}
.pccat{font-size:10px;color:var(--blue);font-weight:700;letter-spacing:.02em;margin-bottom:3px;}
.pcref{font-size:9px;color:var(--g400);letter-spacing:.03em;}
.ppft{padding:10px 40px;border-top:0.5px solid var(--g200);display:flex;justify-content:space-between;flex-shrink:0;}
.ppft span{font-size:10px;color:var(--g400);}
.cls{background:var(--blue)!important;border-color:var(--blue);align-items:center;justify-content:center;}
.cls::after{content:'N';position:absolute;bottom:-45px;right:-18px;font-family:'NA';font-weight:900;font-size:600px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}
@media print{
  body{background:#fff;}
  .viewer{padding:0;gap:0;}
  .topbar,.nav{display:none;}
  .stage,.pw{width:210mm;height:297mm;overflow:visible;}
  .pg{display:flex!important;position:relative;page-break-after:always;width:210mm;height:297mm;border:none;}
}
"""

JS = """
const N=__N__;let c=0,bz=false;
function init(){
  const d=document.getElementById('dots');
  for(let i=0;i<N;i++){const s=document.createElement('span');s.className='dot'+(i===0?' on':'');s.onclick=()=>gp(i);d.appendChild(s);}
  document.querySelectorAll('.pg')[0].classList.add('on');
  upd();
}
function upd(){
  document.getElementById('bp').disabled=c===0;
  document.getElementById('bn').disabled=c===N-1;
  document.getElementById('pn').textContent='Page '+(c+1)+' of '+N;
  document.querySelectorAll('.dot').forEach((d,i)=>d.classList.toggle('on',i===c));
}
function fl(dir){
  if(bz)return;const nx=c+dir;if(nx<0||nx>=N)return;bz=true;
  const all=document.querySelectorAll('.pg');
  const ce=all[c],ne=all[nx];
  const ec=dir>0?'fxl':'fxr',en=dir>0?'fer':'fel';
  ce.classList.add(ec);ne.classList.add(en,'on');
  setTimeout(()=>{ce.classList.remove('on',ec);ne.classList.remove(en);c=nx;upd();bz=false;},350);
}
function gp(n){
  if(bz||n===c)return;const dir=n>c?1:-1;bz=true;
  const all=document.querySelectorAll('.pg');
  const ce=all[c],ne=all[n];
  const ec=dir>0?'fxl':'fxr',en=dir>0?'fer':'fel';
  ce.classList.add(ec);ne.classList.add(en,'on');
  setTimeout(()=>{ce.classList.remove('on',ec);ne.classList.remove(en);c=n;upd();bz=false;},350);
}
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight')fl(1);if(e.key==='ArrowLeft')fl(-1);});
init();
"""

def build_html(pages, company_info, fonts, logo_white_b64, updated_at):
    N = len(pages)
    css = (CSS
           .replace('__FONT_B__', fonts['black'])
           .replace('__FONT_M__', fonts['medium'])
           .replace('__FONT_R__', fonts['regular']))
    js = JS.replace('__N__', str(N))
    pages_html = '\n'.join(pages)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NESTU® {e(company_info['name'])} — Veterinary Product Catalogue 2026</title>
<style>{css}</style>
</head>
<body>
<div class="viewer">
<div class="topbar">
  <span class="tbl">NESTU<sup>®</sup></span>
  <span class="tbm">{e(company_info['name'])} &nbsp;·&nbsp; Veterinary Product Catalogue &nbsp;·&nbsp; 2026</span>
  <span class="tbd">Updated: {e(updated_at)}</span>
</div>
<div class="stage"><div class="pw">
{pages_html}
</div></div>
<div class="nav">
  <button class="nb" id="bp" onclick="fl(-1)" disabled>&#8592;</button>
  <div class="nm">
    <div class="dots" id="dots"></div>
    <span id="pn">Page 1 of {N}</span>
  </div>
  <button class="nb" id="bn" onclick="fl(1)">&#8594;</button>
</div>
</div>
<script>{js}</script>
</body>
</html>"""

# ──────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────

def generate_company(odoo, slug, fonts, logo_white, logo_blue, dear_doctor):
    co = COMPANIES[slug]
    print(f'\n{"─"*52}')
    print(f'  {co["name"]} (company_id={co["id"]})')
    print(f'{"─"*52}')

    tmpl_ids = get_in_stock_tmpl_ids(odoo, co['id'])
    print(f'  In-stock products: {len(tmpl_ids)}')
    if not tmpl_ids:
        print('  SKIP — no in-stock products')
        return []

    products = get_product_templates(odoo, tmpl_ids)

    all_tag_ids = set()
    for p in products:
        all_tag_ids.update(p.get('product_tag_ids', []))
    brand_map = get_brand_tags(odoo, all_tag_ids)

    # Group by primary brand tag, sort A→Z
    brand_products = {}
    missing_images = []

    for p in products:
        tids = p.get('product_tag_ids', [])
        if not p.get('image_1920'):
            missing_images.append(p.get('name', f'ID:{p["id"]}'))
        else:
            p['_img'] = process_image(p['image_1920'], p['id'])

        primary_brand = next((brand_map[t] for t in tids if t in brand_map), None)
        if primary_brand:
            brand_products.setdefault(primary_brand, []).append(p)

    sorted_brands = sorted(brand_products, key=str.lower)
    for bn in sorted_brands:
        brand_products[bn].sort(key=lambda x: (x.get('name') or '').lower())

    # Report missing images
    if missing_images:
        print(f'\n  ⚠ Missing images ({len(missing_images)}):')
        for nm in sorted(missing_images):
            print(f'      • {nm}')
    else:
        print('  ✓ All products have images')

    # Build pages
    pages = [page_cover(co['name'], logo_white)]
    pages.append(page_letter(dear_doctor, logo_blue, co))

    toc_idx = len(pages)
    pages.append('')  # TOC placeholder — fill after we know page indices

    toc_entries = []
    for b_idx, brand in enumerate(sorted_brands):
        prods = brand_products[brand]
        divider_page_idx = len(pages)
        toc_entries.append({'brand': brand, 'count': len(prods), 'page_idx': divider_page_idx})

        pages.append(page_brand_divider(brand, b_idx+1, len(sorted_brands), len(prods)))

        chunks = [prods[i:i+PRODUCTS_PER_PAGE] for i in range(0, len(prods), PRODUCTS_PER_PAGE)]
        for ci, chunk in enumerate(chunks):
            pages.append(page_products(brand, chunk, ci+1, len(chunks), logo_white))

    pages[toc_idx] = page_toc(toc_entries)
    pages.append(page_closing(logo_white))

    N = len(pages)
    updated_at = datetime.now().strftime('%d %b %Y · %H:%M AST')
    html = build_html(pages, co, fonts, logo_white, updated_at)

    out_path = OUTPUT_DIR / f'{slug}.html'
    out_path.write_text(html, encoding='utf-8')
    size_kb = len(html) / 1024
    print(f'  ✓ Saved: docs/{slug}.html  ({N} pages, {size_kb:.0f} KB)')

    return missing_images


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    check_only = '--check' in flags

    target_slugs = args if args else list(COMPANIES.keys())
    invalid = [s for s in target_slugs if s not in COMPANIES]
    if invalid:
        raise SystemExit(f'Unknown company slug(s): {invalid}. Valid: {list(COMPANIES.keys())}')

    # Load assets
    print('Loading fonts and assets...')
    try:
        fonts = {
            'black':   load_b64(FONTS_DIR / 'NeulisAlt-Black.otf'),
            'medium':  load_b64(FONTS_DIR / 'NeulisAlt-Medium.otf'),
            'regular': load_b64(FONTS_DIR / 'NeulisAlt-Regular.otf'),
        }
        logo_white = load_b64(ASSETS_DIR / 'logo_white.png')
        logo_blue  = load_b64(ASSETS_DIR / 'logo_blue.png')
    except FileNotFoundError as err:
        raise SystemExit(f'ERROR: {err}\nRun: python setup_assets.py')

    dear_doctor_path = CONFIG_DIR / 'dear_doctor.txt'
    dear_doctor = (dear_doctor_path.read_text(encoding='utf-8')
                   if dear_doctor_path.exists()
                   else 'With warmth and respect,\n\nThe NESTU family')

    odoo = connect_odoo()

    all_missing = {}
    for slug in target_slugs:
        missing = generate_company(odoo, slug, fonts, logo_white, logo_blue, dear_doctor)
        if missing:
            all_missing[slug] = missing

    print(f'\n{"═"*52}')
    if all_missing:
        print('⚠ PRODUCTS MISSING IMAGES — add in Odoo > Products > [product]:')
        for slug, names in all_missing.items():
            print(f'\n  {COMPANIES[slug]["name"]}:')
            for nm in sorted(names):
                print(f'    • {nm}')
    else:
        print('✓ All products have images')

    print('\n✓ Generation complete')
    print(f'   Jordan: docs/jordan.html')
    print(f'   UAE:    docs/uae.html')
    print(f'   KSA:    docs/ksa.html')


if __name__ == '__main__':
    main()

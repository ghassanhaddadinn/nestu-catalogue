#!/usr/bin/env python3
"""NESTU® Product Catalogue Generator v3"""

import xmlrpc.client, base64, os, sys, re, io, json, shutil, html as html_mod, math
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image; HAS_PIL = True
except ImportError:
    HAS_PIL = False

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

PRODUCTS_PER_PAGE = 9   # 3 cols × 3 rows

EXCLUDE_CATEG_IDS      = []
EXCLUDE_NAME_CONTAINS  = []
EXCLUDE_CODE_AND_NAME  = [('PPP5','kit'),('PPP5','bin')]

COMPANIES = {
    'jordan': {'id':2,'name':'Jordan','slug':'jordan',
               'entity':'The Nest for Specialized Veterinary Therapeutics & Utilities Ltd.',
               'address':'Oweym Ben Saeda St., Bldg. No. 46 · Amman, Jordan',
               'portal':'jordan.nestu.online'},
    'uae':    {'id':3,'name':'UAE','slug':'uae',
               'entity':'NESTU Veterinary Medicines Trading L.L.C',
               'address':'Office 602, North Tower, Dubai Science Park · Dubai, UAE',
               'portal':'uae.nestu.online'},
    'ksa':    {'id':4,'name':'KSA','slug':'ksa',
               'entity':'NESTU KSA','address':'Kingdom of Saudi Arabia',
               'portal':'uae.nestu.online'},
}

# ── ODOO ────────────────────────────────────────────────────────────────────

def connect_odoo():
    common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common', allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_KEY, {})
    if not uid: raise SystemExit('ERROR: Odoo auth failed.')
    models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)
    def call(model, method, *args, **kwargs):
        return models.execute_kw(ODOO_DB, uid, ODOO_KEY, model, method, list(args), kwargs)
    print(f'✓ Odoo connected (uid={uid})')
    return call

def get_catalogue_data(odoo, company_id):
    """Returns (all_tmpl_ids, in_stock_tmpl_ids) — ever-sold union current-stock."""
    # Ever sold in this company
    sol = odoo('sale.order.line','search_read',
        [['order_id.company_id','=',company_id],['order_id.state','in',['sale','done']]],
        fields=['product_id'], limit=0)
    sold_pp = {l['product_id'][0] for l in sol if l['product_id']}
    # Currently in stock
    quants = odoo('stock.quant','search_read',
        [['location_id.usage','=','internal'],['location_id.company_id','=',company_id],['quantity','>',0]],
        fields=['product_id'], limit=0)
    stock_pp = {q['product_id'][0] for q in quants}
    all_pp = sold_pp | stock_pp
    if not all_pp: return set(), set()
    pp_data = odoo('product.product','search_read',
        [['id','in',list(all_pp)]],fields=['id','product_tmpl_id'],limit=0)
    all_tmpl = set(); in_stock_tmpl = set()
    for p in pp_data:
        tid = p['product_tmpl_id'][0]
        all_tmpl.add(tid)
        if p['id'] in stock_pp:
            in_stock_tmpl.add(tid)
    return all_tmpl, in_stock_tmpl

def get_product_templates(odoo, tmpl_ids):
    if not tmpl_ids: return []
    return odoo('product.template','search_read',
        [['id','in',list(tmpl_ids)],['active','=',True]],
        fields=['id','name','product_tag_ids','default_code','categ_id','image_1920'],limit=0)

def get_brand_tags(odoo, tag_ids):
    if not tag_ids: return {}
    for fields in [['id','name','image_1920'],['id','name','image_128'],['id','name']]:
        try:
            tags = odoo('product.tag','search_read',[['id','in',list(tag_ids)]],fields=fields,limit=0)
            return {t['id']:t for t in tags}
        except Exception: continue
    return {}

# ── IMAGES ──────────────────────────────────────────────────────────────────

def process_image(b64, pid, target=(420,420)):
    cf = CACHE_DIR/f'p_{pid}.b64'
    if cf.exists(): return cf.read_text()
    if not b64: return None
    try:
        raw=base64.b64decode(b64)
        if HAS_PIL:
            img=Image.open(io.BytesIO(raw)).convert('RGBA')
            img.thumbnail(target,Image.LANCZOS)
            buf=io.BytesIO(); img.save(buf,format='PNG',optimize=True)
            out=base64.b64encode(buf.getvalue()).decode()
        else: out=b64
        cf.write_text(out); return out
    except Exception as ex: print(f'    Warning: image {pid}: {ex}'); return None

def process_brand_image(b64, tid):
    cf = CACHE_DIR/f'tag_{tid}.b64'
    if cf.exists(): return cf.read_text()
    if not b64: return None
    try:
        raw=base64.b64decode(b64)
        if HAS_PIL:
            img=Image.open(io.BytesIO(raw)).convert('RGBA')
            img.thumbnail((280,80),Image.LANCZOS)
            buf=io.BytesIO(); img.save(buf,format='PNG',optimize=True)
            out=base64.b64encode(buf.getvalue()).decode()
        else: out=b64
        cf.write_text(out); return out
    except Exception: return None

def copy_static_assets():
    fonts_out = OUTPUT_DIR/'fonts'; fonts_out.mkdir(exist_ok=True)
    for n in ['NeulisAlt-Black.otf','NeulisAlt-Medium.otf','NeulisAlt-Regular.otf']:
        src=FONTS_DIR/n; dst=fonts_out/n
        if src.exists(): shutil.copy2(src,dst)

def generate_index():
    html="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NESTU® Veterinary Product Catalogues</title>
<style>
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Black.otf') format('opentype');font-weight:900;font-display:swap;}
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Medium.otf') format('opentype');font-weight:500;font-display:swap;}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{width:100%;height:100%;overflow:hidden;font-family:'NA',sans-serif;background:#3040C4;}
body{display:flex;align-items:center;justify-content:center;}
.card{background:#fff;border-radius:14px;padding:48px 56px;text-align:center;width:min(440px,90vw);}
.logo{font-size:56px;font-weight:900;color:#3040C4;letter-spacing:-.01em;line-height:1;}
.logo sup{font-size:22px;vertical-align:super;}
.sub{font-size:11px;font-weight:500;color:#9ba5cc;letter-spacing:.18em;text-transform:uppercase;margin-top:8px;margin-bottom:40px;}
.links{display:flex;flex-direction:column;gap:10px;}
a.cat{display:block;padding:15px 22px;border-radius:8px;background:#3040C4;color:#fff;text-decoration:none;font-size:15px;font-weight:700;letter-spacing:.04em;transition:background .15s;}
a.cat:hover{background:#2434A8;}
.tag{margin-top:28px;font-size:10px;font-weight:500;color:#c0c8e8;letter-spacing:.1em;text-transform:uppercase;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">NESTU<sup>®</sup></div>
  <div class="sub">Veterinary Product Catalogues</div>
  <div class="links">
    <a class="cat" href="jordan.html">Jordan Catalogue</a>
    <a class="cat" href="uae.html">UAE Catalogue</a>
    <a class="cat" href="ksa.html">KSA Catalogue</a>
  </div>
  <div class="tag">Empowering Vets to Take Better Care of Our Pets</div>
</div>
</body>
</html>"""
    (OUTPUT_DIR/'index.html').write_text(html, encoding='utf-8')
    print('  ✓ docs/index.html')

# ── HELPERS ──────────────────────────────────────────────────────────────────

def e(s): return html_mod.escape(str(s))

def brand_font_size(name):
    l = len(name)
    if l > 24: return '34px'
    if l > 18: return '46px'
    if l > 12: return '60px'
    return '72px'

def species_sort_key(p, brand_name):
    """For Purina Pro Plan: dogs first, then cats, then both/other."""
    if 'purina' not in brand_name.lower():
        return (1, (p.get('name') or '').lower())
    n = (p.get('name') or '').lower()
    dog = any(k in n for k in ['canine',' dog ','dog ','dogs','puppy','large breed','medium breed','small breed','giant breed'])
    cat = any(k in n for k in ['feline',' cat ','cat ','cats','kitten','sterilised'])
    if dog and not cat:  return (0, n)
    if cat and not dog:  return (1, n)
    return (2, n)

def should_exclude(p):
    categ_id = (p.get('categ_id') or [False])[0]
    if categ_id and categ_id in EXCLUDE_CATEG_IDS: return True
    name = (p.get('name') or '').lower()
    if any(k.lower() in name for k in EXCLUDE_NAME_CONTAINS): return True
    ref = (p.get('default_code') or '').upper()
    name_lower = (p.get('name') or '').lower()
    for prefix, keyword in EXCLUDE_CODE_AND_NAME:
        if ref.startswith(prefix.upper()) and keyword.lower() in name_lower: return True
    return False

# ── PAGE BUILDERS ────────────────────────────────────────────────────────────

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
    sign_idx = next((i for i,p in enumerate(paras)
                     if any(w in p.lower() for w in ['warmth','regards','sincerely'])), None)
    if sign_idx is not None:
        body = paras[:sign_idx]; tail = paras[sign_idx:]
        closing = tail[0] if tail else closing
        signoff = tail[-1] if len(tail)>1 else signoff
    else: body = paras
    body_html = ''.join(f'<p>{e(p)}</p>' for p in body
                        if not p.strip().lower().startswith('dear doctor'))
    return f'''<div class="pg ltr">
<div class="lbody">
  <div class="lsal">Dear Doctor,</div>
  <div class="ltxt">{body_html}</div>
  <div class="lsign">
    <div class="lcl">{e(closing)}</div>
    <div class="lnm">{e(signoff)}</div>
  </div>
</div>
</div>'''

def page_toc(entries):
    rows = ''.join(
        f'<li><div class="ta" onclick="gp({en["page_idx"]})">'
        f'<span class="tnum">{i+1:02d}</span>'
        f'<span class="tdot"></span>'
        f'<span class="tbn">{e(en["brand"])}</span>'
        f'<span class="tcnt">{en["count"]} product{"s" if en["count"]!=1 else ""}</span>'
        f'<span class="tarr">→</span>'
        f'</div></li>'
        for i, en in enumerate(entries))
    return f'''<div class="pg">
<div class="pghd">
  <div class="pghd-l">Navigate</div>
  <div class="pghd-t">Table of Contents</div>
</div>
<div class="tbd">
  <p class="tintro">Click any brand to jump to its section. Products are sorted alphabetically within each brand. Tap the brand name in the nav bar at any time to open the quick-jump menu.</p>
  <ul class="tlist">{rows}</ul>
</div>
</div>'''

def page_brand_divider(brand, num, total, count, logo_b64=None):
    initial = brand[0].upper()
    fs = brand_font_size(brand)
    logo_html = ''
    if logo_b64:
        logo_html = f'<div class="bdlogo"><img src="data:image/png;base64,{logo_b64}" alt="{e(brand)}"></div>'
    return f'''<div class="pg bdiv" data-i="{e(initial)}">
<div class="bd-in">
  {logo_html}
  <div class="bdnum">Brand {num:02d} of {total:02d}</div>
  <div class="bdname" style="font-size:{fs}">{e(brand)}</div>
  <div class="bdrule"></div>
  <div class="bdcnt">{count} Product{"s" if count!=1 else ""} Available</div>
</div>
</div>'''

def page_products(brand, products, page_num, total_pages, logo_b64=None):
    logo_html = ''
    if logo_b64:
        logo_html = f'<img class="pphd-logo" src="data:image/png;base64,{logo_b64}" alt="{e(brand)}">'
    cards = ''
    for p in products:
        name = e(p.get('name',''))
        ref  = e(p.get('default_code') or '')
        cat  = e((p.get('categ_id') or [False,''])[1] or '')
        img  = p.get('_img')
        in_stock = p.get('_in_stock', True)
        av_cls = 'av' if in_stock else 'oos'
        img_html = (f'<img src="data:image/png;base64,{img}" alt="{name}">'
                    if img else f'<span class="pcph">{e(str(p.get("name","P"))[0].upper())}</span>')
        oos_cls = '' if in_stock else ' oos'
        cards += (f'<div class="pc{oos_cls}"><div class="pcimg"><span class="avdot {av_cls}"></span>{img_html}</div>'
                  f'<div class="pcinf">'
                  f'<div class="pcnm">{name}</div>'
                  ''
                  f'{f"""<div class="pcref">{ref}</div>""" if ref else ""}'
                  f'</div></div>')
    pag = f'{e(brand)} · {page_num}/{total_pages}' if total_pages>1 else e(brand)
    return f'''<div class="pg">
<div class="pphd">
  <div class="pphd-l">{logo_html}<span class="ppbrand">{e(brand)}</span></div>
  <span class="pplogo">NESTU<sup>®</sup></span>
</div>
<div class="ppgrid">{cards}</div>
<div class="pppage">{pag}</div>
</div>'''

def page_closing(co):
    return f'''<div class="pg cls">
<div class="cvbar"></div>
<div class="cv-in">
  <div class="cv-logo">NESTU<sup>®</sup></div>
  <div class="cvrule"></div>
  <div class="cv-tag2">Empowering Vets to Take<br>Better Care of Our Pets</div>
</div>
<div class="cv-foot">
  <div class="cv-url">nestu.health &nbsp;·&nbsp; info@nestu.health</div>
  <a class="cv-portal" href="https://nestu.online" target="_blank">B2B Portal &nbsp;→&nbsp; nestu.online</a>
  <div class="cv-tag">© 2026 NESTU Ltd. · Jordan · UAE · KSA</div>
</div>
</div>'''

# ── CSS ──────────────────────────────────────────────────────────────────────

CSS = """
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Black.otf') format('opentype');font-weight:900;font-display:swap;}
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Medium.otf') format('opentype');font-weight:500;font-display:swap;}
@font-face{font-family:'NA';src:url('fonts/NeulisAlt-Regular.otf') format('opentype');font-weight:400;font-display:swap;}
*{box-sizing:border-box;margin:0;padding:0;}
:root{--blue:#3040C4;--bdk:#2434A8;--g50:#f8f9fc;--g100:#eef0f8;--g200:#e0e4f2;--g400:#9ba5cc;--g600:#5f6d9e;--tx:#1a2040;}
html,body{width:100%;height:100%;overflow:hidden;font-family:'NA',sans-serif;background:#c8cedf;}
.viewer{width:100vw;height:100dvh;display:flex;flex-direction:column;position:relative;}
.stage-outer{flex:1;min-height:0;display:flex;justify-content:center;align-items:center;padding:8px;}
.stage{transform-origin:center center;}
.pw{width:820px;height:1160px;position:relative;overflow:hidden;box-shadow:0 4px 28px rgba(30,36,72,0.25);}
.nav{height:52px;background:var(--blue);flex-shrink:0;display:flex;align-items:center;padding:0 12px;gap:8px;}
.nb{background:rgba(255,255,255,.18);color:#fff;border:none;width:36px;height:36px;border-radius:50%;font-size:17px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;flex-shrink:0;font-family:'NA',sans-serif;}
.nb:disabled{opacity:.3;cursor:default;}
.nb:not(:disabled):hover{background:rgba(255,255,255,.28);}
.nav-mid{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}
.nav-brand-btn{background:none;border:none;cursor:pointer;display:flex;align-items:center;gap:6px;padding:0;text-align:left;}
.nav-brand-lbl{font-size:11px;font-weight:700;color:rgba(255,255,255,.8);letter-spacing:.04em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:300px;font-family:'NA',sans-serif;}
.nav-brand-arr{font-size:10px;color:rgba(255,255,255,.5);}
.nav-track{height:2px;background:rgba(255,255,255,.2);border-radius:1px;}
.nav-fill{height:100%;background:#fff;border-radius:1px;transition:width .3s;}
.nav-right{display:flex;align-items:center;gap:8px;flex-shrink:0;}
.nav-pg{font-size:11px;color:rgba(255,255,255,.6);white-space:nowrap;font-weight:500;}
.pg{position:absolute;inset:0;background:#fff;display:none;flex-direction:column;font-family:'NA',sans-serif;overflow:hidden;}
.pg.on{display:flex;}
@keyframes fxL{0%{transform:perspective(1400px) rotateY(0);opacity:1;}100%{transform:perspective(1400px) rotateY(-82deg);opacity:0;}}
@keyframes feR{0%{transform:perspective(1400px) rotateY(82deg);opacity:0;}100%{transform:perspective(1400px) rotateY(0);opacity:1;}}
@keyframes fxR{0%{transform:perspective(1400px) rotateY(0);opacity:1;}100%{transform:perspective(1400px) rotateY(82deg);opacity:0;}}
@keyframes feL{0%{transform:perspective(1400px) rotateY(-82deg);opacity:0;}100%{transform:perspective(1400px) rotateY(0);opacity:1;}}
.pg.fxl{display:flex!important;animation:fxL .32s ease-in forwards;}
.pg.fxr{display:flex!important;animation:fxR .32s ease-in forwards;}
.pg.fer{display:flex!important;animation:feR .32s ease-out;}
.pg.fel{display:flex!important;animation:feL .32s ease-out;}
/* COVER */
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
.cv-foot{position:absolute;bottom:44px;left:0;right:0;z-index:1;display:flex;flex-direction:column;align-items:center;gap:4px;}
.cv-tag{font-size:10px;font-weight:500;color:rgba(255,255,255,.4);letter-spacing:.12em;text-transform:uppercase;}
.cv-url{font-size:12px;font-weight:700;color:rgba(255,255,255,.68);}
.cv-portal{display:inline-block;font-size:11px;font-weight:700;color:rgba(255,255,255,.85);letter-spacing:.06em;text-decoration:none;border:1px solid rgba(255,255,255,.35);border-radius:20px;padding:5px 18px;transition:background .15s;}
.cv-tag2{font-size:13px;font-weight:500;color:rgba(255,255,255,.65);letter-spacing:.1em;text-transform:uppercase;text-align:center;line-height:1.65;}
/* LETTER */
.ltr{justify-content:center;}
.lbody{padding:64px 64px 48px;max-width:680px;margin:0 auto;width:100%;}
.lsal{font-size:20px;font-weight:900;color:var(--blue);margin-bottom:20px;}
.ltxt{font-size:13.5px;line-height:1.9;color:var(--tx);text-align:justify;}
.ltxt p{margin-bottom:14px;}
.lsign{margin-top:36px;}
.lcl{font-size:13px;color:var(--tx);margin-bottom:28px;font-style:italic;}
.lnm{font-size:15px;font-weight:900;color:var(--blue);}

/* TOC */
.pghd{background:var(--blue);padding:28px 52px;flex-shrink:0;}
.pghd-l{font-size:10px;font-weight:700;color:rgba(255,255,255,.5);letter-spacing:.22em;text-transform:uppercase;margin-bottom:6px;}
.pghd-t{font-size:26px;font-weight:900;color:#fff;letter-spacing:.03em;}
.tbd{padding:24px 52px;flex:1;overflow:hidden;}
.tintro{font-size:11.5px;color:var(--g600);margin-bottom:20px;line-height:1.65;}
.tlist{list-style:none;}
.ta{display:flex;align-items:center;padding:10px 0;border-bottom:0.5px solid var(--g100);cursor:pointer;}
.ta:last-child{border-bottom:none;}
.ta:hover .tbn{color:var(--blue);}
.tnum{font-size:10px;font-weight:700;color:var(--g400);letter-spacing:.08em;width:26px;flex-shrink:0;}
.tdot{width:8px;height:8px;border-radius:50%;background:var(--blue);flex-shrink:0;margin-right:14px;}
.tbn{font-size:14px;font-weight:700;color:var(--tx);flex:1;transition:color .15s;}
.tcnt{font-size:11px;color:var(--g400);font-weight:500;margin-right:12px;}
.tarr{color:var(--blue);font-size:14px;font-weight:700;}
/* BRAND DIVIDER */
.bdiv{background:var(--blue)!important;align-items:center;justify-content:center;}
.bdiv::before{content:attr(data-i);position:absolute;font-family:'NA';font-weight:900;font-size:520px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}
.bd-in{text-align:center;position:relative;z-index:1;padding:0 40px;width:100%;}
.bdlogo{margin-bottom:20px;}
.bdlogo img{max-width:200px;max-height:64px;object-fit:contain;filter:brightness(0) invert(1);opacity:.85;}
.bdnum{font-size:11px;font-weight:700;color:rgba(255,255,255,.48);letter-spacing:.22em;text-transform:uppercase;margin-bottom:18px;}
.bdname{font-weight:900;color:#fff;letter-spacing:.03em;line-height:1.1;word-break:break-word;overflow-wrap:break-word;}
.bdrule{width:50px;height:2px;background:rgba(255,255,255,.32);margin:20px auto;}
.bdcnt{font-size:13px;color:rgba(255,255,255,.6);font-weight:500;letter-spacing:.06em;}
/* PRODUCT PAGE */
.pphd{background:var(--blue);padding:11px 32px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.pphd-l{display:flex;align-items:center;gap:10px;}
.pphd-logo{height:22px;max-width:72px;object-fit:contain;filter:brightness(0) invert(1);opacity:.85;}
.ppbrand{font-size:14px;font-weight:900;color:#fff;letter-spacing:.07em;text-transform:uppercase;}
.pplogo{font-size:14px;font-weight:900;color:rgba(255,255,255,.5);}
.pplogo sup{font-size:7px;vertical-align:super;}
.ppgrid{flex:1;min-height:0;padding:12px 24px;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);gap:10px;}
.pc{border:0.5px solid var(--g200);border-radius:7px;overflow:hidden;display:flex;flex-direction:column;min-height:0;transition:border-color .15s;}
.pc:hover{border-color:var(--blue);}
.pcimg{flex:1;min-height:0;background:#fff;display:flex;align-items:center;justify-content:center;border-bottom:0.5px solid var(--g100);overflow:hidden;position:relative;}
.pcimg img{max-width:100%;max-height:100%;object-fit:contain;padding:8px;}
.avdot{position:absolute;top:7px;right:7px;width:9px;height:9px;border-radius:50%;border:1.5px solid #fff;z-index:2;box-shadow:0 1px 3px rgba(0,0,0,.15);}
.avdot.av{background:#22c55e;}
.avdot.oos{background:#c8cedf;}
.pc.oos .pcimg img{opacity:.55;filter:grayscale(25%);}
.pc.oos .pcnm{color:var(--g600);}
.pc.oos .pcref{color:var(--g400);}
.pcph{font-family:'NA';font-size:42px;font-weight:900;color:var(--g200);}
.pcinf{flex-shrink:0;padding:8px 10px 9px;display:flex;flex-direction:column;gap:3px;}
.pcnm{font-size:13px;font-weight:700;color:var(--tx);line-height:1.3;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.pcref{font-size:10.5px;color:var(--g400);letter-spacing:.02em;}
.pppage{padding:5px 30px;text-align:center;font-size:9px;color:var(--g400);flex-shrink:0;}
/* CLOSING */
.cls{background:var(--blue)!important;align-items:center;justify-content:center;}
.cls::after{content:'N';position:absolute;bottom:-45px;right:-18px;font-family:'NA';font-weight:900;font-size:600px;line-height:1;color:rgba(255,255,255,.04);pointer-events:none;user-select:none;}
/* BRAND QUICK-JUMP PANEL */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);opacity:0;pointer-events:none;transition:opacity .25s;z-index:99;}
.overlay.on{opacity:1;pointer-events:auto;}
.bpanel{position:fixed;bottom:0;left:0;right:0;background:#fff;border-radius:18px 18px 0 0;transform:translateY(100%);transition:transform .3s cubic-bezier(.4,0,.2,1);z-index:100;max-height:72vh;display:flex;flex-direction:column;box-shadow:0 -4px 30px rgba(30,36,72,.2);}
.bpanel.on{transform:translateY(0);}
.bpanel-hd{padding:16px 20px;border-bottom:0.5px solid var(--g100);display:flex;justify-content:space-between;align-items:center;flex-shrink:0;}
.bpanel-hd-title{font-size:15px;font-weight:700;color:var(--tx);}
.bpanel-close{background:var(--g50);border:none;width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;}
.bpanel-list{overflow-y:auto;flex:1;padding:6px 0;}
.bitem{display:flex;align-items:center;padding:13px 20px;border-bottom:0.5px solid var(--g50);cursor:pointer;gap:12px;transition:background .12s;}
.bitem:hover{background:var(--g50);}
.bitem.active .bname{color:var(--blue);}
.bitem-icon{width:32px;height:32px;border-radius:6px;background:var(--blue);display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:900;color:#fff;flex-shrink:0;font-family:'NA',sans-serif;}
.bname{font-size:14px;font-weight:700;color:var(--tx);flex:1;}
.bcnt{font-size:11px;color:var(--g400);font-weight:500;}
.bsep{height:0.5px;background:var(--g200);margin:4px 20px;}
@media print{
  html,body{overflow:visible;height:auto;}
  .viewer{height:auto;}
  .stage-outer{display:block;}
  .stage{transform:none!important;width:210mm!important;height:auto!important;}
  .pw{width:210mm!important;height:auto!important;box-shadow:none;}
  .pg{display:flex!important;position:relative;page-break-after:always;min-height:297mm;}
  .nav,.overlay,.bpanel{display:none;}
}
"""

JS_TPL = """
const N=__N__,PI=__PI__;
let c=0,bz=false,mOpen=false;

function resize(){
  const PW=820,PH=1160;
  const outer=document.querySelector('.stage-outer');
  const r=outer.getBoundingClientRect();
  const scale=Math.min(r.width/PW,r.height/PH)*.98;
  const stage=document.querySelector('.stage');
  stage.style.width=PW+'px'; stage.style.height=PH+'px';
  stage.style.transform=`scale(${scale})`;
}
window.addEventListener('resize',resize);
window.addEventListener('orientationchange',()=>setTimeout(resize,100));

function upd(){
  document.getElementById('bp').disabled=c===0;
  document.getElementById('bn').disabled=c===N-1;
  const info=PI[c]||{};
  document.getElementById('nbl').textContent=info.label||'';
  document.getElementById('npg').textContent=`${c+1}/${N}`;
  document.getElementById('nfill').style.width=((c+1)/N*100).toFixed(1)+'%';
  // Highlight active brand in panel
  document.querySelectorAll('.bitem').forEach(el=>{
    el.classList.toggle('active', parseInt(el.dataset.page)===c ||
      (info.type==='products' && parseInt(el.dataset.page)<c && 
       PI.slice(parseInt(el.dataset.page),c).every(p=>p.type==='products'||p.type==='divider')));
  });
}

function fl(dir){
  if(bz)return; const nx=c+dir;
  if(nx<0||nx>=N)return; bz=true;
  const all=document.querySelectorAll('.pg');
  const ce=all[c],ne=all[nx];
  const ec=dir>0?'fxl':'fxr',en=dir>0?'fer':'fel';
  ce.classList.add(ec); ne.classList.add(en,'on');
  setTimeout(()=>{ce.classList.remove('on',ec);ne.classList.remove(en);c=nx;upd();bz=false;},320);
}

function gp(n){
  if(bz||n===c)return; const dir=n>c?1:-1; bz=true;
  const all=document.querySelectorAll('.pg');
  const ce=all[c],ne=all[n];
  const ec=dir>0?'fxl':'fxr',en=dir>0?'fer':'fel';
  ce.classList.add(ec); ne.classList.add(en,'on');
  setTimeout(()=>{ce.classList.remove('on',ec);ne.classList.remove(en);c=n;upd();bz=false;},320);
}

function toggleMenu(){
  mOpen=!mOpen;
  document.getElementById('overlay').classList.toggle('on',mOpen);
  document.getElementById('bpanel').classList.toggle('on',mOpen);
}

function jumpTo(n){toggleMenu();setTimeout(()=>gp(n),50);}

function buildMenu(){
  const list=document.getElementById('bpanel-list');
  // Fixed: Cover + TOC
  [{l:'Cover',i:0},{l:'Table of Contents',i:2}].forEach(item=>{
    const d=document.createElement('div');
    d.className='bitem'; d.dataset.page=item.i;
    d.innerHTML=`<div class="bitem-icon">⊙</div><span class="bname">${item.l}</span>`;
    d.onclick=()=>jumpTo(item.i); list.appendChild(d);
  });
  const sep=document.createElement('div'); sep.className='bsep'; list.appendChild(sep);
  // Brands
  PI.forEach((info,i)=>{
    if(info.type!=='divider')return;
    const d=document.createElement('div');
    d.className='bitem'; d.dataset.page=i;
    const letter=info.label?info.label[0].toUpperCase():'?';
    d.innerHTML=`<div class="bitem-icon">${letter}</div><span class="bname">${info.label}</span><span class="bcnt">${info.count||''}</span>`;
    d.onclick=()=>jumpTo(i); list.appendChild(d);
  });
}

document.addEventListener('keydown',ev=>{
  if(ev.key==='ArrowRight')fl(1);
  if(ev.key==='ArrowLeft')fl(-1);
  if(ev.key==='Escape'&&mOpen)toggleMenu();
});
let tx=0;
document.querySelector('.pw').addEventListener('touchstart',ev=>{tx=ev.touches[0].clientX;},{passive:true});
document.querySelector('.pw').addEventListener('touchend',ev=>{
  const dx=ev.changedTouches[0].clientX-tx;
  if(Math.abs(dx)>40)fl(dx<0?1:-1);
},{passive:true});

document.querySelectorAll('.pg')[0].classList.add('on');
buildMenu(); resize(); upd();
"""

def build_html(pages, page_info, co, updated_at):
    N = len(pages)
    pi_json = json.dumps(page_info, ensure_ascii=False)
    js = JS_TPL.replace('__N__', str(N)).replace('__PI__', pi_json)
    pages_html = '\n'.join(pages)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>NESTU® {e(co['name'])} — Veterinary Product Catalogue 2026</title>
<style>{CSS}</style>
</head>
<body>
<div class="viewer">
  <div class="stage-outer">
    <div class="stage"><div class="pw">
{pages_html}
    </div></div>
  </div>
  <div class="nav">
    <button class="nb" id="bp" onclick="fl(-1)" disabled>&#8592;</button>
    <div class="nav-mid">
      <button class="nav-brand-btn" onclick="toggleMenu()">
        <span class="nav-brand-lbl" id="nbl">Cover</span>
        <span class="nav-brand-arr">&#9650;</span>
      </button>
      <div class="nav-track"><div class="nav-fill" id="nfill" style="width:2%"></div></div>
    </div>
    <div class="nav-right">
      <span class="nav-pg" id="npg">1/{N}</span>
      <button class="nb" id="bn" onclick="fl(1)">&#8594;</button>
    </div>
  </div>
</div>
<div class="overlay" id="overlay" onclick="toggleMenu()"></div>
<div class="bpanel" id="bpanel">
  <div class="bpanel-hd">
    <span class="bpanel-hd-title">Navigate Catalogue</span>
    <button class="bpanel-close" onclick="toggleMenu()">&#215;</button>
  </div>
  <div class="bpanel-list" id="bpanel-list"></div>
</div>
<script>{js}</script>
</body>
</html>"""

# ── MAIN ─────────────────────────────────────────────────────────────────────

def generate_company(odoo, slug, dear_doctor):
    co = COMPANIES[slug]
    print(f'\n{"─"*56}\n  {co["name"]}  (company_id={co["id"]})\n{"─"*56}')

    tmpl_ids, in_stock_tmpl = get_catalogue_data(odoo, co['id'])
    print(f'  Total templates: {len(tmpl_ids)} | In-stock: {len(in_stock_tmpl)}')
    if not tmpl_ids:
        print('  SKIP — no products found (no sales history and no stock)'); return []

    products = get_product_templates(odoo, tmpl_ids)
    all_tag_ids = set()
    for p in products: all_tag_ids.update(p.get('product_tag_ids',[]))
    brand_map = get_brand_tags(odoo, all_tag_ids)

    brand_products = {}; missing_images = []; excluded = 0

    for p in products:
        if should_exclude(p): excluded += 1; continue
        tids = p.get('product_tag_ids',[])
        if not p.get('image_1920'):
            missing_images.append(p.get('name', f"ID:{p['id']}"))
        else:
            p['_img'] = process_image(p['image_1920'], p['id'])
        p['_in_stock'] = p['id'] in in_stock_tmpl
        primary = next((brand_map[t]['name'] for t in tids if t in brand_map), None)
        if primary:
            brand_products.setdefault(primary, []).append(p)

    if excluded: print(f'  Excluded (filter): {excluded}')
    if missing_images:
        print(f'\n  ⚠ MISSING IMAGES ({len(missing_images)}):')
        for nm in sorted(missing_images): print(f'      • {nm}')
    else:
        print(f'  ✓ All products have images')

    sorted_brands = sorted(brand_products, key=str.lower)
    for bn in sorted_brands:
        # Sort products: species-aware for Purina, alphabetical otherwise
        brand_products[bn].sort(key=lambda p: (0 if p.get('_in_stock') else 1, species_sort_key(p, bn)))

    pages = []; page_info = []

    pages.append(page_cover(co['name']))
    page_info.append({'label':'Cover','type':'cover'})
    pages.append(page_letter(dear_doctor, co))
    page_info.append({'label':'Dear Doctor','type':'letter'})
    toc_idx = len(pages); pages.append(''); page_info.append({'label':'Contents','type':'toc'})

    toc_entries = []
    for b_idx, brand in enumerate(sorted_brands):
        prods = brand_products[brand]
        div_idx = len(pages)
        toc_entries.append({'brand':brand,'count':len(prods),'page_idx':div_idx})

        # Brand logo
        tag_data = next((v for v in brand_map.values() if v.get('name')==brand), None)
        logo_b64 = None
        if tag_data:
            raw = tag_data.get('image_1920') or tag_data.get('image_128')
            if raw:
                tid = next((k for k,v in brand_map.items() if v.get('name')==brand), 0)
                logo_b64 = process_brand_image(raw, tid)

        pages.append(page_brand_divider(brand, b_idx+1, len(sorted_brands), len(prods), logo_b64))
        page_info.append({'label':brand,'type':'divider','count':len(prods)})

        chunks = [prods[i:i+PRODUCTS_PER_PAGE] for i in range(0, len(prods), PRODUCTS_PER_PAGE)]
        for ci, chunk in enumerate(chunks):
            pages.append(page_products(brand, chunk, ci+1, len(chunks), logo_b64))
            lbl = f'{brand} · {ci+1}/{len(chunks)}' if len(chunks)>1 else brand
            page_info.append({'label':lbl,'type':'products'})

    pages[toc_idx] = page_toc(toc_entries)
    pages.append(page_closing(co))
    page_info.append({'label':'','type':'closing'})

    updated_at = datetime.now().strftime('%d %b %Y · %H:%M AST')
    html = build_html(pages, page_info, co, updated_at)
    out_path = OUTPUT_DIR/f'{slug}.html'
    out_path.write_text(html, encoding='utf-8')
    print(f'  ✓ docs/{slug}.html — {len(pages)} pages, {len(html)//1024} KB')
    return missing_images


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    target_slugs = args if args else list(COMPANIES.keys())
    invalid = [s for s in target_slugs if s not in COMPANIES]
    if invalid: raise SystemExit(f'Unknown slugs: {invalid}')

    print('Copying static assets...')
    copy_static_assets()
    generate_index()

    dp = CONFIG_DIR/'dear_doctor.txt'
    dear_doctor = dp.read_text(encoding='utf-8') if dp.exists() else 'With warmth and respect,\n\nThe NESTU family'

    odoo = connect_odoo()
    all_missing = {}
    for slug in target_slugs:
        missing = generate_company(odoo, slug, dear_doctor)
        if missing: all_missing[slug] = missing

    print(f'\n{"═"*56}')
    if all_missing:
        print('⚠ PRODUCTS MISSING IMAGES:')
        for slug, names in all_missing.items():
            print(f'\n  {COMPANIES[slug]["name"]}:')
            for nm in sorted(names): print(f'    • {nm}')
    else:
        print('✓ All products have images')
    print('\n✓ Done')


if __name__ == '__main__':
    main()

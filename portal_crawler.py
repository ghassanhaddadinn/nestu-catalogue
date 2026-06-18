
import os, json, time
from playwright.sync_api import sync_playwright

EMAIL    = os.environ["PORTAL_EMAIL"]
PASSWORD = os.environ["PORTAL_PASSWORD"]
OUT      = "portal_screenshots"
os.makedirs(OUT, exist_ok=True)
DATA = {}

PORTALS = [
    {"code": "UAE", "base": "https://uae.nestu.online"},
    {"code": "KSA", "base": "https://ksa.nestu.online"},
    {"code": "JO",  "base": "https://jo.nestu.online"},
]

def ss(page, name):
    try:
        page.screenshot(path=f"{OUT}/{name}.png", full_page=True)
        print(f"  ✓ {name}")
    except Exception as e:
        print(f"  ✗ {name}: {e}")

def txt(page):
    try: return page.inner_text("body")
    except: return ""

def wait(page, ms=2500):
    page.wait_for_timeout(ms)

def goto(page, url, name=None):
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
        wait(page)
        if name: ss(page, name)
        return True
    except Exception as e:
        print(f"  ✗ {url}: {e}")
        return False

def do_login(page, base, code):
    page.goto(f"{base}/login", wait_until="networkidle", timeout=20000)
    wait(page, 2000)
    ss(page, f"{code}_LOGIN_PAGE")
    DATA[f"{code}_login_page"] = {"url": page.url, "text": txt(page), "html": page.content()}
    
    filled = False
    for sel in ['input[type="email"]','input[name="email"]','input[placeholder*="mail" i]','input[id*="email" i]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(EMAIL); filled = True; break
        except: continue
    if not filled:
        print(f"  ✗ {code}: email field not found")
        return False

    for sel in ['input[type="password"]','input[name="password"]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(PASSWORD); break
        except: continue

    for sel in ['button[type="submit"]','button:has-text("Login")','button:has-text("Sign")','input[type="submit"]']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click(); break
        except: continue

    wait(page, 4000)
    print(f"  Post-login URL: {page.url}")
    if "/login" in page.url:
        ss(page, f"{code}_LOGIN_FAILED")
        return False
    return True

def crawl_public(page, code, base):
    print(f"\n=== {code} PUBLIC ===")
    for path, name in [
        ("",               f"{code}_01_home"),
        ("/products",      f"{code}_02_products_public"),
        ("/contact-us",    f"{code}_04_contact"),
        ("/terms-condition",f"{code}_05_terms"),
        ("/privacy-policy",f"{code}_06_privacy"),
    ]:
        if goto(page, base+path, name):
            DATA[name] = {"url": page.url, "text": txt(page)}
    
    # Login page (public view)
    goto(page, f"{base}/login", f"{code}_03_login_public")
    DATA[f"{code}_03_login"] = {"url": page.url, "text": txt(page), "html": page.content()}
    
    # Registration page
    for rp in ["/register","/signup","/sign-up","/create-account","/apply"]:
        page.goto(base+rp, timeout=10000)
        wait(page)
        if rp.strip("/") in page.url:
            ss(page, f"{code}_07_register")
            DATA[f"{code}_07_register"] = {"url": page.url, "text": txt(page), "html": page.content()}
            break

def crawl_auth(page, code, base):
    print(f"\n=== {code} AUTHENTICATED ===")
    if not do_login(page, base, code):
        print(f"  Skipping {code}")
        return

    # Dashboard
    ss(page, f"{code}_10_dashboard")
    DATA[f"{code}_10_dashboard"] = {"url": page.url, "text": txt(page)}
    
    # Collect all nav links
    nav = page.eval_on_selector_all(
        "nav a, header a, [class*='nav'] a, [class*='menu'] a, aside a",
        "els => els.map(e=>({t:e.innerText.trim(),h:e.href})).filter(e=>e.t&&e.h&&!e.h.includes('#'))"
    )
    DATA[f"{code}_nav"] = nav
    print(f"  Nav links: {[(l['t'],l['h']) for l in nav]}")
    
    # Products (authenticated)
    if goto(page, f"{base}/products", None):
        wait(page, 4000)  # let products render
        ss(page, f"{code}_11_products_auth")
        DATA[f"{code}_11_products"] = {"url": page.url, "text": txt(page)}
        
        # Get product links
        links = page.eval_on_selector_all(
            "a[href*='/product'], .product-card a, [class*='product'] a",
            "els=>[...new Set(els.map(e=>e.href).filter(h=>h&&h.includes('/product')))].slice(0,2)"
        )
        print(f"  Product links: {links}")
        
        if links:
            if goto(page, links[0], f"{code}_12_product_detail"):
                DATA[f"{code}_12_product"] = {"url": page.url, "text": txt(page)}
                # Add to cart to reveal cart state -- no order placed
                for sel in ['button:has-text("Add to Cart")','button:has-text("Add to Bag")','button:has-text("Add")','[class*="add-to-cart"]']:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=2000):
                            btn.click(); wait(page, 2000)
                            ss(page, f"{code}_13_added_to_cart")
                            break
                    except: continue
    
    # Cart
    for cp in ["/cart","/basket","/my-cart"]:
        page.goto(base+cp, timeout=10000); wait(page)
        if "cart" in page.url or cp.strip("/") in page.url:
            ss(page, f"{code}_14_cart")
            DATA[f"{code}_14_cart"] = {"url": page.url, "text": txt(page)}
            break
    
    # Checkout -- screenshot only, NEVER submit
    for cp in ["/checkout","/cart/checkout","/order/checkout"]:
        page.goto(base+cp, timeout=10000); wait(page, 2000)
        if "checkout" in page.url:
            ss(page, f"{code}_15_checkout")
            DATA[f"{code}_15_checkout"] = {"url": page.url, "text": txt(page)}
            break
    
    # Orders
    for op in ["/orders","/my-orders","/order-history","/account/orders"]:
        page.goto(base+op, timeout=10000); wait(page)
        if op.strip("/") in page.url and "/login" not in page.url:
            ss(page, f"{code}_16_orders")
            DATA[f"{code}_16_orders"] = {"url": page.url, "text": txt(page)}
            # First order detail
            for sel in ["a[href*='/order/']","a[href*='/orders/']","tr a","[class*='order'] a"]:
                try:
                    el = page.locator(sel).first
                    if el.count()>0:
                        h = el.get_attribute("href")
                        if h:
                            goto(page, h if h.startswith("http") else base+h, f"{code}_17_order_detail")
                            DATA[f"{code}_17_order_detail"] = {"url": page.url, "text": txt(page)}
                            break
                except: continue
            break
    
    # Account/Profile
    for ap in ["/account","/profile","/my-account","/settings"]:
        page.goto(base+ap, timeout=10000); wait(page)
        if ap.strip("/") in page.url and "/login" not in page.url:
            ss(page, f"{code}_18_account")
            DATA[f"{code}_18_account"] = {"url": page.url, "text": txt(page)}
            break
    
    # PawPerks
    for pp in ["/pawperks","/paw-perks","/loyalty","/rewards","/points"]:
        page.goto(base+pp, timeout=10000); wait(page)
        if pp.strip("/") in page.url and "/login" not in page.url:
            ss(page, f"{code}_19_pawperks")
            DATA[f"{code}_19_pawperks"] = {"url": page.url, "text": txt(page)}
            print(f"  PawPerks at {pp}")
            break
    
    # Any extra nav links not yet visited
    visited = {base, base+"/", base+"/products", base+"/login",
               base+"/contact-us", base+"/cart", base+"/checkout"}
    for link in nav:
        h = link.get("h","")
        if h and base in h and h not in visited:
            visited.add(h)
            slug = h.replace(base,"").strip("/").replace("/","_") or "misc"
            if goto(page, h, f"{code}_extra_{slug}"):
                DATA[f"{code}_extra_{slug}"] = {"url": page.url, "text": txt(page)}
    
    # Logout
    for lo in ["/logout","/sign-out","/signout"]:
        try: page.goto(base+lo, timeout=8000); break
        except: continue

# ── MAIN ─────────────────────────────────────────────────────────────
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])

    ctx = browser.new_context(viewport={"width":1440,"height":900})
    pg  = ctx.new_page()
    goto(pg, "https://www.nestu.online", "00_landing")
    DATA["00_landing"] = {"url": pg.url, "text": txt(pg)}
    ctx.close()

    for portal in PORTALS:
        code, base = portal["code"], portal["base"]
        ctx = browser.new_context(viewport={"width":1440,"height":900})
        pg  = ctx.new_page()
        crawl_public(pg, code, base)
        ctx.close()
        
        ctx = browser.new_context(viewport={"width":1440,"height":900})
        pg  = ctx.new_page()
        crawl_auth(pg, code, base)
        ctx.close()

    browser.close()

with open("portal_data.json","w",encoding="utf-8") as f:
    json.dump(DATA, f, indent=2, ensure_ascii=False)

files = sorted(os.listdir(OUT))
print(f"\n✓ Done — {len(files)} screenshots")
for f in files: print(f"  {f}")

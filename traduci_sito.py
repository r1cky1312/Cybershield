"""Sito multilingua CyberShield.

L'italiano resta la sorgente (index.html, servizi/*.html, privacy.html).
Questo script:
  1) estrae i testi italiani in i18n/testi_it.tsv   (python3 traduci_sito.py estrai)
  2) genera /en/, /fr/, /es/, /de/ usando i18n/<lingua>.json (python3 traduci_sito.py)
     e aggiunge a TUTTE le pagine (anche quelle italiane) il selettore lingua e i tag hreflang.
Quando cambi un testo italiano: rilancia `estrai`, traduci le righe segnate come MANCANTI, rilancia lo script.
"""
import glob, hashlib, json, os, re, sys, urllib.parse
from bs4 import BeautifulSoup, NavigableString, Tag, Comment, Doctype

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.cybershield1.store/"
LANGS = [("it", "Italiano"), ("en", "English"), ("fr", "Français"), ("es", "Español"), ("de", "Deutsch")]
LOCALE = {"it": "it_IT", "en": "en_GB", "fr": "fr_FR", "es": "es_ES", "de": "de_DE"}
PAGES = ["index.html", "privacy.html"] + sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "servizi", "*.html")))
INLINE = {"a", "abbr", "b", "br", "code", "em", "i", "mark", "small", "span", "strong", "sub", "sup", "u", "s", "time", "kbd", "q", "cite", "wbr"}
SKIP = {"script", "style", "svg", "noscript", "template", "code"}
ATTRS = ["alt", "title", "aria-label", "placeholder", "data-plan"]
META = {"description", "og:title", "og:description", "og:image:alt", "twitter:title", "twitter:description", "twitter:image:alt"}
# testi dentro gli script JS (letterali esatti)
JS = ["'Ciao, sono interessato a \"'", "'. Possiamo parlarne?'", "['Controllo online','Backup','Sicurezza','Sito']"]

def norm(s): return re.sub(r"\s+", " ", s).strip()
def key(s): return hashlib.md5(norm(s).encode()).hexdigest()[:10]
def worth(s):
    s = norm(s)
    if not re.search(r"[a-zà-ÿ]", s): return False          # CYBER, FAQ, prezzi, numeri, simboli
    if re.fullmatch(r"[\w.+-]+@[\w.-]+", s) or s.startswith("http"): return False
    return True

def is_unit(el):
    if el.name in SKIP: return False
    if not worth(el.get_text()): return False
    return all(d.name in INLINE for d in el.find_all(True))

VOID = {"br", "wbr"}
def ser(el):
    """Testo con segnaposto: <a1>..</a1>, <br2/>. Ritorna (testo, {n: tag})."""
    tags = {}
    def rec(e):
        o = ""
        for ch in e.children:
            if isinstance(ch, Comment): continue
            if isinstance(ch, NavigableString): o += str(ch)
            elif isinstance(ch, Tag):
                n = len(tags) + 1; tags[n] = ch
                o += f"<{ch.name}{n}/>" if ch.name in VOID else f"<{ch.name}{n}>" + rec(ch) + f"</{ch.name}{n}>"
        return o
    return rec(el), tags

def rebuild(el, text):
    """Ricostruisce el dal testo tradotto riusando i tag originali (attributi intatti)."""
    _, tags = ser(el)
    for t in tags.values(): t.extract()
    for t in tags.values():
        if t.name not in VOID: t.clear()
    el.clear(); stack = [el]; used = set()
    for m in re.finditer(r"<(/?)([a-z]+)(\d+)(/?)>|([^<]+|<)", text):
        if m.group(5) is not None: stack[-1].append(NavigableString(m.group(5))); continue
        n = int(m.group(3)); t = tags.get(n)
        if t is None: raise ValueError(f"segnaposto sconosciuto {m.group(0)}")
        if m.group(1): stack.pop()
        else:
            stack[-1].append(t); used.add(n)
            if not m.group(4) and t.name not in VOID: stack.append(t)
    return set(tags) - used

def collect(soup):
    """Ritorna lista di (tipo, oggetto, testo_italiano)."""
    out = []
    def walk(el):
        for ch in list(el.children):
            if isinstance(ch, (Comment, Doctype)): continue
            if isinstance(ch, NavigableString):
                if worth(ch): out.append(("str", ch, str(ch)))
            elif isinstance(ch, Tag):
                if ch.name in SKIP or ch.has_attr("data-noi18n"): continue
                if ch.name not in ("html", "head", "body") and is_unit(ch):
                    out.append(("el", ch, ser(ch)[0]))
                else:
                    walk(ch)
    walk(soup)
    for el in soup.find_all(True):
        if el.find_parent(attrs={"data-noi18n": True}) or el.has_attr("data-noi18n"): continue
        for a in ATTRS:
            if el.has_attr(a) and worth(el[a]): out.append(("attr", (el, a), el[a]))
        if el.name == "meta" and (el.get("name") in META or el.get("property") in META) and el.get("content"):
            out.append(("attr", (el, "content"), el["content"]))
        if el.name == "a" and el.has_attr("href"):
            m = re.match(r"^(.*?[?&](?:text|subject)=)([^&#]*)(.*)$", el["href"])
            if m and worth(urllib.parse.unquote(m.group(2))):
                out.append(("href", (el, m), urllib.parse.unquote(m.group(2))))
    for sc in soup.find_all("script"):
        for lit in JS:
            if sc.string and lit in sc.string: out.append(("js", (sc, lit), lit))
    return out

def load(p):
    return BeautifulSoup(open(os.path.join(ROOT, p), encoding="utf8").read(), "html.parser")

def load_tr(code):
    """i18n/<lingua>.tsv : codice<TAB>traduzione"""
    fn = os.path.join(ROOT, "i18n", code + ".tsv"); d = {}
    if os.path.exists(fn):
        for ln in open(fn, encoding="utf8"):
            m = re.match(r"^([0-9a-f]{10})\s+(.*?)\s*$", ln)
            if m: d[m.group(1)] = m.group(2)
    return d

# ---------------- estrazione ----------------
def estrai():
    seen, rows = set(), []
    for p in PAGES:
        for kind, _, txt in collect(load(p)):
            k = key(txt)
            if k in seen: continue
            seen.add(k); rows.append((k, p, norm(txt)))
    os.makedirs(os.path.join(ROOT, "i18n"), exist_ok=True)
    with open(os.path.join(ROOT, "i18n", "testi_it.tsv"), "w", encoding="utf8") as f:
        for k, p, t in rows: f.write(f"{k}\t{p}\t{t}\n")
    print(len(rows), "testi ->", "i18n/testi_it.tsv")
    for code, _ in LANGS[1:]:
        have = load_tr(code)
        miss = [k for k, _, _ in rows if k not in have]
        print(f"  {code}: {len(miss)} MANCANTI")

# ---------------- selettore lingua ----------------
GLOBE = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9.2"/><path d="M2.8 12h18.4M12 2.8c2.6 2.6 3.9 5.6 3.9 9.2s-1.3 6.6-3.9 9.2c-2.6-2.6-3.9-5.6-3.9-9.2S9.4 5.4 12 2.8z"/></svg>'
CHEV = '<svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m3 4.5 3 3 3-3"/></svg>'
CSS = """<style id="cs-lang-css">
.cs-lang{position:relative;display:inline-flex;font-family:inherit;z-index:60}
.cs-lang-btn{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,.03);border:1px solid rgba(148,163,184,.25);color:#cbd5e1;border-radius:10px;padding:7px 10px;font:600 .82rem/1 inherit;letter-spacing:.04em;cursor:pointer;transition:.2s}
.cs-lang-btn:hover,.cs-lang.open .cs-lang-btn{border-color:#38bdf8;color:#f1f5f9}
.cs-lang-btn .chev{transition:transform .2s}.cs-lang.open .chev{transform:rotate(180deg)}
.cs-lang-menu{position:absolute;right:0;top:calc(100% + 8px);min-width:170px;margin:0;padding:6px;list-style:none;background:#0d1524;border:1px solid rgba(148,163,184,.22);border-radius:12px;box-shadow:0 18px 40px -12px rgba(0,0,0,.7);opacity:0;visibility:hidden;transform:translateY(-4px);transition:.18s;display:block!important}
.cs-lang.open .cs-lang-menu{opacity:1;visibility:visible;transform:none}
.cs-lang-menu li{margin:0}
.cs-lang-menu a{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:9px 12px;border-radius:8px;color:#cbd5e1!important;text-decoration:none;font-size:.9rem;font-weight:500}
.cs-lang-menu a small{color:#64748b;font-weight:600;font-size:.72rem;letter-spacing:.06em}
.cs-lang-menu a:hover,.cs-lang-menu a:focus-visible{background:rgba(56,189,248,.1);color:#f1f5f9!important;outline:none}
.cs-lang-menu a[aria-current]{color:#38bdf8!important}
nav{display:flex;align-items:center;gap:18px}
.cs-right{display:flex;align-items:center;gap:16px}
@media(max-width:1000px){nav .cs-lang{order:-1}}
@media(min-width:861px) and (max-width:1000px){.burger{display:block!important}nav ul{display:none!important;position:absolute;top:68px;left:0;right:0;background:var(--bg2);border-bottom:1px solid var(--line);flex-direction:column;padding:20px;gap:18px!important;align-items:flex-start}nav ul.open{display:flex!important}}
@media(min-width:861px) and (max-width:1180px){nav ul{gap:16px!important}nav a{font-size:.86rem!important}nav .btn-sm{padding:8px 12px!important}nav{gap:12px}}
@media(max-width:420px){.cs-right .back{display:none}}
</style>"""
JSCODE = """<script id="cs-lang-js">(function(){document.querySelectorAll('[data-cs-lang]').forEach(function(w){var b=w.querySelector('button');
function set(o){w.classList.toggle('open',o);b.setAttribute('aria-expanded',o)}
b.addEventListener('click',function(e){e.stopPropagation();set(!w.classList.contains('open'))});
document.addEventListener('click',function(e){if(!w.contains(e.target))set(false)});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){set(false)}});
w.querySelectorAll('a[hreflang]').forEach(function(a){a.addEventListener('click',function(){try{localStorage.setItem('cs-lang',a.getAttribute('hreflang'))}catch(_){}})});});})();</script>"""

def rel_up(page, lang): return "../" * (page.count("/") + (lang != "it"))
def url_of(page, lang):
    p = "" if page == "index.html" else page
    return BASE + ("" if lang == "it" else lang + "/") + p

def switcher(page, cur):
    up = rel_up(page, cur)
    items = "".join(
        f'<li><a role="menuitem" href="{up}{"" if c == "it" else c + "/"}{page}" hreflang="{c}" lang="{c}"'
        f'{" aria-current=\"true\"" if c == cur else ""}>{n}<small>{c.upper()}</small></a></li>' for c, n in LANGS)
    return (f'<div class="cs-lang" data-cs-lang data-noi18n><button type="button" class="cs-lang-btn" aria-haspopup="true" '
            f'aria-expanded="false" aria-label="Lingua / Language">{GLOBE}<span>{cur.upper()}</span><span class="chev">{CHEV}</span></button>'
            f'<ul class="cs-lang-menu" role="menu">{items}</ul></div>')

def head_tags(page, cur):
    t = "".join(f'<link rel="alternate" hreflang="{c}" href="{url_of(page, c)}">' for c, _ in LANGS)
    return t + f'<link rel="alternate" hreflang="x-default" href="{url_of(page, "it")}">'

def inject(soup, page, cur):
    for x in soup.select(".cs-lang, #cs-lang-css, #cs-lang-js, link[rel=alternate][hreflang]"): x.decompose()
    for x in soup.select(".cs-right"): x.unwrap()
    sw = BeautifulSoup(switcher(page, cur), "html.parser")
    nav = soup.select_one("header nav")
    if nav: nav.append(sw)
    else:
        back = soup.select_one("header .back")
        wrap = soup.new_tag("div", attrs={"class": "cs-right"}); back.wrap(wrap); wrap.append(sw)
    soup.head.append(BeautifulSoup(CSS + head_tags(page, cur), "html.parser"))
    soup.body.append(BeautifulSoup(JSCODE, "html.parser"))

def set_meta(soup, page, cur):
    soup.html["lang"] = cur
    for sel, attr in (("link[rel=canonical]", "href"), ('meta[property="og:url"]', "content")):
        el = soup.select_one(sel)
        if el: el[attr] = url_of(page, cur)
    el = soup.select_one('meta[property="og:locale"]')
    if el: el["content"] = LOCALE[cur]
    for sc in soup.find_all("script", type="application/ld+json"):
        if sc.string and '"availableLanguage"' in sc.string:
            sc.string = re.sub(r'"availableLanguage":\s*("[^"]*"|\[[^\]]*\])',
                               '"availableLanguage": ["Italian", "English", "French", "Spanish", "German"]', sc.string)

def fix_paths(soup):
    def fix(v):
        if not v or re.match(r"^([a-z]+:|/|#|\.\./\.\./)", v): return v
        base = v.split("#")[0].split("?")[0]
        if base.endswith(".html") or base == "": return v
        return "../" + v
    for el in soup.find_all(True):
        for a in ("src", "href", "poster"):
            if el.has_attr(a): el[a] = fix(el[a])
        if el.has_attr("srcset"):
            el["srcset"] = ", ".join(" ".join([fix(p.split()[0])] + p.split()[1:]) for p in el["srcset"].split(","))
        if el.has_attr("style"): el["style"] = re.sub(r"url\((['\"]?)(?!data:|https?:|/)", r"url(\1../", el["style"])

def translate(soup, tr, stats):
    for kind, obj, txt in collect(soup):
        t = tr.get(key(txt))
        if t is None: stats["miss"].append(norm(txt)[:70]); continue
        if kind == "str":
            s = str(obj); lead = s[:len(s) - len(s.lstrip())]; trail = s[len(s.rstrip()):]
            obj.replace_with(lead + t + trail)
        elif kind == "el":
            s = ser(obj)[0]; lead = s[:len(s) - len(s.lstrip())]; trail = s[len(s.rstrip()):]
            try:
                if rebuild(obj, lead + t + trail): stats["tags"].append(norm(txt)[:70])
            except Exception as e: stats["tags"].append(f"{e}: {norm(txt)[:60]}")
        elif kind == "attr":
            el, a = obj; el[a] = t
        elif kind == "href":
            el, m = obj; el["href"] = m.group(1) + urllib.parse.quote(t) + m.group(3)
        elif kind == "js":
            sc, lit = obj; sc.string = sc.string.replace(lit, t)

MARK = re.compile(r"<!--cs-lang-->.*?<!--/cs-lang-->", re.S)
def wrap_m(x): return "<!--cs-lang-->" + x + "<!--/cs-lang-->"

def inject_text(src, page):
    """Pagina italiana: inserimento chirurgico tra marcatori, il resto del file resta identico."""
    src = MARK.sub("", src)
    sw = switcher(page, "it")
    if re.search(r"<header>.*?</nav>", src, re.S):
        src = re.sub(r"(<header>.*?)(</nav>)", lambda m: m.group(1) + wrap_m(sw) + m.group(2), src, count=1, flags=re.S)
    else:
        src = re.sub(r'(<a class="back"[^>]*>.*?</a>)', lambda m: wrap_m('<div class="cs-right">') + m.group(1) + wrap_m(sw + "</div>"), src, count=1, flags=re.S)
    src = src.replace("</head>", wrap_m(CSS + head_tags(page, "it")) + "</head>", 1)
    src = src.replace("</body>", wrap_m(JSCODE) + "</body>", 1)
    return re.sub(r'"availableLanguage":\s*("[^"]*"|\[[^\]]*\])',
                  '"availableLanguage": ["Italian", "English", "French", "Spanish", "German"]', src)

def sitemap():
    import datetime
    today = datetime.date.today().isoformat()
    pri = lambda p: "1.0" if p == "index.html" else "0.3" if p == "privacy.html" else "0.8"
    alts = lambda p: "".join(f'\n    <xhtml:link rel="alternate" hreflang="{c}" href="{url_of(p, c)}"/>' for c, _ in LANGS) + \
        f'\n    <xhtml:link rel="alternate" hreflang="x-default" href="{url_of(p, "it")}"/>'
    rows = [f"  <url>\n    <loc>{url_of(p, c)}</loc>\n    <lastmod>{today}</lastmod>\n    <priority>{pri(p)}</priority>{alts(p)}\n  </url>"
            for p in PAGES for c, _ in LANGS]
    open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(rows) + "\n</urlset>\n")

def build():
    trs = {c: load_tr(c) for c, _ in LANGS[1:]}
    for page in PAGES:
        # pagina italiana: solo selettore + hreflang (testo invariato)
        raw = open(os.path.join(ROOT, page), encoding="utf8").read()
        open(os.path.join(ROOT, page), "w", encoding="utf8").write(inject_text(raw, page))
        src = MARK.sub("", raw)
        for c, _ in LANGS[1:]:
            s = BeautifulSoup(src, "html.parser"); stats = {"miss": [], "tags": []}
            translate(s, trs[c], stats); set_meta(s, page, c); fix_paths(s); inject(s, page, c)
            out = os.path.join(ROOT, c, page); os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "w", encoding="utf8").write(str(s))
            if stats["miss"] or stats["tags"]:
                print(f"[{c}] {page}: {len(stats['miss'])} mancanti, {len(stats['tags'])} con tag diversi")
                for m in stats["miss"][:5]: print("     manca:", m)
                for m in stats["tags"][:5]: print("     tag:", m)
    sitemap()
    print("OK: generate", ", ".join(f"/{c}/" for c, _ in LANGS[1:]), "per", len(PAGES), "pagine")

if __name__ == "__main__":
    estrai() if sys.argv[1:] == ["estrai"] else build()

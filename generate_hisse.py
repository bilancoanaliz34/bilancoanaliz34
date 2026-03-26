"""
GitHub Actions tarafından çalıştırılan script.
index.html'den dashboard bölümlerini çıkarır,
Google Sheets'ten veriyi okur ve hisse sayfaları oluşturur.
"""

import os, re, json, gzip, base64, sys

# ── index.html'den bölümleri çıkar ───────────────────────────────────────────
print("index.html okunuyor...")
with open('index.html', 'r', encoding='utf-8') as f:
    c = f.read()

style_start = c.find('<style>') + 7
style_end   = c.find('</style>')
main_css    = c[style_start:style_end]

idx_dh = c.find('<div id="dash">')
idx_de = c.find('<!-- Policy Modal -->')
dash_html = c[idx_dh:idx_de].strip()

idx_js = c.find('\n// GLOBALS\n')
idx_je = c.find('\nfunction resetApp()')
core_js = c[idx_js:idx_je]
for var in ['let D={};','let CHS=[];','let VERI={};','let LOGOS={};',
            "let activePeriod='';", 'let D = {};', 'let CHS = [];']:
    core_js = core_js.replace(var, '')

idx_pm = c.find('<!-- Policy Modal -->')
idx_en = c.find('</body>')
modals = c[idx_pm:idx_en].strip()

print(f"✓ CSS: {len(main_css)} kar, JS: {len(core_js)} kar")

# ── VDATA'dan mevcut hisse listesini al ───────────────────────────────────────
print("VDATA okunuyor...")
idx_vd = c.find('id="VDATA"')
end_vd = c.find('</script>', idx_vd)
b64    = c[idx_vd:end_vd].split('>',1)[1].strip()
VERI   = json.loads(gzip.decompress(base64.b64decode(b64)).decode('utf-8'))
print(f"✓ VDATA'dan {len(VERI)} hisse alındı")

# ── Google Sheets'ten güncel veriyi çek ───────────────────────────────────────
import requests

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1a43dQuEOx9C5qrZqpSLePc172U8fxH1ouFBYYk9YS48/gviz/tq?tqx=out:csv&sheet=veri'

def num(v):
    if v is None: return None
    s = str(v).replace(' ','').strip()
    dp = s.split('.')
    cp = s.split(',')
    if len(dp) > 2:   s = s.replace('.','')
    elif len(cp) > 2: s = s.replace(',','')
    elif len(dp)==2 and len(dp[1])>2: s = s.replace('.','')
    elif len(cp)==2 and len(cp[1])>2: s = s.replace(',','')
    else: s = s.replace(',','.')
    try: return float(s)
    except: return None

def numi(v):
    n = num(v)
    return None if n is None else int(round(n))

def sort_key(p):
    y, m = str(p).split('/')
    return int(y)*100 + int(m or 0)

def parse_line(line):
    result, cur, inq = [], '', False
    for ch in line:
        if ch == '"': inq = not inq
        elif ch == ',' and not inq: result.append(cur.strip()); cur = ''
        else: cur += ch
    result.append(cur.strip())
    return [v.strip('"') for v in result]

try:
    print("Google Sheets'ten veri çekiliyor...")
    resp = requests.get(SHEET_URL, timeout=30)
    resp.raise_for_status()
    lines = resp.text.strip().split('\n')
    print(f"✓ {len(lines)} satır geldi")

    VERI_NEW = {}
    for line in lines[2:]:
        row = parse_line(line)
        if len(row) < 40: continue
        ticker = row[1].strip().upper()
        donem  = row[3].strip()
        if not ticker or not donem or '/' not in donem: continue

        # Bilanço tarihi
        bilTarih = row[6].strip()
        dm = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', bilTarih)
        if dm: bilTarih = f"{dm.group(3)}-{dm.group(2).zfill(2)}-{dm.group(1).zfill(2)}"

        yo_raw = num(row[30])
        yo_val = None if yo_raw is None else (round(yo_raw) if yo_raw > 1 else round(yo_raw*100))


        row_data = {
            'fd':num(row[15]),'pd':num(row[10]),'fiyat':num(row[8]),'adet':num(row[9]),
            'donenV':num(row[11]),'duranV':num(row[12]),'kvYuk':num(row[13]),'uvYuk':num(row[14]),
            'oz':num(row[16]),'brutKar':num(row[17]),'faalKar':num(row[21]),'favok':num(row[22]),
            'netBorc':num(row[23]),'netKar':num(row[24]),'satislar':num(row[25]),'roe':num(row[26]),
            'ol':numi(row[27]),'no':numi(row[28]),'ols':numi(row[29]),'yo':yo_val,
            'pddd':num(row[31]),'fk':num(row[32]),'fdFavok':num(row[33]),'pdNfk':num(row[34]),
            'fdNs':num(row[35]),'nfkPd':num(row[36]),'nbFavok':num(row[37]),'efk':num(row[38]),'hbk':num(row[39]),
        }
        dv, drv = row_data.get('donenV'), row_data.get('duranV')
        row_data['tv'] = (dv + drv) if dv is not None and drv is not None else None

        if ticker not in VERI_NEW:
            VERI_NEW[ticker] = {
                'ticker':ticker, 'company':row[5].strip(), 'sector':row[4].strip(),
                'puan':None, 'bilancoTarih':None, 'periods':[], 'rows':{}
            }
        t = VERI_NEW[ticker]
        if donem not in t['periods']: t['periods'].append(donem)
        t['rows'][donem] = row_data
        if bilTarih and (not t['bilancoTarih'] or bilTarih > t['bilancoTarih']):
            t['bilancoTarih'] = bilTarih

    for t in VERI_NEW:
        VERI_NEW[t]['periods'].sort(key=sort_key, reverse=True)
        p0 = VERI_NEW[t]['periods'][0] if VERI_NEW[t]['periods'] else None
        if p0:
            r0 = VERI_NEW[t]['rows'].get(p0, {})
            if r0.get('yo') is not None:
                VERI_NEW[t]['puan'] = r0['yo']
            # Son dönemden olumlu/notr/olumsuz doldur
            if r0.get('ol') is not None:
                VERI_NEW[t]['olumlu']  = r0['ol']
                VERI_NEW[t]['notr']    = r0['no']
                VERI_NEW[t]['olumsuz'] = r0['ols']

    if len(VERI_NEW) > 100:
        VERI = VERI_NEW
        print(f"✓ Google Sheets'ten {len(VERI)} hisse güncellendi")
    else:
        print(f"⚠ Google Sheets sadece {len(VERI_NEW)} hisse döndürdü, VDATA kullanılıyor")

except Exception as e:
    print(f"⚠ Google Sheets hatası: {e} — VDATA kullanılıyor")

# ── Hisse sayfası template ───────────────────────────────────────────────────
def make_hisse_page(ticker, info):
    company   = info.get('company', ticker)
    sector    = info.get('sector', '')
    son_donem = info.get('periods', [''])[0]
    puan      = info.get('puan', 0) or 0
    desc = (f"{company} ({ticker}) bilanço analizi: {son_donem} dönemi finansal rasyolar, "
            f"dönemsel büyüme grafikleri ve ONO analiz skoru. Sektör: {sector}.")
    hisse_json = json.dumps({ticker: info}, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{ticker} Bilanço Analizi — {company} | BilancoAnaliz34</title>
  <meta name="description" content="{desc}">
  <meta name="keywords" content="{ticker}, {company}, {ticker} bilanço, {ticker} analiz, {sector.lower()}, BIST hisse analizi">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="https://bilancoanaliz34.com.tr/hisse/{ticker.lower()}.html">
  <meta property="og:title" content="{ticker} Bilanço Analizi | BilancoAnaliz34">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="https://bilancoanaliz34.com.tr/logo-512.png">
  <link rel="icon" href="/favicon.ico">
  <script type="application/ld+json">
  {{"@context":"https://schema.org","@type":"FinancialProduct","name":"{company} ({ticker})","description":"{desc}","url":"https://bilancoanaliz34.com.tr/hisse/{ticker.lower()}.html","provider":{{"@type":"Organization","name":"BilancoAnaliz34","url":"https://bilancoanaliz34.com.tr"}}}}
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Playfair+Display:wght@700;900&family=Source+Serif+4:wght@400;500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
  <style>
  {main_css}
  #upload-screen {{ display: none !important; }}
  #dash {{ display: block !important; }}
  </style>
</head>
<body>
<script>
var VERI = {hisse_json};
var LOGOS = {{}};
var D = {{}};
var CHS = [];
var activePeriod = '';
</script>
{dash_html}
{modals}
<script>
{core_js}
window.addEventListener('load', function() {{
  var ticker = '{ticker}';
  var SHEET = 'https://docs.google.com/spreadsheets/d/1a43dQuEOx9C5qrZqpSLePc172U8fxH1ouFBYYk9YS48/gviz/tq?tqx=out:csv&sheet=veri';

  function initDash(info) {{
    var sp = [...info.periods].sort(function(a,b){{
      var a2=a.split('/'),b2=b.split('/');
      return (parseInt(b2[0])*100+parseInt(b2[1]))-(parseInt(a2[0])*100+parseInt(a2[1]));
    }});
    var p0 = sp[0];
    var r0 = info.rows[p0] || {{}};
    var olumlu  = (info.olumlu  != null) ? info.olumlu  : (r0.ol  != null ? r0.ol  : 0);
    var notr    = (info.notr    != null) ? info.notr    : (r0.no  != null ? r0.no  : 0);
    var olumsuz = (info.olumsuz != null) ? info.olumsuz : (r0.ols != null ? r0.ols : 0);
    var puan    = (info.puan    != null) ? info.puan    : (r0.yo  != null ? r0.yo  : 0);
    D = {{ticker:ticker,periods:sp,rows:info.rows,sector:info.sector,
          company:info.company,olumlu:olumlu,notr:notr,
          olumsuz:olumsuz,puan:puan}};
    buildDash();
    ['btn-paylas','btn-paylas-home'].forEach(function(id){{
      var el=document.getElementById(id);
      if(el) el.style.display='inline-flex';
    }});
  }}

  // Google Sheets'ten canlı veri çek, ol/no/ols/yo güncelle
  fetch(SHEET)
    .then(function(r){{ return r.text(); }})
    .then(function(csv){{
      var fresh = parseCSV(csv);
      if(fresh && fresh[ticker]) {{
        // VERI'yi güncelle
        VERI[ticker] = fresh[ticker];
      }}
      var info = VERI[ticker];
      if(!info) {{ console.error('Hisse bulunamadı: ' + ticker); return; }}
      initDash(info);
    }})
    .catch(function(){{
      // Google Sheets başarısız → statik VERI kullan
      var info = VERI[ticker];
      if(!info) {{ console.error('Hisse bulunamadı: ' + ticker); return; }}
      initDash(info);
    }});
}});
function resetApp(){{ window.location.href='/'; }}
function showErr(m){{ console.error(m); }}
function hideErr(){{}}
function openAdmin(){{}} function closeAdmin(){{}}
function handleExcelUpload(){{}} function handleLogoUpload(){{}}
function acceptCookies(){{
  try{{localStorage.setItem('ba34_cookie_ok','1');}}catch(e){{}}
  var b=document.getElementById('cookie-banner');if(b)b.style.display='none';
}}
function showPolicy(){{
  var m=document.getElementById('policy-modal');if(m)m.style.display='flex';
}}
function toggleBlogMenu(e){{
  e.stopPropagation();
  ['blog-dropdown','blog-dropdown-home'].forEach(function(id){{
    var el=document.getElementById(id);if(el)el.classList.toggle('open');
  }});
}}
document.addEventListener('click',function(){{
  ['blog-dropdown','blog-dropdown-home'].forEach(function(id){{
    var el=document.getElementById(id);if(el)el.classList.remove('open');
  }});
}});
</script>
</body>
</html>"""

# ── Sayfaları oluştur ─────────────────────────────────────────────────────────
os.makedirs('hisse', exist_ok=True)
count = 0
for ticker, info in VERI.items():
    with open(f'hisse/{ticker.lower()}.html', 'w', encoding='utf-8') as f:
        f.write(make_hisse_page(ticker, info))
    count += 1

print(f"✓ {count} hisse sayfası oluşturuldu → hisse/")

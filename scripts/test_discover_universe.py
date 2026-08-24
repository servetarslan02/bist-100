import sys
import urllib.request
import re
import orjson

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

tickers = set()

# Source 1: Is Yatirim full stock list
try:
    url = 'https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/default.aspx'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
    matches = re.findall(r'value="([A-Z0-9]{3,6})"\s*data-title=', html)
    tickers.update(matches)
    print(f'İş Yatırım Source Found: {len(matches)} tickers')
except Exception as e:
    print('Is Yatirim Err:', e)

# Source 2: Bigpara live stock list
try:
    url = 'https://bigpara.hurriyet.com.tr/borsa/canli-borsa/'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
    matches = re.findall(r'/borsa/hisse-fiyatlari/([a-z0-9]+)-detay/', html)
    tickers.update([m.upper() for m in matches])
    print(f'Bigpara Source Found: {len(matches)} tickers')
except Exception as e:
    print('Bigpara Err:', e)

# Source 3: Mynet Finans
try:
    url = 'https://finans.mynet.com/borsa/hisseler/'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
    matches = re.findall(r'/borsa/hisseler/([a-z0-9]{3,6})-', html)
    tickers.update([m.upper() for m in matches])
    print(f'Mynet Source Found: {len(matches)} tickers')
except Exception as e:
    print('Mynet Err:', e)

clean_tickers = sorted([t for t in tickers if 2 <= len(t) <= 6 and not t.isdigit()])
print(f'TOTAL UNIQUE BIST TICKERS DISCOVERED: {len(clean_tickers)}')
print('Örnekler:', clean_tickers[:30])

"""
Test Turkish financial portals: Doviz.com, Bigpara, Mynet, IsYatirim
"""
import requests
import orjson
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def test_doviz_bist():
    url = "https://www.doviz.com/api/v1/currencies/all/latest"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        print("Doviz.com Status:", r.status_code)
    except Exception as e:
        print("Doviz.com Error:", e)

def test_bigpara_live():
    url = "https://bigpara.hurriyet.com.tr/api/v1/borsa/hissemarket"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        print("Bigpara hissemarket Status:", r.status_code)
        if r.status_code == 200:
            print("Bigpara Sample:", r.text[:200])
    except Exception as e:
        print("Bigpara Error:", e)

if __name__ == "__main__":
    test_doviz_bist()
    test_bigpara_live()

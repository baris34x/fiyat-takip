from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bs4 import BeautifulSoup
import re
import json
import urllib.parse
from curl_cffi import requests as curl_requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

products = []

class ProductCreate(BaseModel):
    name: str
    store: str
    target_price: float
    url: str

def clean_price(val) -> float:
    """Gelen ham fiyat metnini veya sayısını temizleyip float tipine dönüştürür."""
    try:
        if isinstance(val, (int, float)):
            return float(val)
        clean = str(val).strip().replace('.', '').replace(',', '.')
        match = re.search(r'\d+(\.\d+)?', clean)
        if match:
            return float(match.group(0))
    except Exception:
        pass
    return 0.0

def resolve_url(url: str) -> str:
    """Kısaltılmış mobil linkleri (ty.gl, amzn.eu vb.) gerçek ürün adresine çözer."""
    try:
        res = curl_requests.head(url, impersonate="chrome120", follow_redirects=True, timeout=5)
        if res.url:
            return res.url
    except Exception:
        pass
    try:
        res = curl_requests.get(url, impersonate="chrome120", follow_redirects=True, timeout=5)
        if res.url:
            return res.url
    except Exception:
        pass
    return url

def extract_trendyol(final_url: str, html: str) -> float:
    """Trendyol API ve HTML ayrıştırıcı."""
    # 1. API Tüneli (-p- Ürün ID Sökücü)
    match_id = re.search(r'-p-(\d+)', final_url) or re.search(r'/p-(\d+)', final_url)
    if match_id:
        product_id = match_id.group(1)
        api_url = f"https://public-mdc.trendyol.com/discovery-web-productdetail-gwb-service/api/productDetail/{product_id}"
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Culture": "tr-TR"
            }
            res = curl_requests.get(api_url, headers=headers, impersonate="chrome120", timeout=6)
            if res.status_code == 200:
                data = res.json()
                price_info = data.get('result', {}).get('price', {})
                p_val = price_info.get('discountedPrice', {}).get('value') or \
                        price_info.get('sellingPrice', {}).get('value') or \
                        price_info.get('originalPrice', {}).get('value')
                val = clean_price(p_val)
                if val > 0:
                    return val
        except Exception as e:
            print("Trendyol API Hatası:", e)

    # 2. HTML / Script İçi Parsing (Yedek)
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        selectors = ['span.prc-dsc', '.prc-dsc', '.prc-box-sll', '.prc-box-dsc']
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                val = clean_price(el.get_text())
                if val > 0:
                    return val
    return 0.0

def extract_hepsiburada(html: str) -> float:
    """Hepsiburada DOM ve Script State ayrıştırıcı."""
    if not html:
        return 0.0
    soup = BeautifulSoup(html, 'html.parser')

    hb_selectors = [
        '[data-test-id="price-current-price"]',
        '.price-bold',
        'span[data-bind*="currentPrice"]',
        '#offering-price'
    ]
    for sel in hb_selectors:
        el = soup.select_one(sel)
        if el:
            val = clean_price(el.get_text())
            if val > 0:
                return val

    for script in soup.find_all('script'):
        stext = script.string or ""
        if 'currentPrice' in stext or 'hbPrice' in stext:
            matches = re.findall(r'"currentPrice":\s*([\d.]+)', stext) or \
                      re.findall(r'"hbPrice":\s*([\d.]+)', stext) or \
                      re.findall(r'"price":\s*([\d.]+)', stext)
            if matches:
                val = clean_price(matches[0])
                if val > 0:
                    return val
    return 0.0

def extract_generic_schema(html: str) -> float:
    """Tüm e-ticaret siteleri için evrensel JSON-LD ve Meta Tag ayrıştırıcı."""
    if not html:
        return 0.0
    soup = BeautifulSoup(html, 'html.parser')

    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data_json = json.loads(script.string)
            items = data_json if isinstance(data_json, list) else [data_json]
            for item in items:
                if 'offers' in item:
                    offers = item['offers']
                    offer_list = offers if isinstance(offers, list) else [offers]
                    for offer in offer_list:
                        price_raw = offer.get('price') or offer.get('lowPrice')
                        if price_raw:
                            val = clean_price(price_raw)
                            if val > 0:
                                return val
        except Exception:
            continue

    for meta_prop in ['product:price:amount', 'og:price:amount', 'price']:
        meta_price = soup.find('meta', property=meta_prop) or soup.find('meta', attrs={'name': meta_prop})
        if meta_price and meta_price.get('content'):
            val = clean_price(meta_price['content'])
            if val > 0:
                return val

    return 0.0

def fetch_real_price(url: str):
    """Linkleri çözerek canlı fiyatı kazır."""
    try:
        # En başta kısaltılmış linkleri gerçek hedefe çözüyoruz
        final_url = resolve_url(url)
        url_lower = final_url.lower()

        # 1. Trendyol Özel Yaklaşımı
        if 'trendyol.com' in url_lower:
            price = extract_trendyol(final_url, "")
            if price > 0:
                return price

        # 2. Chrome TLS Impersonation ile Sayfa HTML İndirme
        res = curl_requests.get(final_url, impersonate="chrome120", timeout=8, follow_redirects=True)
        html_content = res.text if res.status_code == 200 else ""

        # 3. Mağazaya Özel Ayrıştırıcılara Yönlendirme
        if 'trendyol.com' in url_lower:
            return extract_trendyol(final_url, html_content) or extract_generic_schema(html_content)
        elif 'hepsiburada.com' in url_lower:
            return extract_hepsiburada(html_content) or extract_generic_schema(html_content)
        else:
            return extract_generic_schema(html_content)

    except Exception as e:
        print("Kazıma genel hatası:", e)
        return None

@app.get("/api/search")
def search_products(q: str):
    if not q:
        return []

    q_clean = q.strip()
    q_encoded = urllib.parse.quote(q_clean)

    popular_stores = [
        {"name": f"{q_clean} - Trendyol", "store": "Trendyol", "price": None, "url": f"https://www.trendyol.com/sr?q={q_encoded}"},
        {"name": f"{q_clean} - Amazon TR", "store": "Amazon TR", "price": None, "url": f"https://www.amazon.com.tr/s?k={q_encoded}"},
        {"name": f"{q_clean} - Hepsiburada", "store": "Hepsiburada", "price": None, "url": f"https://www.hepsiburada.com/ara?q={q_encoded}"},
        {"name": f"{q_clean} - N11", "store": "N11", "price": None, "url": f"https://www.n11.com/arama?q={q_encoded}"},
        {"name": f"{q_clean} - Pazarama", "store": "Pazarama", "price": None, "url": f"https://www.pazarama.com/arama?q={q_encoded}"},
        {"name": f"{q_clean} - Çiçeksepeti", "store": "Çiçeksepeti", "price": None, "url": f"https://www.ciceksepeti.com/arama?query={q_encoded}"},
        {"name": f"{q_clean} - İncehesap", "store": "İncehesap", "price": None, "url": f"https://www.incehesap.com/arama/?q={q_encoded}"}
    ]

    return popular_stores

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Axion Engine Active"}

@app.get("/api/products")
def get_products():
    return products

@app.post("/api/add-product")
def add_product(item: ProductCreate):
    scraped_price = fetch_real_price(item.url)
    final_price = scraped_price if (scraped_price and scraped_price > 0) else 0.0

    new_prod = {
        "id": str(len(products) + 1),
        "name": item.name,
        "store": item.store,
        "target_price": item.target_price,
        "current_price": final_price,
        "initial_price": final_price,
        "url": item.url
    }
    products.append(new_prod)
    return new_prod

@app.post("/api/check-prices")
def check_prices():
    updated = 0
    for prod in products:
        new_price = fetch_real_price(prod["url"])
        if new_price and new_price > 0:
            prod["current_price"] = new_price
            updated += 1
    return {"message": "Fiyatlar güncellendi", "updated": updated}

@app.delete("/api/products/{prod_id}")
def delete_product(prod_id: str):
    global products
    products = [p for p in products if p["id"] != prod_id]
    return {"message": "Silindi"}

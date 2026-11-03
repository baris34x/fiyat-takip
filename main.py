from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re
import json
import urllib.parse

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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"'
}

def clean_price(val) -> float:
    """Metin veya sayı olarak gelen fiyat bilgisini güvenli float tipe dönüştürür."""
    if not val:
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        
        s = str(val).strip()
        matches = re.findall(r'\d+(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?|\d+', s)
        for m in matches:
            cleaned = m.replace('.', '').replace(',', '.')
            try:
                v = float(cleaned)
                if v > 0:
                    return v
            except ValueError:
                continue
    except Exception:
        pass
    return 0.0

def resolve_url(url: str) -> str:
    """Mobil ve yönlendirmeli bağlantıları çözer."""
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        res = session.get(url, allow_redirects=True, timeout=5)
        return res.url
    except Exception:
        return url

def fetch_trendyol_price(url: str) -> float:
    """Trendyol ürün kodunu (-p-123456) söküp doğrudan API üzerinden fiyatı alır."""
    match_id = re.search(r'[-/]p-(\d+)', url) or re.search(r'pi=(\d+)', url)
    if match_id:
        pid = match_id.group(1)
        api_url = f"https://public-mdc.trendyol.com/discovery-web-productdetail-gwb-service/api/productDetail/{pid}"
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Culture": "tr-TR",
                "x-storefront-id": "1"
            }
            res = requests.get(api_url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                p_info = data.get('result', {}).get('price', {})
                val = p_info.get('discountedPrice', {}).get('value') or \
                      p_info.get('sellingPrice', {}).get('value') or \
                      p_info.get('originalPrice', {}).get('value')
                price = clean_price(val)
                if price > 0:
                    return price
        except Exception:
            pass
    return 0.0

def fetch_page_html(url: str) -> str:
    """Sayfa HTML içeriğini doğrudan veya proxy tünelleri üzerinden çeker."""
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # 1. Doğrudan İstek
    try:
        res = session.get(url, timeout=5)
        if res.status_code == 200 and len(res.text) > 500:
            return res.text
    except Exception:
        pass
        
    # 2. Proxy Tünel 1 (AllOrigins)
    try:
        proxy_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}"
        res = session.get(proxy_url, timeout=5)
        if res.status_code == 200 and len(res.text) > 500:
            return res.text
    except Exception:
        pass

    # 3. Proxy Tünel 2 (CorsProxy)
    try:
        proxy_url = f"https://corsproxy.io/?{urllib.parse.quote(url)}"
        res = session.get(proxy_url, timeout=5)
        if res.status_code == 200 and len(res.text) > 500:
            return res.text
    except Exception:
        pass

    return ""

def fetch_real_price(url: str) -> float:
    """Amazon, Trendyol, Hepsiburada ve tüm mağazalardan fiyatı kazır."""
    try:
        final_url = resolve_url(url)
        url_lower = final_url.lower()

        # 1. TRENDYOL ÖZEL API SÜZÜCÜ
        if 'trendyol.com' in url_lower:
            price = fetch_trendyol_price(final_url)
            if price > 0:
                return price

        # 2. HTML İÇERİĞİNİ YÜKLE
        html = fetch_page_html(final_url)
        if not html:
            return 0.0

        soup = BeautifulSoup(html, 'html.parser')

        # 3. AMAZON ÖZEL SELECTOR'LARI (Amazon'da Çalışan Orijinal Mantık)
        if 'amazon' in url_lower:
            amazon_selectors = [
                'span.a-price span.a-offscreen',
                '.a-price-whole',
                '#priceblock_ourprice',
                '#priceblock_dealprice',
                'span.a-color-price'
            ]
            for sel in amazon_selectors:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text())
                    if price > 0:
                        return price

        # 4. HEPSİBURADA ÖZEL SELECTOR'LARI
        if 'hepsiburada' in url_lower:
            hb_selectors = [
                '[data-test-id="price-current-price"]',
                '.price-bold',
                '#offering-price'
            ]
            for sel in hb_selectors:
                el = soup.select_one(sel)
                if el:
                    price = clean_price(el.get_text())
                    if price > 0:
                        return price

        # 5. GENEL MAĞAZA SELECTOR'LARI
        general_selectors = [
            'span.prc-dsc', '.prc-dsc', '.prc-box-sll',
            '.product-price-container', '.priceContainer .price'
        ]
        for sel in general_selectors:
            el = soup.select_one(sel)
            if el:
                price = clean_price(el.get_text())
                if price > 0:
                    return price

        # 6. EVRENSEL JSON-LD ŞEMA TARAMASI
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data_json = json.loads(script.string)
                items = data_json if isinstance(data_json, list) else [data_json]
                for item in items:
                    if 'offers' in item:
                        offers = item['offers']
                        offer_list = offers if isinstance(offers, list) else [offers]
                        for offer in offer_list:
                            p_raw = offer.get('price') or offer.get('lowPrice')
                            price = clean_price(p_raw)
                            if price > 0:
                                return price
            except Exception:
                continue

        # 7. META TAG TARAMASI
        for meta_prop in ['product:price:amount', 'og:price:amount', 'price']:
            meta_price = soup.find('meta', property=meta_prop) or soup.find('meta', attrs={'name': meta_prop})
            if meta_price and meta_price.get('content'):
                price = clean_price(meta_price['content'])
                if price > 0:
                    return price

        return 0.0
    except Exception as e:
        print("Kazıma hatası:", e)
        return 0.0

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

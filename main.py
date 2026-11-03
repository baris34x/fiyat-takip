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
}

def clean_price(val) -> float:
    """Türkçe fiyat formatlarını (Örn: 28.214,00 TL -> 28214.0) doğru sayıya çevirir."""
    if val is None:
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        
        s = str(val).strip()
        # Sadece rakam, nokta ve virgülü tut
        s = re.sub(r'[^\d.,]', '', s)
        if not s:
            return 0.0
        
        if ',' in s and '.' in s:
            s = s.replace('.', '').replace(',', '.')
        elif ',' in s:
            s = s.replace(',', '.')
        elif '.' in s:
            parts = s.split('.')
            if len(parts) > 2:
                s = "".join(parts)
            elif len(parts) == 2 and len(parts[1]) == 3:
                s = parts[0] + parts[1]

        match = re.search(r'\d+(\.\d+)?', s)
        if match:
            return float(match.group(0))
    except Exception:
        pass
    return 0.0

def resolve_url(url: str) -> str:
    """Kısaltılmış ve mobil linkleri çözer."""
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        res = session.head(url, allow_redirects=True, timeout=4)
        return res.url
    except Exception:
        try:
            res = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=4)
            return res.url
        except Exception:
            return url

def fetch_real_price(url: str):
    """Amazon, Trendyol, Hepsiburada ve diğer mağazalar için stabil fiyat kazıma."""
    try:
        final_url = resolve_url(url)
        url_lower = final_url.lower()

        # 1. TRENDYOL İÇİN DİREKT API + SCRIPT PARSING
        if 'trendyol.com' in url_lower:
            match_id = re.search(r'-p-(\d+)', final_url) or re.search(r'/p-(\d+)', final_url)
            if match_id:
                product_id = match_id.group(1)
                api_url = f"https://public-mdc.trendyol.com/discovery-web-productdetail-gwb-service/api/productDetail/{product_id}"
                try:
                    res = requests.get(api_url, headers=HEADERS, timeout=5)
                    if res.status_code == 200:
                        data = res.json()
                        price_info = data.get('result', {}).get('price', {})
                        p_val = price_info.get('discountedPrice', {}).get('value') or \
                                price_info.get('sellingPrice', {}).get('value') or \
                                price_info.get('originalPrice', {}).get('value')
                        val = clean_price(p_val)
                        if val > 0:
                            return val
                except Exception:
                    pass

        # 2. SAYFA HTML İÇERİĞİNİ İNDİRME (Standart Requests + Proxy Fallback)
        session = requests.Session()
        session.headers.update(HEADERS)
        html_content = ""

        try:
            res = session.get(final_url, timeout=5)
            if res.status_code == 200:
                html_content = res.text
        except Exception:
            pass

        if not html_content:
            try:
                proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(final_url)}"
                res = session.get(proxy_url, timeout=5)
                if res.status_code == 200:
                    html_content = res.json().get('contents', '')
            except Exception:
                pass

        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')

        # 3. AMAZON ÖZEL SELECTOR'LARI
        if 'amazon' in url_lower:
            amazon_selectors = [
                'span.a-price span.a-offscreen',
                '.a-price-whole',
                '#priceblock_ourprice',
                '#priceblock_dealprice',
                '.a-price .a-offscreen'
            ]
            for sel in amazon_selectors:
                el = soup.select_one(sel)
                if el:
                    val = clean_price(el.get_text())
                    if val > 0:
                        return val

        # 4. HEPSİBURADA & TRENDYOL DOM SELECTOR'LARI
        primary_selectors = [
            'span.prc-dsc', '.prc-dsc',                            # Trendyol
            '[data-test-id="price-current-price"]', '.price-bold',  # Hepsiburada
            '.product-price-container', '.prc-box-sll'
        ]

        for sel in primary_selectors:
            el = soup.select_one(sel)
            if el:
                val = clean_price(el.get_text())
                if val > 0:
                    return val

        # 5. SCRIPT VE JSON-LD İÇİ VERİ TARAMASI
        for script in soup.find_all('script'):
            stext = script.string or ""
            if 'discountedPrice' in stext or 'currentPrice' in stext or 'hbPrice' in stext:
                matches = re.findall(r'"discountedPrice":\s*([\d.]+)', stext) or \
                          re.findall(r'"currentPrice":\s*([\d.]+)', stext) or \
                          re.findall(r'"hbPrice":\s*([\d.]+)', stext)
                if matches:
                    val = clean_price(matches[0])
                    if val > 0:
                        return val

        # 6. EVRENSEL JSON-LD TARAMASI
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

        # 7. META TAG TARAMASI
        for meta_prop in ['product:price:amount', 'og:price:amount', 'price']:
            meta_price = soup.find('meta', property=meta_prop) or soup.find('meta', attrs={'name': meta_prop})
            if meta_price and meta_price.get('content'):
                val = clean_price(meta_price['content'])
                if val > 0:
                    return val

        return None
    except Exception as e:
        print("Kazıma hatası:", e)
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

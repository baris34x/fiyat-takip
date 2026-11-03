from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re
import json

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
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    'Accept-Language': 'tr-TR,tr;q=0.9',
}

def resolve_url(url: str) -> str:
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        res = session.head(url, allow_redirects=True, timeout=4)
        return res.url
    except Exception:
        try:
            res = session.get(url, headers=HEADERS, allow_redirects=True, timeout=4)
            return res.url
        except Exception:
            return url

def fetch_real_price(url: str):
    """Trendyol, Amazon ve Hepsiburada için bot kalkanını proxy + JS state parsing ile aşar."""
    try:
        final_url = resolve_url(url)
        session = requests.Session()
        session.headers.update(HEADERS)

        html_content = ""
        
        # 1. Önce Proxy Tüneli (Trendyol Bot Engellerini Aşmak İçin En Etkili Yol)
        try:
            proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(final_url)}"
            res = session.get(proxy_url, timeout=6)
            if res.status_code == 200:
                data = res.json()
                html_content = data.get('contents', '')
        except Exception:
            pass

        # 2. Proxy Yanıt Vermezse Doğrudan İstek Denemesi
        if not html_content:
            try:
                res = session.get(final_url, timeout=5)
                if res.status_code == 200:
                    html_content = res.text
            except Exception:
                pass

        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_price = None

        # A. TRENDYOL İÇİN SCRIPT İÇİ KESİN VERİ PARSING (HTML Engellense Bile Çalışır)
        if 'trendyol.com' in final_url.lower():
            for script in soup.find_all('script'):
                script_text = script.string or ""
                if 'discountedPrice' in script_text or 'sellingPrice' in script_text:
                    price_matches = re.findall(r'"sellingPrice":\s*([\d.]+)', script_text) or re.findall(r'"discountedPrice":\s*([\d.]+)', script_text)
                    if price_matches:
                        try:
                            val = float(price_matches[0])
                            if val > 0:
                                extracted_price = val
                                break
                        except Exception:
                            pass

        # B. HTML NOKTA ATIŞI FİYAT SELECTOR'LARI
        if not extracted_price:
            primary_selectors = [
                'span.prc-dsc', '.prc-dsc',                           # Trendyol Fiyat
                '[data-test-id="price-current-price"]', '.price-bold', # Hepsiburada Fiyat
                '.a-price-whole', '#priceblock_ourprice',            # Amazon Fiyat
                '.product-price-container', '.prc-box-sll'
            ]

            for sel in primary_selectors:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text().strip()
                    clean_text = text.replace('.', '').replace(',', '.')
                    match = re.search(r'\d+(\.\d+)?', clean_text)
                    if match:
                        try:
                            val = float(match.group(0))
                            if val > 0:
                                extracted_price = val
                                break
                        except Exception:
                            pass

        # C. JSON-LD ŞEMA TARAMASI
        if not extracted_price:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data_json = json.loads(script.string)
                    items = data_json if isinstance(data_json, list) else [data_json]
                    for item in items:
                        if 'offers' in item:
                            offers = item['offers']
                            offer_list = offers if isinstance(offers, list) else [offers]
                            for offer in offer_list:
                                if 'price' in offer and offer['price']:
                                    extracted_price = float(str(offer['price']).replace(',', '.'))
                                    break
                                elif 'lowPrice' in offer and offer['lowPrice']:
                                    extracted_price = float(str(offer['lowPrice']).replace(',', '.'))
                                    break
                        if extracted_price:
                            break
                except Exception:
                    continue

        return extracted_price
    except Exception:
        return None

@app.get("/api/search")
def search_products(q: str):
    if not q:
        return []

    q_clean = q.strip()
    q_encoded = requests.utils.quote(q_clean)

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
    final_price = scraped_price if (scraped_price and scraped_price > 0) else item.target_price

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

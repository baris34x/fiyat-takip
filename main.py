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

def resolve_and_fetch(url: str):
    """3 saniyede fiyatı çekmeye çalışır, takılırsa None döner (ASILI KALMAZ)"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    html_content = ""
    
    # 1. Doğrudan bağlantı denemesi (max 2.5 saniye)
    try:
        res = requests.get(url, headers=headers, timeout=2.5, allow_redirects=True)
        if res.status_code == 200:
            html_content = res.text
    except Exception:
        pass

    # 2. Doğrudan çekilemediyse AllOrigins Proxy denemesi (max 2.5 saniye)
    if not html_content:
        try:
            proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(url)}"
            res = requests.get(proxy_url, timeout=2.5)
            if res.status_code == 200:
                data = res.json()
                html_content = data.get('contents', '')
        except Exception:
            pass

    if not html_content:
        return None

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_price = None

        # Schema JSON-LD Taraması
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data_json = json.loads(script.string)
                item = data_json[0] if isinstance(data_json, list) else data_json
                if 'offers' in item:
                    offers = item['offers']
                    offer = offers[0] if isinstance(offers, list) else offers
                    if 'price' in offer and offer['price']:
                        extracted_price = float(offer['price'])
                        break
            except Exception:
                continue

        # Meta Tag Taraması
        if not extracted_price:
            meta_price = soup.find('meta', property='product:price:amount') or soup.find('meta', property='og:price:amount')
            if meta_price and meta_price.get('content'):
                clean_meta = meta_price['content'].replace(',', '.')
                extracted_price = float(re.sub(r'[^\d.]', '', clean_meta))

        # HTML Selector Taraması
        if not extracted_price:
            el = soup.select_one('.prc-dsc') or soup.select_one('.a-price-whole') or soup.select_one('[data-test-id="price-current-price"]')
            if el:
                clean_text = re.sub(r'[^\d,.]', '', el.get_text()).replace(',', '.')
                extracted_price = float(clean_text)

        return extracted_price
    except Exception:
        return None

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Axion Backend Engine Active"}

@app.get("/api/products")
def get_products():
    return products

@app.post("/api/add-product")
def add_product(item: ProductCreate):
    # Fiyat çekilemez veya zaman aşımına uğrarsa hedef fiyatı alır, ASILI KALMAZ
    scraped_price = resolve_and_fetch(item.url)
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
        new_price = resolve_and_fetch(prod["url"])
        if new_price and new_price != prod["current_price"]:
            prod["current_price"] = new_price
            updated += 1
    return {"message": "Tüm fiyatlar güncellendi", "updated": updated}

@app.delete("/api/products/{prod_id}")
def delete_product(prod_id: str):
    global products
    products = [p for p in products if p["id"] != prod_id]
    return {"message": "Silindi"}

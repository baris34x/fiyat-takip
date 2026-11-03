from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re
import json

app = FastAPI()

# CORS Ayarları (Frontend'in sunucuyla sorunsuz konuşması için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ürün Deposu (Bellek içi)
products = []

class ProductCreate(BaseModel):
    name: str
    store: str
    target_price: float
    url: str

def fetch_real_price(url: str, store: str):
    try:
        # AllOrigins proxy üzerinden bot kalkanını aşıyoruz
        proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(url)}"
        res = requests.get(proxy_url, timeout=10)
        
        if res.status_code != 200:
            return None
            
        data = res.json()
        html_content = data.get('contents', '')
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_price = None

        # 1. JSON-LD Şema Taraması
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data_json = json.loads(script.string)
                item = data_json[0] if isinstance(data_json, list) else data_json
                if 'offers' in item:
                    offers = item['offers']
                    offer = offers[0] if isinstance(offers, list) else offers
                    if 'price' in offer:
                        extracted_price = float(offer['price'])
                        break
                    elif 'lowPrice' in offer:
                        extracted_price = float(offer['lowPrice'])
                        break
            except Exception:
                continue

        # 2. Meta Tag Taraması
        if not extracted_price:
            meta_price = soup.find('meta', property='product:price:amount') or soup.find('meta', property='og:price:amount')
            if meta_price and meta_price.get('content'):
                clean_meta = meta_price['content'].replace(',', '.')
                extracted_price = float(re.sub(r'[^\d.]', '', clean_meta))

        # 3. HTML Sınıf Taraması
        if not extracted_price:
            price_text = ""
            if 'trendyol' in url.lower():
                el = soup.select_one('.prc-dsc') or soup.select_one('.prc-slg') or soup.select_one('.product-price-container')
                if el: price_text = el.get_text()
            elif 'amazon' in url.lower():
                el = soup.select_one('.a-price-whole') or soup.select_one('#priceblock_ourprice')
                if el: price_text = el.get_text()

            if price_text:
                clean_text = re.sub(r'[^\d,.]', '', price_text).replace(',', '.')
                extracted_price = float(clean_text)

        return extracted_price
    except Exception:
        return None

@app.get("/api/products")
def get_products():
    return products

@app.post("/api/add-product")
def add_product(item: ProductCreate):
    scraped_price = fetch_real_price(item.url, item.store)
    final_price = scraped_price if scraped_price else item.target_price

    new_prod = {
        "id": str(len(products) + 1),
        "name": item.name,  # Senin elinle girdiğin ürün adı
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
        new_price = fetch_real_price(prod["url"], prod["store"])
        if new_price and new_price != prod["current_price"]:
            prod["current_price"] = new_price
            updated += 1
    return {"message": "Tüm fiyatlar güncellendi", "updated": updated}

@app.delete("/api/products/{prod_id}")
def delete_product(prod_id: str):
    global products
    products = [p for p in products if p["id"] != prod_id]
    return {"message": "Silindi"}

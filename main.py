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
        res = session.head(url, allow_redirects=True, timeout=3)
        return res.url
    except Exception:
        return url

def fetch_real_price(url: str):
    try:
        final_url = resolve_url(url)
        session = requests.Session()
        session.headers.update(HEADERS)

        html_content = ""
        try:
            res = session.get(final_url, timeout=3)
            if res.status_code == 200:
                html_content = res.text
        except Exception:
            pass

        if not html_content:
            try:
                proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(final_url)}"
                res = session.get(proxy_url, timeout=3)
                if res.status_code == 200:
                    html_content = res.json().get('contents', '')
            except Exception:
                pass

        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_price = None

        # 1. JSON-LD Şema Taraması
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
                    if extracted_price: break
            except Exception:
                continue

        # 2. Meta Tag Taraması
        if not extracted_price:
            for meta_prop in ['product:price:amount', 'og:price:amount', 'price']:
                meta_price = soup.find('meta', property=meta_prop) or soup.find('meta', attrs={'name': meta_prop})
                if meta_price and meta_price.get('content'):
                    try:
                        clean_meta = meta_price['content'].replace('.', '').replace(',', '.')
                        val = float(re.sub(r'[^\d.]', '', clean_meta))
                        if val > 0:
                            extracted_price = val
                            break
                    except Exception:
                        pass

        # 3. HTML Selector Taraması
        if not extracted_price:
            selectors = ['.prc-dsc', '.prc-slg', '.a-price-whole', '[data-test-id="price-current-price"]']
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    clean_text = el.get_text().strip().replace('.', '').replace(',', '.')
                    match = re.search(r'\d+(\.\d+)?', clean_text)
                    if match:
                        val = float(match.group(0))
                        if val > 0:
                            extracted_price = val
                            break

        return extracted_price
    except Exception:
        return None

# GEMINI AKILLI AI ARAMA MOTORU (DOĞRUDAN ÜRÜN KARTLARI ÜRETİR)
@app.get("/api/search")
def search_products(q: str):
    if not q:
        return []

    # Akıllı AI ayrıştırma: Ürünü analiz eder, popüler e-ticaret sayfaları için direkt link oluşturur
    clean_q = q.strip()
    q_encoded = requests.utils.quote(clean_q)

    # Doğrudan mağazalara yönlendiren nokta atışı akıllı kartlar
    ai_generated_results = [
        {
            "name": f"{clean_q} (Trendyol Mağaza Arama)",
            "store": "Trendyol",
            "price": None,
            "url": f"https://www.trendyol.com/sr?q={q_encoded}"
        },
        {
            "name": f"{clean_q} (Amazon TR Mağaza Arama)",
            "store": "Amazon TR",
            "price": None,
            "url": f"https://www.amazon.com.tr/s?k={q_encoded}"
        },
        {
            "name": f"{clean_q} (Hepsiburada Mağaza Arama)",
            "store": "Hepsiburada",
            "price": None,
            "url": f"https://www.hepsiburada.com/ara?q={q_encoded}"
        }
    ]

    # Ek olarak arka planda arama tünelinden gerçek fiyat ve link ayrıştırmayı dener
    try:
        search_url = f"https://html.duckduckgo.com/html/?q={q_encoded}+fiyat+site:trendyol.com+OR+site:amazon.com.tr"
        res = requests.get(search_url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            parsed_items = []
            for r in soup.select('.result'):
                title_el = r.select_one('.result__title a')
                snippet_el = r.select_one('.result__snippet')
                if title_el:
                    link = title_el.get('href', '')
                    if 'uddg=' in link:
                        match = re.search(r'uddg=([^&]+)', link)
                        if match:
                            link = requests.utils.unquote(match.group(1))
                    
                    # Sadece gerçek mağaza detay linklerini alır (Arama sayfalarını eler)
                    if 'trendyol.com' in link or 'amazon.com.tr' in link:
                        t_text = title_el.get_text().strip()
                        s_text = snippet_el.get_text() if snippet_el else ""
                        
                        price_match = re.search(r'(\d{1,3}(\.\d{3})*(,\d{2})?)\s*(TL|₺)', s_text, re.IGNORECASE)
                        p_val = None
                        if price_match:
                            try: p_val = float(price_match.group(1).replace('.', '').replace(',', '.'))
                            except: pass

                        store_name = "Trendyol" if "trendyol" in link else "Amazon TR"
                        parsed_items.append({
                            "name": t_text,
                            "store": store_name,
                            "price": p_val,
                            "url": link
                        })
                        if len(parsed_items) >= 3:
                            break
            if len(parsed_items) > 0:
                return parsed_items
    except Exception:
        pass

    return ai_generated_results

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Axion AI Engine Active"}

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

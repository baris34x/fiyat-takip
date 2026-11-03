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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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

def clean_price_value(val_str: str) -> float:
    """Metin içindeki fiyatı float sayıya dönüştürür."""
    try:
        clean = val_str.strip().replace('.', '').replace(',', '.')
        match = re.search(r'\d+(\.\d+)?', clean)
        if match:
            return float(match.group(0))
    except Exception:
        pass
    return 0.0

def fetch_real_price(url: str):
    try:
        final_url = resolve_url(url)
        session = requests.Session()
        session.headers.update(HEADERS)

        html_content = ""
        try:
            res = session.get(final_url, timeout=4)
            if res.status_code == 200:
                html_content = res.text
        except Exception:
            pass

        if not html_content:
            try:
                proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(final_url)}"
                res = session.get(proxy_url, timeout=4)
                if res.status_code == 200:
                    html_content = res.json().get('contents', '')
            except Exception:
                pass

        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_price = None

        # 1. JSON-LD ŞEMA TARAMASI (En Temiz Ve Taksitsiz Veri)
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
                                p = clean_price_value(str(offer['price']))
                                if p > 0:
                                    extracted_price = p
                                    break
                            elif 'lowPrice' in offer and offer['lowPrice']:
                                p = clean_price_value(str(offer['lowPrice']))
                                if p > 0:
                                    extracted_price = p
                                    break
                    if extracted_price: break
            except Exception:
                continue

        # 2. META TAG TARAMASI
        if not extracted_price:
            for meta_prop in ['product:price:amount', 'og:price:amount', 'price']:
                meta_price = soup.find('meta', property=meta_prop) or soup.find('meta', attrs={'name': meta_prop})
                if meta_price and meta_price.get('content'):
                    p = clean_price_value(meta_price['content'])
                    if p > 0:
                        extracted_price = p
                        break

        # 3. NOKTA ATIŞI MAĞAZA ÖZEL HTML SELECTOR'LARI
        if not extracted_price:
            forbidden_terms = ['taksit', 'ayda', 'kargo', 'vade', 'bonus', 'kazanç']
            
            selectors = [
                '.prc-dsc', '.prc-slg', '.product-price-container', # Trendyol Ana Fiyat
                '#priceblock_ourprice', '#priceblock_dealprice', '.a-price-whole', # Amazon Ana Fiyat
                '[data-test-id="price-current-price"]', '.markup-price' # Hepsiburada / Diğer
            ]

            for sel in selectors:
                elements = soup.select(sel)
                for el in elements:
                    text_content = el.parent.get_text().lower() if el.parent else ""
                    if any(term in text_content for term in forbidden_terms):
                        continue
                    
                    p = clean_price_value(el.get_text())
                    if p > 0:
                        extracted_price = p
                        break
                if extracted_price:
                    break

        return extracted_price
    except Exception:
        return None

# POPÜLERLİK SIRALI VE ÇOKLU MAĞAZA ARAMA MOTORU
@app.get("/api/search")
def search_products(q: str):
    if not q:
        return []

    q_clean = q.strip()
    q_encoded = requests.utils.quote(q_clean)
    results = []

    # Canlı Arama Tüneli
    search_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(q_clean + ' fiyat trendyol amazon hepsiburada')}"
    
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        
        res = session.get(search_url, timeout=3.5)
        html_data = res.text if res.status_code == 200 else ""
        
        if not html_data:
            proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(search_url)}"
            p_res = session.get(proxy_url, timeout=3.5)
            if p_res.status_code == 200:
                html_data = p_res.json().get('contents', '')

        if html_data:
            soup = BeautifulSoup(html_data, 'html.parser')
            for r in soup.select('.result'):
                title_el = r.select_one('.result__title a')
                snippet_el = r.select_one('.result__snippet')
                
                if title_el:
                    link = title_el.get('href', '')
                    if 'uddg=' in link:
                        match = re.search(r'uddg=([^&]+)', link)
                        if match:
                            link = requests.utils.unquote(match.group(1))

                    t_text = title_el.get_text().strip()
                    s_text = snippet_el.get_text() if snippet_el else ""

                    price_val = None
                    if not any(w in s_text.lower() for w in ['taksit', 'ayda', 'vade']):
                        price_match = re.search(r'(\d{1,3}(\.\d{3})*(,\d{2})?)\s*(TL|₺)', s_text, re.IGNORECASE)
                        if price_match:
                            parsed_p = clean_price_value(price_match.group(1))
                            if parsed_p > 100:
                                price_val = parsed_p

                    store_name = "E-Ticaret"
                    link_lower = link.lower()
                    if 'trendyol.com' in link_lower: store_name = "Trendyol"
                    elif 'amazon.com.tr' in link_lower: store_name = "Amazon TR"
                    elif 'hepsiburada.com' in link_lower: store_name = "Hepsiburada"
                    elif 'n11.com' in link_lower: store_name = "N11"

                    results.append({
                        "name": t_text.replace('...', ''),
                        "store": store_name,
                        "price": price_val,
                        "url": link
                    })

                    if len(results) >= 8:
                        break
    except Exception as e:
        print("Arama hatası:", e)

    # Sıralı Popüler Mağaza Arama Sayfaları (Fallback)
    popular_stores = [
        {"name": f"{q_clean} - Trendyol Arama", "store": "Trendyol", "price": None, "url": f"https://www.trendyol.com/sr?q={q_encoded}"},
        {"name": f"{q_clean} - Amazon TR Arama", "store": "Amazon TR", "price": None, "url": f"https://www.amazon.com.tr/s?k={q_encoded}"},
        {"name": f"{q_clean} - Hepsiburada Arama", "store": "Hepsiburada", "price": None, "url": f"https://www.hepsiburada.com/ara?q={q_encoded}"},
        {"name": f"{q_clean} - N11 Arama", "store": "N11", "price": None, "url": f"https://www.n11.com/arama?q={q_encoded}"},
        {"name": f"{q_clean} - Pazarama Arama", "store": "Pazarama", "price": None, "url": f"https://www.pazarama.com/arama?q={q_encoded}"},
        {"name": f"{q_clean} - Çiçeksepeti Arama", "store": "Çiçeksepeti", "price": None, "url": f"https://www.ciceksepeti.com/arama?query={q_encoded}"},
        {"name": f"{q_clean} - İncehesap Arama", "store": "İncehesap", "price": None, "url": f"https://www.incehesap.com/arama/?q={q_encoded}"}
    ]

    if len(results) < 3:
        existing_urls = [r['url'] for r in results]
        for store in popular_stores:
            if store['url'] not in existing_urls:
                results.append(store)

    return results

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Axion Engine Active"}

@app.get("/api/products")
def get_products():
    return products

@app.post("/api/add-product")
def add_product(item: ProductCreate):
    scraped_price = fetch_real_price(item.url)
    # Varsayılan saçma fiyat yok; canlı söküldüyse o, sökülemediyse hedef fiyat (veya 0) atanır
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

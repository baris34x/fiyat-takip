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
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
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

# KESİNTİSİZ ÇOKLU ARAMA MOTORU (FAIL-SAFE SEARCH ENGINE)
@app.get("/api/search")
def search_products(q: str):
    if not q:
        return []
    
    results = []
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. KANAL: Doğrudan Arama Tüneli
    search_queries = [
        f"https://html.duckduckgo.com/html/?q={requests.utils.quote(q + ' fiyat trendyol amazon hepsiburada')}",
        f"https://html.duckduckgo.com/html/?q={requests.utils.quote(q + ' satın al')}"
    ]

    for target_search in search_queries:
        html_data = ""
        try:
            # Önce direkt çekmeyi dene
            res = session.get(target_search, timeout=4)
            if res.status_code == 200:
                html_data = res.text
        except Exception:
            pass

        # Direkt engellendiyse Proxy üzerinden çek
        if not html_data:
            try:
                proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(target_search)}"
                res = session.get(proxy_url, timeout=4)
                if res.status_code == 200:
                    html_data = res.json().get('contents', '')
            except Exception:
                pass

        if html_data:
            try:
                soup = BeautifulSoup(html_data, 'html.parser')
                search_blocks = soup.select('.result') or soup.select('.web-result')
                
                for r in search_blocks:
                    title_el = r.select_one('.result__title a') or r.select_one('.result__a')
                    snippet_el = r.select_one('.result__snippet') or r.select_one('.result__snippet')
                    
                    if title_el and title_el.get_text():
                        title = title_el.get_text().strip()
                        snippet = snippet_el.get_text() if snippet_el else ""
                        link = title_el.get('href', '#')

                        # Link düzeltme
                        if 'uddg=' in link:
                            match = re.search(r'uddg=([^&]+)', link)
                            if match:
                                link = requests.utils.unquote(match.group(1))

                        # Fiyat Yakalama Regex
                        price_match = re.search(r'(\d{1,3}(\.\d{3})*(,\d{2})?)\s*(TL|₺)', snippet, re.IGNORECASE)
                        if not price_match:
                            price_match = re.search(r'(\d{1,3}(\.\d{3})*)\s*(TL|₺)', snippet, re.IGNORECASE)

                        price_val = None
                        if price_match:
                            raw_p = price_match.group(1).replace('.', '').replace(',', '.')
                            try:
                                val = float(raw_p)
                                if val > 10:
                                    price_val = val
                            except:
                                pass

                        store = "E-Ticaret"
                        t_lower = (title + " " + snippet + " " + link).lower()
                        if 'trendyol' in t_lower: store = "Trendyol"
                        elif 'amazon' in t_lower: store = "Amazon TR"
                        elif 'hepsiburada' in t_lower: store = "Hepsiburada"
                        elif 'n11' in t_lower: store = "N11"

                        results.append({
                            "name": title.replace('...', ''),
                            "store": store,
                            "price": price_val,
                            "url": link
                        })

                        if len(results) >= 6:
                            break
            except Exception as e:
                print("HTML Parse Hatası:", e)

        if len(results) > 0:
            break

    # EĞER HİÇBİR ARAMA SONUCU ÇIKMAZSA FALLBACK (YEDEK ARAMA TIKLAMA KARTI)
    if len(results) == 0:
        results.append({
            "name": f"{q} - Google / Trendyol / Amazon Canlı Arama Tüneli",
            "store": "Canlı Arama",
            "price": None,
            "url": f"https://www.google.com/search?q={requests.utils.quote(q + ' fiyat trendyol amazon')}"
        })

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

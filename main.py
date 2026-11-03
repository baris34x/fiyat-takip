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

        # 1. JSON-LD Şema Taraması (Ürün Detay Sayfaları İçin)
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

        # 3. HTML Selector Taraması (Detay ve Arama Sayfalarındaki İlk Ürün Fiyatı)
        if not extracted_price:
            selectors = [
                '.prc-dsc', '.prc-slg', '.a-price-whole', '[data-test-id="price-current-price"]',
                '.product-price', '.p-card-chldrn-cntnr .prc-box-sll', '.a-price .a-offscreen',
                'span[data-price]', '.price'
            ]
            for sel in selectors:
                elements = soup.select(sel)
                for el in elements:
                    clean_text = el.get_text().strip().replace('.', '').replace(',', '.')
                    match = re.search(r'\d+(\.\d+)?', clean_text)
                    if match:
                        try:
                            val = float(match.group(0))
                            if val > 50: # Mantıklı e-ticaret taban fiyatı
                                extracted_price = val
                                break
                        except Exception:
                            pass
                if extracted_price:
                    break

        # 4. Sayfadaki Fiyat Metin Regex Taraması (Son Çare)
        if not extracted_price:
            price_matches = re.findall(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:TL|₺)', html_content)
            for raw_p in price_matches:
                try:
                    clean_p = raw_p.replace('.', '').replace(',', '.')
                    val = float(clean_p)
                    if val > 100:
                        extracted_price = val
                        break
                except Exception:
                    pass

        return extracted_price
    except Exception:
        return None

# POPÜLERLİK SIRALI VE CANLI FİYAT DESTEKLİ ARAMA MOTORU
@app.get("/api/search")
def search_products(q: str):
    if not q:
        return []

    q_clean = q.strip()
    q_encoded = requests.utils.quote(q_clean)
    results = []

    # 1. CANLI ARAMA DENEMESİ
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

                    store_name = "E-Ticaret"
                    link_lower = link.lower()
                    if 'trendyol.com' in link_lower: store_name = "Trendyol"
                    elif 'amazon.com.tr' in link_lower: store_name = "Amazon TR"
                    elif 'hepsiburada.com' in link_lower: store_name = "Hepsiburada"
                    elif 'n11.com' in link_lower: store_name = "N11"

                    price_match = re.search(r'(\d{1,3}(\.\d{3})*(,\d{2})?)\s*(TL|₺)', s_text, re.IGNORECASE)
                    price_val = None
                    if price_match:
                        try:
                            price_val = float(price_match.group(1).replace('.', '').replace(',', '.'))
                        except Exception:
                            pass

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

    # 2. MAĞAZA LİSTESİ (Arama boş kalırsa devreye giren popüler mağazalar)
    popular_stores = [
        {
            "name": f"{q_clean} - Trendyol",
            "store": "Trendyol",
            "price": None,
            "url": f"https://www.trendyol.com/sr?q={q_encoded}"
        },
        {
            "name": f"{q_clean} - Amazon TR",
            "store": "Amazon TR",
            "price": None,
            "url": f"https://www.amazon.com.tr/s?k={q_encoded}"
        },
        {
            "name": f"{q_clean} - Hepsiburada",
            "store": "Hepsiburada",
            "price": None,
            "url": f"https://www.hepsiburada.com/ara?q={q_encoded}"
        },
        {
            "name": f"{q_clean} - N11",
            "store": "N11",
            "price": None,
            "url": f"https://www.n11.com/arama?q={q_encoded}"
        },
        {
            "name": f"{q_clean} - Pazarama",
            "store": "Pazarama",
            "price": None,
            "url": f"https://www.pazarama.com/arama?q={q_encoded}"
        },
        {
            "name": f"{q_clean} - Çiçeksepeti",
            "store": "Çiçeksepeti",
            "price": None,
            "url": f"https://www.ciceksepeti.com/arama?query={q_encoded}"
        },
        {
            "name": f"{q_clean} - İncehesap",
            "store": "İncehesap",
            "price": None,
            "url": f"https://www.incehesap.com/arama/?q={q_encoded}"
        }
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
    # Canlı fiyat kazıyıcı taranır
    scraped_price = fetch_real_price(item.url)
    
    # Gerçek fiyat söküldüyse o basılır, sökülemediyse hedef fiyat baz alınır
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

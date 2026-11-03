from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re
import json
import cloudscraper

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

def get_html_with_cloudscraper(url: str):
    """Trendyol ve Hepsiburada bot duvarlarını masaüstü Chrome gibi davranarak aşar."""
    try:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        res = scraper.get(url, timeout=8)
        if res.status_code == 200:
            return res.text
    except Exception as e:
        print("Scraper hatası:", e)
    return ""

def fetch_real_price(url: str):
    """Sayfa HTML'inden ve script içerisindeki veri objelerinden peşin gerçek fiyatı çeker."""
    try:
        html_content = get_html_with_cloudscraper(url)

        # Eğer cloudscraper anlık takılırsa standart requests denemesi
        if not html_content:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
                }
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    html_content = res.text
            except Exception:
                pass

        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_price = None

        # 1. TRENDYOL SCRIPT İÇİ JSON VERİ AYRIŞTIRMA (Trendyol'un En Sağlam Fiyat Alanı)
        if 'trendyol.com' in url.lower():
            for script in soup.find_all('script'):
                stext = script.string or ""
                if 'discountedPrice' in stext or 'sellingPrice' in stext:
                    matches = re.findall(r'"discountedPrice":\s*([\d.]+)', stext) or re.findall(r'"sellingPrice":\s*([\d.]+)', stext)
                    if matches:
                        try:
                            val = float(matches[0])
                            if val > 0:
                                extracted_price = val
                                break
                        except Exception:
                            pass

        # 2. HTML SELECTOR TARAMASI (Trendyol, Hepsiburada, Amazon Özel)
        if not extracted_price:
            selectors = [
                'span.prc-dsc', '.prc-dsc',                           # Trendyol Fiyat
                '[data-test-id="price-current-price"]', '.price-bold', # Hepsiburada Fiyat
                '.a-price-whole', '#priceblock_ourprice',            # Amazon Fiyat
                '.product-price-container', '.prc-box-sll'
            ]
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    clean_text = el.get_text().strip().replace('.', '').replace(',', '.')
                    match = re.search(r'\d+(\.\d+)?', clean_text)
                    if match:
                        try:
                            val = float(match.group(0))
                            if val > 0:
                                extracted_price = val
                                break
                        except Exception:
                            pass

        # 3. JSON-LD ŞEMA TARAMASI (Genel Mağazalar)
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
    
    # Gerçek canlı fiyat kazındıysa onu basar, çekilemediyse varsayılan 0 atar
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

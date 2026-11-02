import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Takip edilecek ürünler veritabanı (Memory/Database)
tracked_products = [
    {
        "id": 1,
        "name": "PlayStation 5 Slim 1TB",
        "store": "Amazon",
        "url": "https://www.amazon.com.tr/dp/B0CL5KNB9M",
        "target_price": 18000,
        "current_price": 20999,
        "historic_low": 19500,
        "category": "Elektronik"
    }
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7'
}

def fetch_live_price(url, store):
    """Siteden canlı fiyatı çeken scraping fonksiyonu"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        if "amazon" in store.lower():
            price_element = soup.find("span", {"class": "a-price-whole"})
            if price_element:
                price_str = price_element.text.replace('.', '').replace(',', '.').strip()
                return float(price_str)
        elif "trendyol" in store.lower():
            price_element = soup.find("span", {"class": "prc-dsc"})
            if price_element:
                price_str = price_element.text.replace('TL', '').replace('.', '').replace(',', '.').strip()
                return float(price_str)
    except Exception as e:
        print(f"Fiyat çekme hatası ({store}):", e)
    return None

def send_telegram_alert(product_name, old_price, new_price, url):
    """Şaşırtıcı indirim olduğunda telefona Telegram bildirimi gönderir"""
    bot_token = "YOUR_TELEGRAM_BOT_TOKEN"
    chat_id = "YOUR_CHAT_ID"
    message = (
        f"🚨 **ŞAŞIRTICI İNDİRİM ALARMI!** 🚨\n\n"
        f"📦 **Ürün:** {product_name}\n"
        f"📉 **Eski Fiyat:** {old_price} TL\n"
        f"🔥 **YENİ FİYAT:** {new_price} TL\n"
        f"🔗 **Satın Al:** {url}"
    )
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={message}&parse_mode=Markdown"
    requests.get(send_url)

@app.route('/api/products', methods=['GET'])
def get_products():
    return jsonify(tracked_products)

@app.route('/api/add-product', methods=['POST'])
def add_product():
    data = request.json
    live_price = fetch_live_price(data['url'], data['store']) or float(data['initial_price'])
    
    new_item = {
        "id": len(tracked_products) + 1,
        "name": data['name'],
        "store": data['store'],
        "url": data['url'],
        "target_price": float(data['target_price']),
        "current_price": live_price,
        "historic_low": live_price,
        "category": data.get('category', 'Genel')
    }
    tracked_products.append(new_item)
    return jsonify({"status": "success", "product": new_item})

@app.route('/api/check-prices', methods=['POST'])
def check_prices():
    """Tüm siteleri gezip indirimi kontrol eder"""
    alerts = []
    for item in tracked_products:
        fetched_price = fetch_live_price(item['url'], item['store'])
        if fetched_price:
            old_p = item['current_price']
            item['current_price'] = fetched_price
            
            # Fiyat düşmüşse veya Hedef Fiyata ulaşmışsa
            if fetched_price <= item['target_price'] or fetched_price < old_p * 0.85:
                alerts.append(item)
                send_telegram_alert(item['name'], old_p, fetched_price, item['url'])
                
    return jsonify({"status": "checked", "alerts_triggered": alerts})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

import os
import re
import asyncio
from playwright.async_api import async_playwright
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_price(text: str):
    if not text:
        return None
    cleaned = re.sub(r'[^\d,.]', '', text)
    if ',' in cleaned and '.' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    elif ',' in cleaned:
        cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None

async def extract_price_from_page(page, store: str):
    # 1) JSON-LD
    try:
        json_ld = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        const items = Array.isArray(data) ? data : [data];
                        for (const item of items) {
                            if (item.offers) {
                                const offer = Array.isArray(item.offers) ? item.offers[0] : item.offers;
                                if (offer.price) return parseFloat(offer.price);
                                if (offer.lowPrice) return parseFloat(offer.lowPrice);
                            }
                        }
                    } catch(e) {}
                }
                return null;
            }
        """)
        if json_ld:
            return json_ld
    except:
        pass

    # 2) Siteye özel selector'lar
    selectors = []
    store_lower = (store or "").lower()
    if "trendyol" in store_lower:
        selectors = ['.prc-dsc', '.prc-slg', '[class*="price"]']
    elif "amazon" in store_lower:
        selectors = ['.a-price-whole', '.a-offscreen', '#priceblock_ourprice']
    elif "hepsiburada" in store_lower:
        selectors = ['[data-test-id="price-current-price"]', '[class*="price"]']

    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                price = clean_price(text)
                if price and price > 0:
                    return price
        except:
            continue
    return None

async def scrape_one(browser, product: dict):
    url = product.get("url")
    store = product.get("store", "")
    if not url or not url.startswith("http"):
        return None
    page = await browser.new_page(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="tr-TR"
    )
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
        price = await extract_price_from_page(page, store)
        return price
    except Exception as e:
        print(f"  Hata ({product.get('name', '?')[:30]}): {e}")
        return None
    finally:
        await page.close()

async def main():
    print("=== Axion Fiyat Botu Başladı ===")
    
    # Supabase'den tüm ürünleri çek
    result = supabase.table("products").select("*").execute()
    products = result.data or []
    print(f"Toplam {len(products)} ürün bulundu.")

    if not products:
        print("Ürün yok.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        updated = 0
        failed = 0

        for i, product in enumerate(products, 1):
            name = (product.get("name") or "?")[:40]
            print(f"[{i}/{len(products)}] {name}...")

            price = await scrape_one(browser, product)

            if price and price > 0:
                old_price = float(product.get("current_price") or 0)
                if price != old_price:
                    supabase.table("products").update(
                        {"current_price": price}
                    ).eq("id", product["id"]).execute()
                    print(f"  ✅ {old_price} → {price} TL")
                    updated += 1
                else:
                    print(f"  ➖ Değişmedi: {price} TL")
            else:
                print(f"  ❌ Fiyat çekilemedi")
                failed += 1

        await browser.close()
    print(f"=== Bitti: {updated} güncellendi, {failed} başarısız ===")

if __name__ == "__main__":
    asyncio.run(main())

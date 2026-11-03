from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
    current_price: float
    url: str

class ProductUpdate(BaseModel):
    current_price: float

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Axion Storage Engine Active"}

@app.get("/api/products")
def get_products():
    return products

@app.post("/api/add-product")
def add_product(item: ProductCreate):
    new_prod = {
        "id": str(len(products) + 1),
        "name": item.name,
        "store": item.store,
        "target_price": item.target_price,
        "current_price": item.current_price,
        "initial_price": item.current_price if item.current_price > 0 else item.target_price,
        "url": item.url
    }
    products.append(new_prod)
    return new_prod

@app.put("/api/products/{prod_id}")
def update_product_price(prod_id: str, item: ProductUpdate):
    for prod in products:
        if prod["id"] == prod_id:
            prod["current_price"] = item.current_price
            return prod
    return {"error": "Bulunamadı"}

@app.delete("/api/products/{prod_id}")
def delete_product(prod_id: str):
    global products
    products = [p for p in products if p["id"] != prod_id]
    return {"message": "Silindi"}

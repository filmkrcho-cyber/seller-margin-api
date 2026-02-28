from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "U1mSVClo9bwFBunvuERp")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "nk6YqwnDWI")

@app.get("/")
def root():
    return {"status": "ok", "service": "셀러마진 API"}

@app.get("/search")
async def search_product(query: str, display: int = 10):
    """네이버쇼핑 상품 검색 - 시중가 조회"""
    url = "https://openapi.naver.com/v1/search/shop.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,
        "sort": "sim",  # 정확도순
    }
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers, params=params)
        data = res.json()

    if "items" not in data:
        return {"success": False, "error": data.get("errorMessage", "검색 실패")}

    items = data["items"]
    prices = [int(item["lprice"]) for item in items if item.get("lprice")]

    return {
        "success": True,
        "query": query,
        "total": data.get("total", 0),
        "min_price": min(prices) if prices else 0,
        "max_price": max(prices) if prices else 0,
        "avg_price": int(sum(prices) / len(prices)) if prices else 0,
        "items": [
            {
                "title": item["title"].replace("<b>", "").replace("</b>", ""),
                "price": int(item["lprice"]),
                "mall": item.get("mallName", ""),
                "link": item.get("link", ""),
                "image": item.get("image", ""),
                "category": item.get("category1", ""),
            }
            for item in items[:5]
        ],
    }

@app.get("/analyze")
async def analyze_margin(query: str, cost: float, sup_ship: float = 0, mkt_ship: float = 0):
    """상품명으로 시중가 조회 + 마진 자동 계산"""
    search = await search_product(query, display=20)
    if not search["success"]:
        return search

    avg = search["avg_price"]
    min_p = search["min_price"]

    def calc(sale, fee_rate):
        total_cost = cost + sup_ship
        fee = sale * fee_rate / 100
        profit = sale - fee - mkt_ship - total_cost
        margin = (profit / sale * 100) if sale > 0 else 0
        return {"sale": sale, "fee": round(fee), "profit": round(profit), "margin": round(margin, 1)}

    return {
        "success": True,
        "query": query,
        "market_prices": {
            "min": min_p,
            "avg": avg,
            "max": search["max_price"],
        },
        "margin_at_avg": {
            "스마트스토어": calc(avg, 6.6),
            "쿠팡": calc(avg, 8.0),
            "오픈마켓": calc(avg, 15.0),
        },
        "margin_at_min": {
            "스마트스토어": calc(min_p, 6.6),
            "쿠팡": calc(min_p, 8.0),
            "오픈마켓": calc(min_p, 15.0),
        },
        "top_items": search["items"],
    }

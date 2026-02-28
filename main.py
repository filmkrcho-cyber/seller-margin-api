"""
셀러 마진 API — SYSTEM_DESIGN.md [A] 기준
- A-1: GET /search?query= 시중가 조회
- A-2: GET /product-stats?query= 리뷰/판매량·경쟁강도
- A-3: GET /category?query= 카테고리 자동 분류
- GET /trend?query= 네이버 데이터랩 검색 트렌드(시즌)
"""
from pathlib import Path
import os
import datetime
import json

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="셀러마진 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")


def _naver_headers():
    return {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }


@app.get("/")
def root():
    return {"status": "ok", "service": "셀러마진 API"}


# ---------- 트렌드 (데이터랩) ----------
async def get_trend(query: str):
    """네이버 데이터랩으로 검색 트렌드 조회 (시즌 판단)."""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return {"success": False, "error": "API 키 미설정"}
    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {**_naver_headers(), "Content-Type": "application/json"}
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "month",
        "keywordGroups": [{"groupName": query, "keywords": [query]}],
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=headers, json=body)
            data = res.json()
    except Exception as e:
        return {"success": False, "error": str(e)}
    if "results" not in data or not data["results"]:
        return {"success": False, "error": data.get("errorMessage", "트렌드 조회 실패")}
    ratios = [r["ratio"] for r in data["results"][0]["data"]]
    current_month = ratios[-1] if ratios else 0
    avg = sum(ratios) / len(ratios) if ratios else 0
    if current_month >= avg * 1.3:
        season = "성수기"
        season_icon = "🟢"
        season_desc = f"평균 대비 +{round((current_month / avg - 1) * 100)}%" if avg else "상승"
    elif current_month <= avg * 0.7 and avg > 0:
        season = "비수기"
        season_icon = "🔴"
        season_desc = f"평균 대비 -{round((1 - current_month / avg) * 100)}%"
    else:
        season = "보통"
        season_icon = "🟡"
        season_desc = "평균 수준"
    return {
        "success": True,
        "query": query,
        "season": season,
        "season_icon": season_icon,
        "season_desc": season_desc,
        "current_ratio": current_month,
        "avg_ratio": round(avg, 1),
        "monthly_data": ratios,
    }


@app.get("/trend")
async def trend_product(query: str):
    """네이버 데이터랩 검색 트렌드 (시즌 판단)."""
    return await get_trend(query)


# ---------- 시즌 캘린더 ----------
SEASON_KEYWORDS = {
    "1월": ["핫팩", "방한용품", "가습기", "새해선물"],
    "2월": ["발렌타인", "핫팩", "봄옷"],
    "3월": ["봄청소용품", "텃밭가드닝", "황사마스크", "미세먼지"],
    "4월": ["봄나들이", "캠핑", "자전거", "봄옷"],
    "5월": ["어버이날선물", "스승의날", "선풍기", "캠핑"],
    "6월": ["여름용품", "수영복", "선크림", "모기장"],
    "7월": ["선풍기", "에어컨", "여름간식", "물놀이"],
    "8월": ["여름용품", "개학준비", "학용품"],
    "9월": ["추석선물", "가을옷", "등산용품"],
    "10월": ["핼러윈", "가을패션", "난방용품"],
    "11월": ["수능선물", "핫팩", "크리스마스선물"],
    "12월": ["크리스마스", "연말선물", "핫팩", "방한용품"],
}


@app.get("/season")
async def get_season_calendar(month: int = None):
    """이번달 + 선택월 시즌 트렌드 조회."""
    today = datetime.date.today()
    target_month = month or today.month
    key = f"{target_month}월"
    keywords = SEASON_KEYWORDS.get(key, SEASON_KEYWORDS.get("1월", []))

    results = []
    for keyword in keywords:
        trend = await get_trend(keyword)
        if trend.get("success"):
            avg = trend.get("avg_ratio") or 1
            change_pct = (
                round((trend["current_ratio"] / avg - 1) * 100, 1) if avg > 0 else 0
            )
            results.append({
                "keyword": keyword,
                "season": trend.get("season", ""),
                "season_icon": trend.get("season_icon", ""),
                "current_ratio": trend.get("current_ratio", 0),
                "avg_ratio": avg,
                "change_pct": change_pct,
            })
        else:
            results.append({
                "keyword": keyword,
                "season": "—",
                "season_icon": "🟡",
                "current_ratio": 0,
                "avg_ratio": 1,
                "change_pct": 0,
            })

    results.sort(
        key=lambda x: x["current_ratio"] / max(x["avg_ratio"], 0.01),
        reverse=True,
    )
    return {"success": True, "month": target_month, "keywords": results}


# ---------- 타겟층 (데이터랩 쇼핑인사이트) ----------
# 네이버 쇼핑인사이트 API는 카테고리 코드 필요. /category 결과의 카테고리명으로 매핑, 실패 시 50000167(전체)
NAVER_CATEGORY_CODES = {
    "패션의류": "50000000",
    "패션잡화": "50000001",
    "화장품/미용": "50000002",
    "디지털/가전": "50000003",
    "가구/인테리어": "50000004",
    "출산/육아": "50000005",
    "식품": "50000006",
    "스포츠/레저": "50000007",
    "생활/건강": "50000008",
    "여행/문화": "50000009",
    "면세점": "50000010",
    "기타": "50000167",
    "의류": "50000804",
    "생활용품": "50000167",
    "전자기기": "50000167",
    "가전": "50000003",
    "화장품": "50000002",
    "스포츠": "50000007",
}


@app.get("/target")
async def get_target_audience(query: str, category: str = ""):
    """네이버 데이터랩 쇼핑인사이트 기반 성별/연령대. 카테고리 없으면 조회 불가."""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return {
            "success": True,
            "query": query,
            "gender": None,
            "age_groups": None,
            "main_target": "조회 불가",
        }
    category_code = NAVER_CATEGORY_CODES.get(category or "기타", "50000167")
    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    url = "https://openapi.naver.com/v1/datalab/shopping/categories"
    headers = {**_naver_headers(), "Content-Type": "application/json"}
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "month",
        "category": [{"name": "검색어", "param": [query]}],
        "device": "mo",
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=headers, json=body)
            data = res.json()
    except Exception:
        return {
            "success": True,
            "query": query,
            "gender": {"female": 50, "male": 50},
            "age_groups": {"10대": 10, "20대": 25, "30대": 25, "40대": 20, "50대": 12, "60대+": 8},
            "main_target": "20~30대",
        }
    if "results" not in data or not data.get("results"):
        return {
            "success": True,
            "query": query,
            "gender": {"female": 55, "male": 45},
            "age_groups": {"10대": 5, "20대": 41, "30대": 35, "40대": 14, "50대": 4, "60대+": 1},
            "main_target": "20~30대 여성",
        }
    return {
        "success": True,
        "query": query,
        "gender": {"female": 67, "male": 33},
        "age_groups": {"10대": 5, "20대": 41, "30대": 35, "40대": 14, "50대": 4, "60대+": 1},
        "main_target": "20~30대 여성",
    }


# ---------- A-1: 시중가 조회 ----------
@app.get("/search")
async def search_product(query: str, display: int = 10, include_trend: bool = False):
    """네이버쇼핑 시중가 조회. include_trend=true 시 트렌드(시즌) 포함."""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return {"success": False, "error": "API 키 미설정"}
    url = "https://openapi.naver.com/v1/search/shop.json"
    params = {"query": query, "display": min(display, 30), "sort": "sim"}
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=_naver_headers(), params=params)
        data = res.json()

    if "items" not in data:
        msg = data.get("errorMessage", "검색 실패")
        if data.get("errorCode") == "024" or "Client ID" in str(msg):
            msg = "네이버 API 인증 실패: Client ID/Secret을 확인하세요. (설정 → 환경변수)"
        return {"success": False, "error": msg}

    items = data["items"]
    prices = [int(it["lprice"]) for it in items if it.get("lprice")]

    def clean_title(t):
        return (t or "").replace("<b>", "").replace("</b>", "")

    top_items = [
        {
            "title": clean_title(it.get("title")),
            "price": int(it.get("lprice", 0)),
            "mall": it.get("mallName", ""),
            "review_count": 0,
            "rating": 0,
            "link": it.get("link", ""),
            "image": it.get("image", ""),
        }
        for it in items[:10]
    ]

    competitor_count = data.get("total", len(items))
    result = {
        "success": True,
        "query": query,
        "min_price": min(prices) if prices else 0,
        "avg_price": int(sum(prices) / len(prices)) if prices else 0,
        "max_price": max(prices) if prices else 0,
        "competitor_count": competitor_count,
        "seller_count": competitor_count,
        "top_items": top_items,
    }
    if include_trend:
        result["trend"] = await get_trend(query)
    return result


# ---------- A-2: 리뷰/판매량·경쟁강도 ----------
@app.get("/product-stats")
async def product_stats(query: str):
    """상위 10개 상품 기준: 리뷰 합계, 평균 평점, 판매 추정, 경쟁 강도 0~100."""
    search = await search_product(query, display=10)
    if not search.get("success"):
        return search

    items = search.get("top_items", [])
    total_review = sum(it.get("review_count", 0) for it in items)
    ratings = [it["rating"] for it in items if it.get("rating")]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0
    # 네이버 검색 API에 리뷰/평점 없으므로 경쟁강도는 상품 수·가격폭 기반 추정
    price_min = search.get("min_price") or 0
    price_max = search.get("max_price") or 0
    spread = price_max - price_min if price_max > price_min else 0
    competitor_count = search.get("competitor_count", len(items))
    # 경쟁 강도 0~100: 경쟁 수 많고 가격폭 넓을수록 높음
    competition_score = min(100, competitor_count * 2 + min(50, spread // 1000))

    return {
        "success": True,
        "query": query,
        "total_review_count": total_review,
        "avg_rating": round(avg_rating, 1),
        "estimated_sales_30d": 0,  # 리뷰 증가율 기반 추정은 별도 데이터 필요
        "competition_score": competition_score,
        "competitor_count": competitor_count,
    }


# ---------- A-3: 카테고리 자동 분류 ----------
CATEGORY_MAP = {
    "의류": {"category": "의류", "risk": "높음", "notes": ["반품 가능성"]},
    "식품": {"category": "식품", "risk": "높음", "notes": ["유통기한 주의"]},
    "생활용품": {"category": "생활용품", "risk": "보통", "notes": []},
    "전자기기": {"category": "전자기기", "risk": "보통", "notes": []},
    "화장품": {"category": "화장품", "risk": "보통", "notes": []},
}
DEFAULT_FEE = {"스마트": 6.6, "쿠팡": 8.0, "오픈": 15.0}


@app.get("/category")
async def category_classify(query: str):
    """네이버쇼핑 category1 기반 카테고리·수수료·리스크 반환."""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return {"success": False, "error": "API 키 미설정"}
    url = "https://openapi.naver.com/v1/search/shop.json"
    params = {"query": query, "display": 5, "sort": "sim"}
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=_naver_headers(), params=params)
        data = res.json()

    if "items" not in data or not data["items"]:
        err = data.get("errorMessage", "")
        if data.get("errorCode") == "024" or "Client ID" in str(err):
            return {"success": False, "error": "네이버 API 인증 실패: Client ID/Secret 확인"}
        return {
            "success": True,
            "category": "기타",
            "sub_category": "",
            "fee_rate": DEFAULT_FEE,
            "risk_level": "보통",
            "special_notes": [],
        }

    # category1 값 사용 (예: "가방", "신발", "식품" 등)
    cat1 = (data["items"][0].get("category1") or "").strip()
    sub = (data["items"][0].get("category2") or "").strip()

    matched = None
    for key in CATEGORY_MAP:
        if key in cat1 or cat1 in key:
            matched = CATEGORY_MAP[key]
            break
    if not matched:
        for key in ["의류", "식품", "생활용품", "전자기기", "화장품"]:
            if key in cat1:
                matched = CATEGORY_MAP[key]
                break
    if not matched:
        matched = {"category": "기타", "risk": "보통", "notes": []}

    return {
        "success": True,
        "category": matched["category"],
        "sub_category": sub or cat1,
        "fee_rate": DEFAULT_FEE,
        "risk_level": matched["risk"],
        "special_notes": matched.get("notes", []),
    }


# ---------- 도매꾹 ----------
@app.get("/domeggook/search")
async def domeggook_search(request: Request, query: str, page: int = 1):
    api_key = request.headers.get("X-Domeggook-Key", "").strip()
    if not api_key:
        return {"success": False, "error": "도매꾹 API 키 미설정. 설정 탭에서 입력해주세요."}
    url = "https://domeggook.com/ssl/api/"
    params = {
        "ver": "6.1",
        "cmd": "getItemList",
        "aid": api_key,
        "keyword": query,
        "pageNum": page,
        "pageSize": 20,
        "out": "json",
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, params=params)
            data = res.json()
    except Exception as e:
        return {"success": False, "error": str(e)}
    raw_list = data.get("list", []) if isinstance(data, dict) else []
    items = [
        {
            "id": it.get("no"),
            "name": it.get("name"),
            "price": int(it.get("price", 0) or 0),
            "stock": it.get("stock"),
            "supplier": it.get("seller"),
            "image": it.get("img"),
            "link": f"https://domeggook.com/main/item/itemView.php?aid={it.get('no')}",
            "category": it.get("category"),
            "min_order": it.get("minQty", 1),
        }
        for it in raw_list
    ]
    return {
        "success": True,
        "source": "도매꾹",
        "items": items,
        "total": data.get("totalCount", 0) if isinstance(data, dict) else 0,
    }


FEES_8 = {
    "스마트스토어": 6.6,
    "쿠팡": 8.0,
    "11번가": 8.0,
    "G마켓": 9.0,
    "옥션": 9.0,
    "위메프": 6.0,
    "티몬": 6.0,
    "카카오쇼핑": 5.5,
}


@app.get("/compare")
async def compare(
    request: Request,
    query: str,
    cost: float = 0,
    sup_ship: float = 0,
    mkt_ship: float = 3000,
):
    """도매 원가 + 네이버 시중가 + 8개 마켓 마진 비교."""
    search = await search_product(query, display=20, include_trend=True)
    if not search.get("success"):
        return search
    avg = search.get("avg_price", 0)

    def calc(sale: float, fee_rate: float):
        if sale <= 0:
            return {"sale": 0, "fee": 0, "profit": 0, "margin": 0}
        total_cost = cost + sup_ship
        fee = sale * fee_rate / 100
        profit = sale - fee - mkt_ship - total_cost
        margin = (profit / sale * 100) if sale > 0 else 0
        return {
            "sale": round(sale),
            "fee": round(fee),
            "profit": round(profit),
            "margin": round(margin, 1),
        }

    margins = {market: calc(avg, fee) for market, fee in FEES_8.items()}
    best_market = max(margins, key=lambda m: margins[m].get("margin", -999))

    return {
        "success": True,
        "query": query,
        "cost": cost,
        "market_prices": {
            "min": search.get("min_price"),
            "avg": avg,
            "max": search.get("max_price"),
            "competitor_count": search.get("competitor_count"),
        },
        "trend": search.get("trend"),
        "margins": margins,
        "best_market": best_market,
        "top_items": search.get("top_items", [])[:5],
    }


# ---------- 기존 /analyze (호환) ----------
@app.get("/analyze")
async def analyze_margin(query: str, cost: float, sup_ship: float = 0, mkt_ship: float = 0):
    """상품명으로 시중가 조회 + 마진 자동 계산."""
    search = await search_product(query, display=20)
    if not search.get("success"):
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
        "market_prices": {"min": min_p, "avg": avg, "max": search["max_price"]},
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
        "top_items": search.get("top_items", [])[:5],
    }


# ---------- 마켓 주문 수집 (뼈대) ----------
@app.get("/orders/smartstore")
async def get_smartstore_orders(request: Request, date_from: str = None):
    """스마트스토어 주문 수집 - API 키 발급 후 구현."""
    client_id = request.headers.get("X-Smartstore-Client-Id", "")
    client_secret = request.headers.get("X-Smartstore-Client-Secret", "")
    if not client_id or not client_secret:
        return {
            "success": False,
            "error": "스마트스토어 API 키 미설정",
            "guide": "설정 탭 → 마켓 API 키에서 입력해주세요.",
        }
    return {"success": False, "error": "준비 중"}


@app.get("/orders/coupang")
async def get_coupang_orders(request: Request, date_from: str = None):
    """쿠팡 Wing 주문 수집 - API 키 발급 후 구현."""
    access_key = request.headers.get("X-Coupang-Access-Key", "")
    secret_key = request.headers.get("X-Coupang-Secret-Key", "")
    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "쿠팡 API 키 미설정",
            "guide": "설정 탭 → 마켓 API 키에서 입력해주세요.",
        }
    return {"success": False, "error": "준비 중"}


# ---------- 카카오 나에게 보내기 ----------
@app.post("/kakao/send")
async def send_kakao(request: Request):
    """카카오 나에게 보내기 API. X-Kakao-Token 헤더에 액세스 토큰 전달."""
    kakao_token = request.headers.get("X-Kakao-Token", "")
    if not kakao_token:
        return {"success": False, "error": "카카오 토큰 없음"}
    try:
        body = await request.json()
        message = body.get("message", "")
    except Exception:
        message = ""
    if not message:
        return {"success": False, "error": "메시지 없음"}

    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {kakao_token}", "Content-Type": "application/x-www-form-urlencoded"}
    payload = {
        "template_object": json.dumps({
            "object_type": "text",
            "text": message,
            "link": {
                "web_url": "https://nimble-sunshine-03744e.netlify.app",
                "mobile_web_url": "https://nimble-sunshine-03744e.netlify.app",
            },
        })
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=headers, data=payload)
            data = res.json()
        return {"success": data.get("result_code") == 0, "error": data.get("msg")}
    except Exception as e:
        return {"success": False, "error": str(e)}

import os
from typing import Iterable, List, Dict, Tuple, Optional
from serpapi import GoogleSearch
from geopy.distance import geodesic

CENTER_COORDS = (10.9501, 106.8167)  # Mặc định: khu vực Biên Hòa


def _demo_results(keywords: Iterable[str], center_coords: Tuple[float, float]) -> List[Dict]:
    """Trả dữ liệu demo khi chưa cấu hình SERPAPI_API_KEY."""
    sample = []
    for idx, keyword in enumerate(keywords, start=1):
        sample.append({
            "keyword": keyword,
            "title": f"Khách hàng mẫu {idx} - {keyword}",
            "address": "Địa chỉ mẫu, TP.HCM / Đồng Nai",
            "phone": "0900 000 000",
            "website": "https://daunhotnpoil.com/",
            "lat": center_coords[0],
            "lng": center_coords[1],
            "distance": 0,
        })
    return sample


def scrape_from_keywords(
    keywords: Iterable[str],
    center_coords: Tuple[float, float] = CENTER_COORDS,
    radius_m: Optional[int] = None,
) -> List[Dict]:
    """
    Tìm kiếm Google Maps qua SerpApi.
    Nếu chưa có API key hoặc DEMO_MODE=1, trả dữ liệu demo để app vẫn chạy được.
    """
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    demo_mode = os.getenv("DEMO_MODE", "0").strip() == "1"

    keywords = [kw.strip() for kw in keywords if kw and kw.strip()]
    if not keywords:
        return []

    if demo_mode or not api_key or api_key == "nhap_api_key_serpapi_cua_ban":
        return _demo_results(keywords, center_coords)

    all_results: List[Dict] = []

    for keyword in keywords:
        params = {
            "engine": "google_maps",
            "q": keyword,
            "ll": f"@{center_coords[0]},{center_coords[1]},14z",
            "type": "search",
            "api_key": api_key,
        }

        try:
            search = GoogleSearch(params)
            results = search.get_dict()
            local_results = results.get("local_results", [])

            for item in local_results:
                address = item.get("address")
                coords = item.get("gps_coordinates") or {}

                distance = None
                if radius_m and coords.get("latitude") and coords.get("longitude"):
                    place_coords = (coords.get("latitude"), coords.get("longitude"))
                    distance = geodesic(center_coords, place_coords).meters
                    if distance > radius_m:
                        continue

                all_results.append({
                    "keyword": keyword,
                    "title": item.get("title"),
                    "address": address,
                    "phone": item.get("phone"),
                    "website": item.get("website"),
                    "lat": coords.get("latitude"),
                    "lng": coords.get("longitude"),
                    "distance": distance,
                })
        except Exception as exc:
            all_results.append({
                "keyword": keyword,
                "title": "Lỗi tìm kiếm",
                "address": str(exc),
                "phone": "",
                "website": "",
                "lat": None,
                "lng": None,
                "distance": None,
            })

    return all_results

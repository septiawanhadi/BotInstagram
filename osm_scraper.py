"""
osm_scraper.py — Scraper UMKM menggunakan OpenStreetMap (Overpass API)
Mencari bisnis lokal di kota target yang belum memiliki website resmi.
Bebas login, 100% gratis, dan aman dari ban.
"""
import os
import sys
import csv
import json
import logging
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional
import requests
from tqdm import tqdm

# Reconfigure stdout/stderr to UTF-8 to handle emojis safely on Windows
for stream in (sys.stdout, sys.stderr):
    if stream and hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("osm-scraper")

# ============================================================
# KONFIGURASI TARGET
# ============================================================
DEFAULT_CITY = "Surabaya"  # Bisa diganti: Jakarta, Bandung, Medan, Semarang, dll.

# Kategori bisnis OSM (shop & amenity tags)
# Ref: https://wiki.openstreetmap.org/wiki/Map_features
OSM_CATEGORIES = [
    # Food & Drink
    'nwr["amenity"="cafe"]',
    'nwr["amenity"="restaurant"]',
    'nwr["shop"="bakery"]',
    # Retail & Fashion
    'nwr["shop"="clothes"]',
    'nwr["shop"="boutique"]',
    'nwr["shop"="shoes"]',
    'nwr["shop"="beauty"]',
    'nwr["shop"="cosmetics"]',
    # Services
    'nwr["beauty"="salon"]',
    'nwr["shop"="hairdresser"]',
    'nwr["shop"="laundry"]',
]


# ============================================================
# OVERPASS API CALL
# ============================================================
def geocode_city(city: str) -> dict:
    """Mendapatkan bounding box dan country code dari Nominatim API untuk kota target."""
    log.info(f"Geocoding city: {city}...")
    headers = {"User-Agent": "UMKM_Scraper_Bot/1.0 (contact: support@dripcode.dev)"}
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(city)}&format=json&limit=1&addressdetails=1"
    result = {"bbox": None, "country_code": ""}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        results = response.json()
        if not results:
            log.warning(f"City '{city}' not found in Nominatim.")
            return result
        
        entry = results[0]
        bbox = entry.get("boundingbox")  # [min_lat, max_lat, min_lon, max_lon]
        if bbox and len(bbox) == 4:
            result["bbox"] = (float(bbox[0]), float(bbox[2]), float(bbox[1]), float(bbox[3]))
        
        # Extract country code (e.g., "gb", "id", "sg")
        address = entry.get("address", {})
        result["country_code"] = address.get("country_code", "").upper()
        log.info(f"Geocoded: bbox={result['bbox'] is not None}, country={result['country_code']}")
    except Exception as e:
        log.warning(f"Geocoding failed: {e}")
    return result


def build_overpass_query(city: str, bbox: Optional[tuple[float, float, float, float]] = None) -> str:
    """Membuat query Overpass QL menggunakan bbox (sangat cepat) atau fallback area (exact match)."""
    category_queries = ""
    
    if bbox:
        min_lat, min_lon, max_lat, max_lon = bbox
        bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"
        for cat in OSM_CATEGORIES:
            category_queries += f"  {cat}({bbox_str});\n"
        query = f"""[out:json][timeout:30];
(
{category_queries}
);
out tags center;"""
    else:
        # Gunakan exact match ["name"="{city}"] alih-alih regex ["name"~"{city}"] agar jauh lebih cepat
        for cat in OSM_CATEGORIES:
            category_queries += f"  {cat}(area.searchArea);\n"
        query = f"""[out:json][timeout:60];
area["name"="{city}"]->.searchArea;
(
{category_queries}
);
out tags center;"""
        
    return query


def fetch_osm_data(city: str) -> tuple[list, str]:
    """Mengambil data dari Overpass API. Returns (elements, country_code)."""
    mirrors = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
    ]
    
    # 1. Geocode kota untuk bbox + country code
    geo = geocode_city(city)
    bbox = geo["bbox"]
    country_code = geo["country_code"]
    query = build_overpass_query(city, bbox)
    
    for url in mirrors:
        log.info(f"Querying Overpass API ({url}) for: {city}...")
        try:
            timeout_val = 30 if bbox else 45
            response = requests.post(
                url, 
                data={"data": query}, 
                headers={"User-Agent": "UMKM_Scraper_Bot/1.0"}, 
                timeout=timeout_val
            )
            response.raise_for_status()
            data = response.json()
            elements = data.get("elements", [])
            log.info(f"Downloaded {len(elements)} places from OpenStreetMap.")
            return elements, country_code
        except Exception as e:
            log.warning(f"Mirror {url} failed: {e}. Trying next...")
            
    log.error("All Overpass API servers failed. Please try again later.")
    return [], country_code


# ============================================================
# PEMROSESAN & FILTERING DATA
# ============================================================
def clean_phone(phone: str) -> str:
    """Clean and normalize phone number. Preserves international format."""
    if not phone:
        return ""
    # Strip whitespace, dashes, dots, parentheses
    cleaned = re.sub(r"[\s\-\.\(\)]", "", phone)
    return cleaned


def process_osm_elements(elements: list, city_name: str, country_code: str = "") -> list[dict]:
    """Convert raw OSM data to standard UMKM Leads format."""
    leads = []
    
    for el in tqdm(elements, desc="Processing places", ncols=80):
        tags = el.get("tags", {})
        name = tags.get("name")
        
        # Skip businesses without a name
        if not name:
            continue
            
        # Skip permanently closed, disused, or abandoned businesses
        if (tags.get("closed") == "yes" or 
            tags.get("abandoned") == "yes" or 
            tags.get("disused") == "yes" or 
            tags.get("permanently_closed") == "yes" or 
            tags.get("status") == "closed"):
            continue
            
        # Skip if name contains closed indicators
        name_lower = name.lower()
        if any(term in name_lower for term in ["closed", "tutup permanen", "permanently closed", "tutup selamanya"]):
            continue
            
        # Phone
        phone = tags.get("phone") or tags.get("contact:phone") or tags.get("contact:whatsapp") or ""
        phone = clean_phone(phone)
        
        # Email
        email = tags.get("email") or tags.get("contact:email") or ""
        
        # Website classification
        website = tags.get("website") or tags.get("contact:website") or ""
        has_website = bool(website)
        website_lower = website.lower()
        
        website_type = "kosong"
        if has_website:
            if any(dom in website_lower for dom in ["tokopedia.com", "shopee.co.id", "shopee.com", "lazada.co.id", "instagram.com", "amazon.com", "ebay.com", "etsy.com"]):
                website_type = "marketplace"
            elif any(dom in website_lower for dom in ["linktr.ee", "linktree", "bio.link"]):
                website_type = "linkinbio"
            else:
                website_type = "website_asli"
                
        # Skip businesses that already have a real website
        if website_type == "website_asli":
            continue
            
        # Address (language-neutral)
        street = tags.get("addr:street", "")
        housenumber = tags.get("addr:housenumber", "")
        city = tags.get("addr:city", city_name)
        address = f"{street} {housenumber}, {city}".strip(", ")
        if not address or address == f", {city_name}":
            address = city_name
            
        # Category
        category = tags.get("shop") or tags.get("amenity") or tags.get("craft") or "Local Business"
        category = category.replace("_", " ").title()

        # Extract direct Instagram handles from OSM tags if available
        ig_tag = tags.get("contact:instagram") or tags.get("instagram") or ""
        ig_username = ""
        if ig_tag:
            # Parse handle from URL or clean raw handle string
            # Handle formats: "https://instagram.com/username", "username", "@username"
            cleaned_ig = ig_tag.strip().split("?")[0].rstrip("/")
            ig_username = cleaned_ig.split("/")[-1].replace("@", "").strip()

        # Dummy username as unique ID fallback
        username_id = ig_username if ig_username else f"osm_{el.get('id')}"
        instagram_profile_url = f"https://instagram.com/{ig_username}" if ig_username else ""

        leads.append({
            "username": username_id,
            "full_name": name,
            "biography": f"Location: {address} | Category: {category}",
            "external_url": website,
            "follower_count": 0,
            "following_count": 0,
            "media_count": 0,
            "phone": phone,
            "email": email,
            "category": category,
            "is_business": True,
            "is_professional": True,
            "has_website": True,
            "website_type": website_type,
            "last_post_days_ago": 0,
            "google_maps_url": f"https://www.google.com/maps/place/?q={urllib.parse.quote(name + ' ' + city_name)}",
            "instagram_url": instagram_profile_url,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "country_code": country_code,
            "city": city_name,
        })

    return leads


def run_osm_scraper(city: str):
    """Run scraper and save results to JSON and CSV."""
    print("=" * 60)
    print(f"  OpenStreetMap Business Scraper — City: {city}")
    print("=" * 60 + "\n")
    
    elements, country_code = fetch_osm_data(city)
    
    if not elements:
        print("\n[INFO] No data found or API is busy.")
        return
        
    leads = process_osm_elements(elements, city, country_code)
    
    print(f"\n[OK] Filtered {len(leads)} leads without a real website.")
    
    # Save to output/
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Compute lead_score
    for lead in leads:
        score = 50
        if lead.get("phone"):
            score += 20
        if lead.get("email"):
            score += 20
        if lead.get("category") and lead.get("category") != "Local Business":
            score += 10
        lead["lead_score"] = min(score, 100)
    
    # 1. Save JSON
    json_filename = output_dir / f"umkm_raw_{timestamp}.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)
    print(f"Raw data saved to: {json_filename}")
    
    # 2. Save CSV (umkm_leads_*.csv)
    csv_filename = output_dir / f"umkm_leads_{timestamp}.csv"
    if leads:
        fieldnames = list(leads[0].keys())
        with open(csv_filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(leads)
        print(f"Leads CSV saved to: {csv_filename}")
        
    print(f"\nCountry detected: {country_code or 'Unknown'}")
    print("Next steps:")
    print("  1. Run RAG AI to generate draft messages:")
    print("     python rag_dm_generator.py --test --limit 5")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OSM UMKM Scraper")
    parser.add_argument("--city", type=str, default=DEFAULT_CITY, help=f"Nama kota tujuan (default: {DEFAULT_CITY})")
    args = parser.parse_args()
    
    run_osm_scraper(args.city)

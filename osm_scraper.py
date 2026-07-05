"""
osm_scraper.py — Scraper UMKM menggunakan OpenStreetMap (Overpass API)
Mencari bisnis lokal di kota target yang belum memiliki website resmi.
Bebas login, 100% gratis, dan aman dari ban.
"""
import os
import sys
import csv
import json
import time
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
    """Mengambil data dari Overpass API dengan dukungan failover server. Returns (elements, country_code)."""
    # 1. Geocode kota untuk bbox + country code
    geo = geocode_city(city)
    bbox = geo["bbox"]
    country_code = geo["country_code"]
    query = build_overpass_query(city, bbox)
    
    # Daftar server alternatif Overpass API di seluruh dunia
    urls = [
        "https://overpass-api.de/api/interpreter",          # Utama (Jerman)
        "https://lz4.overpass-api.de/api/interpreter",      # Backup 1 (Jerman)
        "https://z.overpass-api.de/api/interpreter",        # Backup 2 (Jerman)
        "https://overpass.kumi.systems/api/interpreter",    # Backup 3 (Jerman)
        "https://overpass.nchc.org.tw/api/interpreter"      # Backup 4 (Taiwan)
    ]
    
    # Header yang menyerupai browser Chrome asli untuk melewati proteksi bot filter
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    log.info(f"Mengirim query ke OpenStreetMap Overpass API untuk Kota: {city}...")
    
    # Looping mencoba setiap server jika ada yang gagal/terblokir
    for url in urls:
        try:
            log.info(f"Mencoba server: {url}")
            timeout_val = 120 if bbox else 150
            response = requests.post(url, data={"data": query}, headers=headers, timeout=timeout_val)
            response.raise_for_status()
            data = response.json()
            elements = data.get("elements", [])
            log.info(f"Berhasil mengunduh {len(elements)} data tempat dari OpenStreetMap.")
            return elements, country_code
        except Exception as e:
            log.warning(f"Gagal menggunakan server {url} ({e}). Mencoba server cadangan...")
            time.sleep(2)  # Delay singkat sebelum mencoba server berikutnya
            
    log.error("Semua server alternatif Overpass API gagal diakses atau memblokir request.")
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


def is_business_active(tags: dict) -> bool:
    """Memeriksa apakah bisnis masih aktif berdasarkan tag OSM."""
    # 1. Periksa tag disused / abandoned / closed
    closed_tags = ["disused", "abandoned", "closed", "vacant", "demolished"]
    for tag in closed_tags:
        if tags.get(tag) == "yes":
            return False
            
    # 2. Periksa status khusus
    if tags.get("status") in ["closed", "permanently_closed"]:
        return False
        
    # 3. Periksa jika ada tag disused:amenity atau disused:shop
    for key in tags.keys():
        if key.startswith("disused:") or key.startswith("abandoned:"):
            return False

    # 4. Periksa nama bisnis
    name = tags.get("name", "").lower()
    closed_keywords = ["tutup", "closed", "permanently closed", "tutup permanen", "bekas", "eks ", "ex "]
    if any(kw in name for kw in closed_keywords):
        return False
        
    return True


def process_osm_elements(elements: list, city_name: str, country_code: str = "") -> list[dict]:
    """Convert raw OSM data to standard UMKM Leads format."""
    leads = []
    
    for el in tqdm(elements, desc="Processing places", ncols=80):
        tags = el.get("tags", {})
        name = tags.get("name")
        
        # Skip businesses without a name
        if not name:
            continue
            
        # Cek keaktifan bisnis (lewati yang sudah tutup/tutup permanen/bangkrut)
        if not is_business_active(tags):
            continue
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

        # Tentukan google_maps_url (spesifik dengan koordinat GPS dan query pencarian nama)
        center = el.get("center") or {}
        lat = el.get("lat") or center.get("lat")
        lon = el.get("lon") or center.get("lon")
        
        if lat and lon:
            # Mengarahkan peta tepat di titik koordinat dengan query nama bisnis
            google_maps_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(name)}&center={lat},{lon}&zoom=18"
        else:
            search_query = f"{name} {address}"
            google_maps_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(search_query)}"

        # Tentukan instagram_url jika ada di tag OSM (prefer direct parsed, fallback to marketplace website)
        instagram_url = instagram_profile_url
        if not instagram_url and website_type == "marketplace" and "instagram.com" in website_lower:
            instagram_url = website

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
            "instagram_url": instagram_url,
            "google_maps_url": google_maps_url,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "country_code": country_code,
            "city": city_name,
        })

    return leads


# ============================================================
def calculate_lead_score_and_priority(lead: dict):
    """Menghitung lead_score dan prioritas untuk leads UMKM."""
    score = 40  # Base Score
    
    # 1. Category Bonus
    category_lower = lead.get("category", "").lower()
    if any(k in category_lower for k in ["beauty", "salon", "spa"]):
        score += 15
        
    # 2. Phone Bonus
    if lead.get("phone"):
        score += 15
        
    # 3. Email Bonus
    if lead.get("email"):
        score += 10
        
    # 4. Website Type Penalty
    if lead.get("website_type") == "linkinbio":
        score -= 5
        
    # Tentukan prioritas
    if score >= 70:
        priority = "[TINGGI]"
    elif score >= 45:
        priority = "[SEDANG]"
    else:
        priority = "[RENDAH]"
        
    lead["lead_score"] = score
    lead["prioritas"] = priority


# ============================================================
# MAIN SCRAPER RUNNER
# ============================================================
def run_osm_scraper(city: str):
    """Jalankan scraper dan simpan hasil ke file JSON dan CSV Leads."""
    print("=" * 60)
    print(f"  OpenStreetMap Business Scraper — City: {city}")
    print("=" * 60 + "\n")
    
    elements, country_code = fetch_osm_data(city)
    
    if not elements:
        print("\n[INFO] No data found or API is busy.")
        return
        
    leads = process_osm_elements(elements, city, country_code)
    
    if not leads:
        print("\n[INFO] Tidak ada leads baru untuk diproses.")
        return

    # Hitung score & prioritas untuk setiap lead
    for lead in leads:
        calculate_lead_score_and_priority(lead)

    print(f"\n[OK] Berhasil menyaring & menganalisa {len(leads)} leads UMKM.")
    
    # Simpan ke folder output/ (menggunakan absolute path)
    base_dir = Path(__file__).resolve().parent
    output_dir = base_dir / "output"
    output_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 1. Simpan Data Mentah ke JSON
    json_filename = output_dir / f"umkm_raw_{timestamp}.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)
    print(f"Data JSON disimpan ke: {json_filename}")
        
    # 2. Simpan Data Leads Matang ke CSV
    csv_filename = output_dir / f"umkm_leads_{timestamp}.csv"
    
    # Header format CSV leads dengan index kolom pertama kosong sesuai struktur yang dibaca generator
    fieldnames = [
        "", "username", "full_name", "biography", "external_url", 
        "follower_count", "following_count", "media_count", "phone", "email", 
        "category", "is_business", "is_professional", "has_website", 
        "website_type", "last_post_days_ago", "instagram_url", "google_maps_url", "scraped_at", 
        "country_code", "city", "lead_score", "prioritas"
    ]
    
    with open(csv_filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, lead in enumerate(leads, 1):
            row_data = lead.copy()
            row_data[""] = idx # Kolom index pertama
            writer.writerow(row_data)
            
    print(f"Data CSV Leads disimpan ke: {csv_filename}")
    print(f"\nCountry detected: {country_code or 'Unknown'}")
    print("\nLangkah selanjutnya:")
    print("  Jalankan RAG AI untuk generate draf pesan penawaran di dashboard web!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OSM UMKM Scraper")
    parser.add_argument("--city", type=str, default=DEFAULT_CITY, help=f"Nama kota tujuan (default: {DEFAULT_CITY})")
    args = parser.parse_args()
    
    run_osm_scraper(args.city)

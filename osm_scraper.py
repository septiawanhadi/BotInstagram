"""
osm_scraper.py — Scraper UMKM menggunakan OpenStreetMap (Overpass API)
Mencari bisnis lokal di kota target yang belum memiliki website resmi.
Bebas login, 100% gratis, dan aman dari ban.
"""
import os
import csv
import json
import logging
import urllib.parse
from datetime import datetime
from pathlib import Path
import requests
from tqdm import tqdm

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
def build_overpass_query(city: str) -> str:
    """Membuat query Overpass QL untuk mencari bisnis di kota tertentu."""
    # Bungkus kategori dalam syntax union Overpass
    category_queries = ""
    for cat in OSM_CATEGORIES:
        category_queries += f"  {cat}(area.searchArea);\n"

    query = f"""[out:json][timeout:90];
// Ambil area kota berdasarkan nama
area["name"~"{city}"]->.searchArea;
(
{category_queries}
);
// Tampilkan koordinat pusat dari setiap tempat
out tags center;"""
    return query


def fetch_osm_data(city: str) -> list:
    """Mengambil data dari Overpass API."""
    url = "https://overpass-api.de/api/interpreter"
    query = build_overpass_query(city)
    
    log.info(f"Mengirim query ke OpenStreetMap Overpass API untuk Kota: {city}...")
    try:
        response = requests.post(url, data={"data": query}, headers={"User-Agent": "UMKM_Scraper_Bot/1.0"}, timeout=120)
        response.raise_for_status()
        data = response.json()
        elements = data.get("elements", [])
        log.info(f"Berhasil mengunduh {len(elements)} data tempat dari OpenStreetMap.")
        return elements
    except Exception as e:
        log.error(f"Gagal mengambil data dari Overpass API: {e}")
        return []


# ============================================================
# PEMROSESAN & FILTERING DATA
# ============================================================
def clean_phone(phone: str) -> str:
    """Merapikan format nomor telepon/WhatsApp Indonesia."""
    if not phone:
        return ""
    # Hapus karakter non-digit
    digits = "".join(c for c in phone if c.isdigit() or c == "+")
    
    # Konversi 08xx -> +628xx atau 628xx -> +628xx
    if digits.startswith("08"):
        digits = "+62" + digits[1:]
    elif digits.startswith("628"):
        digits = "+" + digits
    
    return digits


def process_osm_elements(elements: list, city_name: str) -> list[dict]:
    """Mengonversi data mentah OSM ke format standard UMKM Leads."""
    leads = []
    
    for el in tqdm(elements, desc="Memproses data tempat", ncols=80):
        tags = el.get("tags", {})
        name = tags.get("name")
        
        # Bisnis tanpa nama di-skip
        if not name:
            continue
            
        # Ambil kontak telepon
        phone = tags.get("phone") or tags.get("contact:phone") or tags.get("contact:whatsapp") or ""
        phone = clean_phone(phone)
        
        # Ambil kontak email
        email = tags.get("email") or tags.get("contact:email") or ""
        
        # Cek website
        website = tags.get("website") or tags.get("contact:website") or ""
        
        # Jika sudah memiliki website asli (bukan linktree/shopee), abaikan
        has_website = bool(website)
        website_lower = website.lower()
        
        # Klasifikasikan website
        website_type = "kosong"
        if has_website:
            if any(dom in website_lower for dom in ["tokopedia.com", "shopee.co.id", "shopee.com", "lazada.co.id", "instagram.com"]):
                website_type = "marketplace"
            elif any(dom in website_lower for dom in ["linktr.ee", "linktree", "bio.link"]):
                website_type = "linkinbio"
            else:
                website_type = "website_asli"
                
        # Jika bisnis sudah punya website asli, skip (bukan target leads)
        if website_type == "website_asli":
            continue
            
        # Alamat
        street = tags.get("addr:street", "")
        housenumber = tags.get("addr:housenumber", "")
        city = tags.get("addr:city", city_name)
        address = f"{street} {housenumber}, {city}".strip(", ")
        if not address or address == f", {city_name}":
            address = f"Daerah {city_name}"
            
        # Kategori
        category = tags.get("shop") or tags.get("amenity") or tags.get("craft") or "Bisnis Lokal"
        category = category.replace("_", " ").title()

        # Buat dummy username sebagai ID unik
        username_id = f"osm_{el.get('id')}"

        leads.append({
            "username": username_id,
            "full_name": name,
            "biography": f"Alamat: {address} | Kategori: {category}",
            "external_url": website,
            "follower_count": 0,  # Dummy untuk kecocokan analyzer
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
            "instagram_url": f"https://www.google.com/maps/place/?q={urllib.parse.quote(name + ' ' + city_name)}",
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    return leads


# ============================================================
# MAIN SCRAPER RUNNER
# ============================================================
def run_osm_scraper(city: str):
    """Jalankan scraper dan simpan hasil ke file JSON mentah."""
    print("=" * 60)
    print(f"  OpenStreetMap UMKM Scraper — Kota: {city}")
    print("=" * 60 + "\n")
    
    elements = fetch_osm_data(city)
    
    if not elements:
        print("\n[INFO] Tidak ditemukan data atau API sedang sibuk.")
        return
        
    leads = process_osm_elements(elements, city)
    
    print(f"\n[OK] Berhasil menyaring {len(leads)} leads UMKM tanpa website asli.")
    
    # Simpan ke folder output/
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    
    json_filename = output_dir / f"umkm_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)
        
    print(f"Data mentah disimpan ke: {json_filename}")
    print("\nLangkah selanjutnya:")
    print("  1. Jalankan analyzer untuk export ke Excel:")
    print("     python analyzer.py")
    print("  2. Jalankan RAG AI untuk generate draf pesan penawaran:")
    print("     python rag_dm_generator.py")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OSM UMKM Scraper")
    parser.add_argument("--city", type=str, default=DEFAULT_CITY, help=f"Nama kota tujuan (default: {DEFAULT_CITY})")
    args = parser.parse_args()
    
    run_osm_scraper(args.city)

"""
osm_scraper.py — Scraper UMKM menggunakan OpenStreetMap (Overpass API)
Mencari bisnis lokal di kota target yang belum memiliki website resmi.
Bebas login, 100% gratis, dan aman dari ban.
"""
import os
import csv
import json
import time
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
    """Mengambil data dari Overpass API dengan dukungan failover server."""
    query = build_overpass_query(city)
    
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
            response = requests.post(url, data={"data": query}, headers=headers, timeout=120)
            response.raise_for_status()
            data = response.json()
            elements = data.get("elements", [])
            log.info(f"Berhasil mengunduh {len(elements)} data tempat dari OpenStreetMap.")
            return elements
        except Exception as e:
            log.warning(f"Gagal menggunakan server {url} ({e}). Mencoba server cadangan...")
            time.sleep(2)  # Delay singkat sebelum mencoba server berikutnya
            
    log.error("Semua server alternatif Overpass API gagal diakses atau memblokir request.")
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


def process_osm_elements(elements: list, city_name: str) -> list[dict]:
    """Mengonversi data mentah OSM ke format standard UMKM Leads."""
    leads = []
    
    for el in tqdm(elements, desc="Memproses data tempat", ncols=80):
        tags = el.get("tags", {})
        name = tags.get("name")
        
        # Bisnis tanpa nama di-skip
        if not name:
            continue
            
        # Cek keaktifan bisnis (lewati yang sudah tutup/tutup permanen/bangkrut)
        if not is_business_active(tags):
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

        # Tentukan instagram_url jika ada di tag OSM (misal jika ada link marketplace)
        instagram_url = ""
        if website_type == "marketplace" and "instagram.com" in website_lower:
            instagram_url = website

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
            "instagram_url": instagram_url,
            "google_maps_url": google_maps_url,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    print(f"  OpenStreetMap UMKM Scraper — Kota: {city}")
    print("=" * 60 + "\n")
    
    elements = fetch_osm_data(city)
    
    if not elements:
        print("\n[INFO] Tidak ditemukan data atau API sedang sibuk.")
        return
        
    leads = process_osm_elements(elements, city)
    
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
        "lead_score", "prioritas"
    ]
    
    with open(csv_filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, lead in enumerate(leads, 1):
            row_data = lead.copy()
            row_data[""] = idx # Kolom index pertama
            writer.writerow(row_data)
            
    print(f"Data CSV Leads disimpan ke: {csv_filename}")
    print("\nLangkah selanjutnya:")
    print("  Jalankan RAG AI untuk generate draf pesan penawaran di dashboard web!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OSM UMKM Scraper")
    parser.add_argument("--city", type=str, default=DEFAULT_CITY, help=f"Nama kota tujuan (default: {DEFAULT_CITY})")
    args = parser.parse_args()
    
    run_osm_scraper(args.city)

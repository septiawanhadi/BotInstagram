"""
resolve_ig_usernames.py
Mencari username Instagram asli berdasarkan nama bisnis hasil scrap OpenStreetMap (OSM).
"""
import os
import sys
import csv
import time
import random
import logging
from pathlib import Path
from dotenv import load_dotenv
from instagrapi import Client

# Reconfigure stdout/stderr to UTF-8 to handle emojis safely on Windows
for stream in (sys.stdout, sys.stderr):
    if stream and hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s -- %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ig-resolver")

load_dotenv()

INPUT_FILE = "output/rag_dm_drafts.csv"
OUTPUT_FILE = "output/rag_dm_drafts_resolved.csv"

def verify_name_overlap(business_name: str, ig_user) -> bool:
    """Check if the matched Instagram account name or username has some overlap with the business name to prevent mismatching."""
    import re
    # Clean and split business name into words
    biz_words = set(re.findall(r'[a-zA-Z0-9]+', business_name.lower()))
    
    # Ignore common generic words
    stop_words = {"cafe", "restaurant", "shop", "boutique", "salon", "laundry", "bakery", "warung", "kopi", "kedai", "indonesia", "surabaya", "manchester", "london", "store", "beauty", "spa", "deli", "food"}
    clean_biz_words = biz_words - stop_words
    if not clean_biz_words:
        clean_biz_words = biz_words  # fallback

    # Clean and split IG username and full name
    ig_words = set(re.findall(r'[a-zA-Z0-9]+', ig_user.username.lower()))
    if ig_user.full_name:
        ig_words.update(re.findall(r'[a-zA-Z0-9]+', ig_user.full_name.lower()))
        
    overlap = clean_biz_words.intersection(ig_words)
    return len(overlap) > 0


def main():
    if not os.path.exists(INPUT_FILE):
        log.error(f"File input tidak ditemukan di: {INPUT_FILE}")
        return

    username = os.getenv("IG_USERNAME")
    sessionid = os.getenv("IG_SESSIONID")
    
    if not sessionid:
        log.error("IG_SESSIONID belum diset di .env. Mohon login di browser dan masukkan sessionid Anda.")
        return

    # Inisialisasi client
    cl = Client()
    log.info("Menghubungkan ke Instagram via Session ID...")
    try:
        cl.login_by_sessionid(sessionid)
        cl.username = username or "user"
        log.info("Login berhasil!")
    except Exception as e:
        log.error(f"Gagal login: {e}")
        return

    # Membaca draf
    rows = []
    with open(INPUT_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        # Ensure instagram_url is in fieldnames
        if "instagram_url" not in fieldnames:
            fieldnames = list(fieldnames) + ["instagram_url"]
        for row in reader:
            rows.append(row)

    log.info(f"Memproses {len(rows)} data UMKM...")
    resolved_count = 0

    for i, row in enumerate(rows, 1):
        old_username = row.get("username", "")
        business_name = row.get("full_name", "")
        
        # Hanya cari jika username saat ini masih berstatus dummy (osm_...)
        if old_username.startswith("osm_") and business_name:
            # Extract city from lead data (city field or from biography)
            city = row.get("city", "")
            if not city:
                bio = row.get("biography", "")
                if "Location:" in bio:
                    location_part = bio.split("Location:")[-1].split("|")[0].strip()
                    parts = [p.strip() for p in location_part.split(",")]
                    city = parts[-1] if parts else ""
            
            query = f"{business_name} {city}".strip()
            log.info(f"[{i}/{len(rows)}] Searching IG for: '{business_name}' (Query: '{query}')...")
            
            try:
                # Cari user di Instagram
                results = cl.search_users(query)
                matched_user = None
                
                if results:
                    # Verify first few results
                    for candidate in results[:3]:
                        if verify_name_overlap(business_name, candidate):
                            matched_user = candidate
                            break
                
                if matched_user:
                    new_username = matched_user.username
                    log.info(f"  -> DITEMUKAN: @{new_username} ({matched_user.full_name})")
                    
                    # Update data baris
                    row["username"] = new_username
                    row["instagram_url"] = f"https://instagram.com/{new_username}"
                    
                    # Perbarui isi pesan RAG (ganti mention dummy @osm_ ke @username asli)
                    pesan = row.get("pesan_dm_rag", "")
                    if f"@{old_username}" in pesan:
                        pesan = pesan.replace(f"@{old_username}", f"@{new_username}")
                    elif old_username in pesan:
                        pesan = pesan.replace(old_username, new_username)
                    row["pesan_dm_rag"] = pesan
                    
                    resolved_count += 1
                else:
                    log.warning(f"  -> Tidak ditemukan hasil pencarian yang valid/beririsan untuk: {business_name}")
            except Exception as e:
                log.error(f"  -> Error saat mencari: {e}")
            
            # Delay acak 5-9 detik agar aman dari limitasi Instagram
            delay = random.randint(5, 9)
            time.sleep(delay)

    # Simpan hasil akhir
    Path("output").mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log.info("\n" + "=" * 50)
    log.info("PENCARIAN SELESAI")
    log.info("=" * 50)
    log.info(f"Total UMKM diproses : {len(rows)}")
    log.info(f"Berhasil di-resolve  : {resolved_count} akun")
    log.info(f"File tersimpan di   : {OUTPUT_FILE}")
    log.info("=" * 50)

if __name__ == "__main__":
    main()

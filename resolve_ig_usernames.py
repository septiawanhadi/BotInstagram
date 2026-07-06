"""
resolve_ig_usernames.py
Mencari username Instagram asli berdasarkan nama bisnis hasil scrap OpenStreetMap (OSM).
"""
import os
import sys
import re
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

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = str(BASE_DIR / "output" / "rag_dm_drafts_resolved.csv")

def find_input_file() -> str:
    """Mencari file input terbaik secara dinamis."""
    candidates = [
        "output/rag_dm_drafts_resolved.csv",
        "output/rag_dm_drafts.csv",
    ]
    for c in candidates:
        path = BASE_DIR / c
        if path.exists():
            return str(path)
            
    # Fallback to latest raw leads from scraper
    import glob
    raw_files = sorted(glob.glob(str(BASE_DIR / "output" / "umkm_leads_*.csv")), reverse=True)
    if raw_files:
        return raw_files[0]
        
    return ""

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
    # 1. Cari raw leads CSV terbaru sebagai master list
    import glob
    raw_files = sorted(glob.glob(str(BASE_DIR / "output" / "umkm_leads_*.csv")), reverse=True)
    if not raw_files:
        log.error("Tidak ditemukan file raw leads (umkm_leads_*.csv). Harap jalankan Scraper terlebih dahulu.")
        return
    master_file = raw_files[0]
    log.info(f"Menggunakan master file leads: {master_file}")

    # Membaca master leads
    rows = []
    fieldnames = []
    with open(master_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(dict(row))

    # 2. Cari data lama (resolved / drafts) untuk dioverlay agar tidak kehilangan progress/draft
    existing_data = {}
    overlay_candidates = [
        BASE_DIR / "output" / "rag_dm_drafts_resolved.csv",
        BASE_DIR / "output" / "rag_dm_drafts.csv"
    ]
    for candidate in overlay_candidates:
        if candidate.exists():
            log.info(f"Menemukan file data lama untuk overlay: {candidate}")
            try:
                with open(candidate, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = row.get("username") or row.get("full_name")
                        if key:
                            existing_data[key] = dict(row)
                break
            except Exception as e:
                log.warning(f"Gagal membaca file overlay {candidate}: {e}")

    # Pastikan kolom-kolom baru ada di fieldnames
    for col in ["instagram_url", "pesan_dm_rag", "pesan_email_rag"]:
        if col not in fieldnames:
            fieldnames.append(col)

    for row in rows:
        # Isi nilai default
        for col in ["instagram_url", "pesan_dm_rag", "pesan_email_rag"]:
            row.setdefault(col, "")
            
        username = row.get("username", "")
        fullname = row.get("full_name", "")
        
        # Overlay data jika ada kecocokan
        old_row = existing_data.get(username) or existing_data.get(fullname)
        if old_row:
            if old_row.get("username") and not old_row["username"].startswith("osm_"):
                row["username"] = old_row["username"]
            if old_row.get("instagram_url"):
                row["instagram_url"] = old_row["instagram_url"]
            if old_row.get("pesan_dm_rag"):
                row["pesan_dm_rag"] = old_row["pesan_dm_rag"]
            if old_row.get("pesan_email_rag"):
                row["pesan_email_rag"] = old_row["pesan_email_rag"]
            if old_row.get("email") and not row.get("email"):
                row["email"] = old_row["email"]
            if old_row.get("phone") and not row.get("phone"):
                row["phone"] = old_row["phone"]

    username_ig = os.getenv("IG_USERNAME")
    sessionid = os.getenv("IG_SESSIONID")
    
    if not sessionid:
        log.error("IG_SESSIONID belum diset di .env. Mohon login di browser dan masukkan sessionid Anda.")
        return

    # Inisialisasi client
    cl = Client()
    log.info("Menghubungkan ke Instagram via Session ID...")
    try:
        cl.login_by_sessionid(sessionid)
        cl.username = username_ig or "user"
        log.info("Login berhasil!")
    except Exception as e:
        log.error(f"Gagal login: {e}")
        return

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
                    # Tarik informasi detail kontak bisnis publik (email & no HP)
                    try:
                        user_info = cl.user_info(matched_user.pk)
                        if user_info:
                            public_email = getattr(user_info, "public_email", "")
                            contact_phone = getattr(user_info, "contact_phone_number", "") or getattr(user_info, "public_phone_number", "")
                            bio_url = getattr(user_info, "external_url", "")
                            
                            # Jika public_email kosong, coba cari lewat Regex di teks biografi (bio)
                            if not public_email:
                                bio_text = getattr(user_info, "biography", "")
                                if bio_text:
                                    found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', bio_text)
                                    if found_emails:
                                        public_email = found_emails[0]
                                        log.info(f"     [EMAIL DETECTED VIA REGEX BIO]: {public_email}")

                            if public_email:
                                row["email"] = public_email
                                log.info(f"     [EMAIL DETECTED]: {public_email}")
                            if contact_phone:
                                # Rapikan nomor HP kontak
                                digits = "".join(c for c in contact_phone if c.isdigit() or c == "+")
                                if digits.startswith("08"):
                                    digits = "+62" + digits[1:]
                                elif digits.startswith("628"):
                                    digits = "+" + digits
                                row["phone"] = digits
                                log.info(f"     [PHONE DETECTED]: {digits}")
                            if bio_url and (not row.get("external_url") or row.get("external_url") == ""):
                                row["external_url"] = bio_url
                    except Exception as e_info:
                        log.warning(f"     Gagal menarik detail info kontak: {e_info}")
                    
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

            # Simpan progress secara bertahap (incremental autosave) agar aman jika laptop mati/mati lampu mid-way
            try:
                with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
            except Exception as e_save:
                log.warning(f"Gagal melakukan autosave progress: {e_save}")

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

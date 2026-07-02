"""
dm_sender.py — Kirim DM otomatis ke leads UMKM dari hasil scraper

Cara pakai:
  python dm_sender.py                    # Kirim ke semua leads prioritas tinggi
  python dm_sender.py --limit 20         # Kirim ke 20 akun pertama
  python dm_sender.py --min-score 60     # Kirim ke akun dengan score >= 60
  python dm_sender.py --test             # Preview pesan tanpa kirim
"""
import os
import csv
import time
import random
import logging
import glob
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s -- %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dm-sender")

# ============================================================
# KONFIGURASI PESAN DM
# Sesuaikan template pesan sesuai kebutuhan Anda
# ============================================================

# Gunakan {name} untuk nama bisnis, {username} untuk handle Instagram
DM_TEMPLATES = [
    """Halo {name}! 

Saya lihat bisnis Anda di Instagram dan produk/layanannya sangat menarik!

Apakah {name} sudah punya website resmi? Kami membantu UMKM seperti Anda membangun website profesional yang bisa meningkatkan kepercayaan pelanggan dan penjualan.

Website mulai dari harga terjangkau, desain modern, dan bisa langsung aktif!

Boleh saya bantu? DM balik atau cek profil kami ya!""",

    """Hai {name}!

Produk/usaha Anda kelihatan bagus banget di Instagram!

Kami dari @dripcodedev spesialis pembuatan website untuk bisnis lokal & UMKM. Website bisa bikin bisnis Anda lebih dipercaya dan mudah ditemukan pelanggan baru via Google.

Tertarik konsultasi gratis? Balas pesan ini ya!""",

    """Halo kak {name}!

Saya dari tim @dripcodedev yang membantu bisnis-bisnis lokal Indonesia go digital lewat website profesional.

Sudah banyak UMKM yang omzetnya naik setelah punya website sendiri. Apakah {name} tertarik?

Konsultasi gratis, tanpa komitmen! Balas DM ini untuk info lebih lanjut.""",
]

# Delay antar DM (detik) — jangan terlalu cepat!
DM_DELAY_MIN = 30   # minimum 30 detik
DM_DELAY_MAX = 90   # maksimum 90 detik

# Maksimum DM per sesi (aman: 20-30 per hari)
MAX_DM_PER_SESSION = 20

BASE_DIR = Path(__file__).resolve().parent
TRACKING_FILE = str(BASE_DIR / "output" / "dm_sent_log.csv")


def load_sent_usernames() -> set:
    """Load daftar username yang sudah pernah di-DM."""
    sent = set()
    if Path(TRACKING_FILE).exists():
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "sent":
                    sent.add(row["username"])
    return sent


def log_dm_result(username: str, status: str, message_preview: str = ""):
    """Catat hasil pengiriman DM ke file log."""
    Path("output").mkdir(exist_ok=True)
    file_exists = Path(TRACKING_FILE).exists()

    with open(TRACKING_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "username", "status", "message_preview"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "status": status,
            "message_preview": message_preview[:80] if message_preview else "",
        })


def load_leads(target_file: str = "output/umkm_leads_20260630_215902.csv", min_score: int = 60) -> list[dict]:
    """Load leads dari file CSV dengan filter score."""
    path_obj = Path(target_file)
    if not path_obj.is_absolute():
        target_file = str(BASE_DIR / target_file)

    if not os.path.exists(target_file):
        raise FileNotFoundError(
            f"Tidak ditemukan file leads di: {target_file}"
        )

    log.info(f"Membaca leads dari: {target_file}")

    leads = []
    with open(target_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                score = int(row.get("lead_score", 0) or 0)
                if score >= min_score:
                    leads.append(row)
            except (ValueError, TypeError):
                # Fallback jika lead_score kosong tetapi baris valid
                leads.append(row)

    log.info(f"Ditemukan {len(leads)} leads dalam file target.")
    return leads


# ============================================================
# BUAT PESAN PERSONAL
# ============================================================
def build_message(lead: dict) -> str:
    """Buat pesan DM yang dipersonalisasi untuk satu lead."""
    name = lead.get("full_name") or lead.get("username", "")
    # Ambil nama depan/nama bisnis saja (potong di kata ke-3)
    name_parts = name.split()
    short_name = " ".join(name_parts[:2]) if len(name_parts) > 1 else name

    # Pilih template secara acak agar tidak spam filter
    template = random.choice(DM_TEMPLATES)
    return template.format(name=short_name, username=lead.get("username", ""))


def challenge_code_handler(username, choice):
    """Menangani kode verifikasi keamanan secara interaktif."""
    if choice == 0:
        print(f"\n[VERIFIKASI] Instagram mengirimkan kode verifikasi melalui SMS.")
        code = input("Masukkan kode verifikasi SMS: ").strip()
        return code
    elif choice == 1:
        print(f"\n[VERIFIKASI] Instagram mengirimkan kode verifikasi melalui EMAIL.")
        code = input("Masukkan kode verifikasi EMAIL: ").strip()
        return code
    return None


# ============================================================
# LOGIN INSTAGRAM
# ============================================================
def create_instagram_client():
    """Login ke Instagram menggunakan Instagrapi (mendukung bypass via Session ID)."""
    try:
        from instagrapi import Client
        from instagrapi.exceptions import ChallengeRequired
    except ImportError:
        raise ImportError("Instagrapi belum terinstall. Jalankan: pip install instagrapi")

    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    sessionid = os.getenv("IG_SESSIONID")

    cl = Client()
    cl.challenge_code_handler = challenge_code_handler
    session_file = BASE_DIR / "session.json"

    # CARA 1: Login menggunakan Session ID Cookie (Paling aman, bypass challenge)
    if sessionid and sessionid != "isi_session_id_browser_anda_disini":
        log.info("Mencoba login bypass menggunakan Session ID dari browser...")
        try:
            cl.login_by_sessionid(sessionid)
            # Dapatkan info username dari session untuk memverifikasi login aktif
            cl.username = username or "user"
            log.info("Login bypass berhasil menggunakan Session ID!")
            cl.dump_settings(session_file)
            return cl
        except Exception as session_err:
            log.warning(f"Gagal login dengan Session ID: {session_err}. Beralih ke metode biasa...")

    # CARA 2: Gunakan session cache jika ada
    if session_file.exists():
        log.info("Menggunakan session tersimpan...")
        try:
            cl.load_settings(session_file)
            cl.login(username, password)
            log.info(f"Login berhasil sebagai @{username}")
            return cl
        except Exception:
            log.warning("Session kadaluarsa, login ulang...")
            session_file.unlink(missing_ok=True)

    # CARA 3: Login biasa (dengan challenge handler)
    if not username or not password:
        raise ValueError(
            "IG_USERNAME dan IG_PASSWORD atau IG_SESSIONID harus diisi di file .env!"
        )

    log.info(f"Login ke Instagram sebagai @{username}...")
    try:
        cl.login(username, password)
        cl.dump_settings(session_file)
        log.info("Login berhasil!")
    except ChallengeRequired as e:
        log.info("Instagram mendeteksi login baru dan meminta verifikasi keamanan (Challenge).")
        log.info("Mencoba memicu pengiriman kode verifikasi secara interaktif...")
        try:
            cl.challenge_resolve(cl.last_json)
            cl.login(username, password)
            cl.dump_settings(session_file)
            log.info("Login berhasil setelah menyelesaikan verifikasi keamanan!")
        except Exception as challenge_err:
            log.error(f"Gagal menyelesaikan verifikasi otomatis: {challenge_err}")
            raise e
            
    return cl


# ============================================================
# KIRIM DM
# ============================================================
def send_dm(cl, username: str, message: str) -> bool:
    """Kirim satu DM ke username tertentu. Return True jika berhasil."""
    try:
        user_id = cl.user_id_from_username(username)
        cl.direct_send(message, [user_id])
        return True
    except Exception as e:
        log.warning(f"Gagal kirim DM ke @{username}: {e}")
        return False


# ============================================================
# MAIN
# ============================================================
def run_dm_campaign(
    target_file: str = "output/umkm_leads_20260630_215902.csv",
    limit: int = MAX_DM_PER_SESSION,
    min_score: int = 60,
    test_mode: bool = False,
):
    """Jalankan kampanye DM otomatis ke leads UMKM."""

    print("\n" + "=" * 55)
    print("  DM OTOMATIS UNTUK LEADS UMKM")
    if test_mode:
        print("  [MODE TEST - Tidak akan kirim DM sungguhan]")
    print("=" * 55)

    # Load leads
    try:
        leads = load_leads(target_file=target_file, min_score=min_score)
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        return

    # Filter yang sudah di-DM sebelumnya
    sent_usernames = load_sent_usernames()
    pending = [l for l in leads if l.get("username") not in sent_usernames]

    print(f"  Total leads    : {len(leads)}")
    print(f"  Sudah di-DM    : {len(sent_usernames)}")
    print(f"  Antrian baru   : {len(pending)}")
    print(f"  Akan dikirim   : {min(limit, len(pending))} DM")
    print("=" * 55)

    if not pending:
        print("\n[INFO] Semua leads sudah pernah di-DM!")
        return

    # Login (skip jika test mode)
    cl = None
    if not test_mode:
        try:
            cl = create_instagram_client()
        except Exception as e:
            print(f"\n[ERROR] Login gagal: {e}")
            return

    # Kirim DM
    sent_count = 0
    failed_count = 0
    skipped_count = 0
    to_send = pending[:limit]

    print()
    for i, lead in enumerate(to_send, 1):
        username = lead.get("username", "")
        
        # Cek jika username menggunakan format OSM dummy
        if username.startswith("osm_"):
            print(f"[{i}/{len(to_send)}] @{username} (DILEWATI)")
            print(f"  [INFO] Username dummy dari OpenStreetMap dideteksi. Pengiriman dilewati.")
            log_dm_result(username, "skipped_dummy", "Username dummy OSM dilewati.")
            skipped_count += 1
            print("-" * 40)
            continue
            
        # Gunakan draf pesan RAG dari AI jika ada kolomnya
        if "pesan_dm_rag" in lead and lead["pesan_dm_rag"].strip():
            message = lead["pesan_dm_rag"].strip()
            log.info("Menggunakan draf pesan kustom hasil RAG AI.")
        else:
            message = build_message(lead)
            
        score = lead.get("lead_score", "?")
        followers = int(lead.get("follower_count", 0) or 0)

        print(f"[{i}/{len(to_send)}] @{username} (score: {score}, {followers:,} followers)")
        print(f"  Pesan: {message[:80].strip()}...")

        if test_mode:
            print("  [TEST] Pesan TIDAK dikirim (mode preview)")
            log_dm_result(username, "test_preview", message)
            time.sleep(0.5)
            print("-" * 40)
            continue

        # Kirim DM sungguhan
        success = send_dm(cl, username, message)

        if success:
            print(f"  [OK] DM terkirim!")
            log_dm_result(username, "sent", message)
            sent_count += 1
        else:
            print(f"  [GAGAL] DM tidak terkirim")
            log_dm_result(username, "failed", message)
            failed_count += 1

        # Delay random antar DM
        if i < len(to_send):
            delay = random.randint(DM_DELAY_MIN, DM_DELAY_MAX)
            print(f"  Menunggu {delay} detik sebelum DM berikutnya...\n")
            time.sleep(delay)

    # Ringkasan
    print("\n" + "=" * 55)
    print("  RINGKASAN KAMPANYE DM")
    print("=" * 55)
    if test_mode:
        print(f"  Mode Preview - tidak ada DM dikirim")
        print(f"  Total preview : {len(to_send)} akun")
    else:
        print(f"  Berhasil dikirim : {sent_count}")
        print(f"  Gagal            : {failed_count}")
        print(f"  Dilewati (dummy) : {skipped_count}")
        print(f"  Log tersimpan di : {TRACKING_FILE}")
    print("=" * 55)


# ============================================================
# ENTRY POINT (CLI)
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kirim DM otomatis ke leads UMKM")
    parser.add_argument("--csv", type=str, default="output/umkm_leads_20260630_215902.csv",
                        help="Path ke file CSV leads (default: output/umkm_leads_20260630_215902.csv)")
    parser.add_argument("--limit", type=int, default=MAX_DM_PER_SESSION,
                        help=f"Maksimum DM yang dikirim (default: {MAX_DM_PER_SESSION})")
    parser.add_argument("--min-score", type=int, default=60,
                        help="Minimum lead score untuk di-DM (default: 60)")
    parser.add_argument("--test", action="store_true",
                        help="Preview pesan tanpa kirim DM sungguhan")
    args = parser.parse_args()

    run_dm_campaign(
        target_file=args.csv,
        limit=args.limit,
        min_score=args.min_score,
        test_mode=args.test,
    )

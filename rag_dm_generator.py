"""
rag_dm_generator.py — RAG-Enhanced DM Generator untuk UMKM

Cara kerja:
1. Index data profil UMKM ke ChromaDB (vector store)
2. Untuk setiap lead, retrieve konteks relevan dari profil mereka
3. Gemini AI generate DM yang sangat personal berdasarkan konteks itu
4. Kirim via Instagrapi

Cara pakai:
  python rag_dm_generator.py --index         # Build/update vector database dari CSV
  python rag_dm_generator.py --test          # Preview DM tanpa kirim
  python rag_dm_generator.py --limit 10      # Generate & kirim 10 DM
"""
import os
import csv
import glob
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s -- %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rag-dm")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TRACKING_FILE = "output/rag_dm_log.csv"

# ============================================================
# CONTOH SUKSES — Knowledge Base untuk RAG
# Ini adalah contoh hasil nyata yang digunakan AI sebagai referensi
# ============================================================
SUCCESS_STORIES = [
    {
        "business": "Warung Nasi Padang Bu Rina",
        "category": "kuliner",
        "problem": "Hanya bisa ditemukan lewat Instagram, pelanggan jauh susah order",
        "solution": "Buat website dengan menu online & Google Maps integration",
        "result": "Kunjungan naik 40%, sekarang muncul di halaman pertama Google pencarian 'nasi padang jaksel'",
    },
    {
        "business": "Batik Sogan Solo",
        "category": "fashion/tekstil",
        "problem": "Jual hanya di Tokopedia, tidak punya brand identity sendiri",
        "solution": "Website dengan galeri koleksi & cerita brand",
        "result": "Pembeli wholesale dari Bali & Surabaya mulai kontak langsung, margin lebih tinggi",
    },
    {
        "business": "Kue Kering Bu Dewi",
        "category": "makanan",
        "problem": "Order hanya lewat WA, susah kelola & sering kelewatan",
        "solution": "Website dengan form order online & payment gateway",
        "result": "Kapasitas produksi naik 2x karena sistem order lebih teratur",
    },
    {
        "business": "Konveksi Bandung Jaya",
        "category": "konveksi/garmen",
        "problem": "Hanya dapat klien dari referral mulut ke mulut",
        "solution": "Portfolio website dengan galeri produk & testimoni",
        "result": "Dapat 3 klien korporat baru dari Jakarta dalam 2 bulan pertama",
    },
]


# ============================================================
# VECTOR STORE SETUP (ChromaDB)
# ============================================================
def get_vector_store():
    """Inisialisasi ChromaDB sebagai vector store lokal."""
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        raise ImportError("ChromaDB belum terinstall. Jalankan: pip install chromadb")

    client = chromadb.PersistentClient(path="./chroma_db")

    # Gunakan embedding function bawaan ChromaDB (tidak perlu API key tambahan)
    ef = embedding_functions.DefaultEmbeddingFunction()

    collection = client.get_or_create_collection(
        name="umkm_leads",
        embedding_function=ef,
        metadata={"description": "Database profil akun UMKM untuk RAG DM generation"}
    )
    return collection


def index_leads_to_vectordb(csv_path: Optional[str] = None):
    """Index semua leads dari CSV ke ChromaDB vector store."""
    # Cari CSV terbaru jika tidak disebut eksplisit
    if not csv_path:
        files = sorted(glob.glob("output/umkm_leads_*.csv"), reverse=True)
        if not files:
            raise FileNotFoundError("Tidak ada CSV leads. Jalankan scraper.py dahulu.")
        csv_path = files[0]

    log.info(f"Indexing leads dari: {csv_path}")
    collection = get_vector_store()

    leads = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(row)

    # Hapus data lama dan re-index
    try:
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
            log.info(f"Menghapus {len(existing['ids'])} dokumen lama dari vector DB")
    except Exception:
        pass

    seen_ids = set()
    unique_documents = []
    unique_metadatas = []
    unique_ids = []

    for lead in leads:
        username = lead.get("username", "")
        if not username:
            continue
        
        doc_id = f"umkm_{username}"
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)

        # Buat representasi teks kaya untuk embedding
        doc_text = f"""
Nama bisnis: {lead.get('full_name', username)}
Username Instagram: @{username}
Kategori bisnis: {lead.get('category', 'tidak diketahui')}
Bio: {lead.get('biography', '')}
Jumlah followers: {lead.get('follower_count', 0)}
Jumlah postingan: {lead.get('media_count', 0)}
Tipe website: {lead.get('website_type', 'kosong')}
URL website: {lead.get('external_url', 'tidak ada')}
Nomor telepon: {lead.get('phone', 'tidak ada')}
Email: {lead.get('email', 'tidak ada')}
Lead score: {lead.get('lead_score', 0)}
        """.strip()

        unique_documents.append(doc_text)
        unique_metadatas.append({
            "username": username,
            "full_name": lead.get("full_name", ""),
            "category": lead.get("category", ""),
            "follower_count": int(lead.get("follower_count", 0) or 0),
            "website_type": lead.get("website_type", "kosong"),
            "phone": lead.get("phone", ""),
            "email": lead.get("email", ""),
            "lead_score": int(lead.get("lead_score", 0) or 0),
        })
        unique_ids.append(doc_id)

    if unique_documents:
        collection.add(documents=unique_documents, metadatas=unique_metadatas, ids=unique_ids)
        log.info(f"[OK] {len(unique_documents)} leads unik berhasil di-index ke ChromaDB")
    else:
        log.warning("Tidak ada leads yang bisa di-index!")

    return len(unique_documents)


# ============================================================
# RAG: RETRIEVE CONTEXT & GENERATE DM
# ============================================================
def get_relevant_context(username: str, category: str) -> str:
    """Ambil konteks relevan dari vector DB dan success stories."""
    # Cari success story yang paling relevan berdasarkan kategori
    relevant_stories = []
    for story in SUCCESS_STORIES:
        if any(kw in category.lower() for kw in story["category"].split("/")):
            relevant_stories.append(story)

    if not relevant_stories:
        relevant_stories = SUCCESS_STORIES[:2]  # fallback ke 2 cerita pertama

    context = "Contoh bisnis yang berhasil setelah punya website:\n"
    for story in relevant_stories[:2]:
        context += f"""
- {story['business']} ({story['category']}):
  Masalah: {story['problem']}
  Solusi: {story['solution']}
  Hasil: {story['result']}
"""
    return context


def generate_personalized_dm(lead: dict) -> str:
    """
    Generate DM yang sangat personal menggunakan Gemini + RAG context.
    Setiap DM unik berdasarkan profil spesifik si UMKM.
    """
    # Ambil konfigurasi tipe AI
    ai_type = os.getenv("AI_TYPE", "cloud").lower()
    
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        raise ImportError("langchain-core belum terinstall.")

    if ai_type == "local":
        # Gunakan OpenAI-compatible local API (seperti Ollama / LM Studio)
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            log.info("Menginstall langchain-openai untuk koneksi LLM lokal...")
            import subprocess
            subprocess.run(["pip", "install", "langchain-openai"], check=True)
            from langchain_openai import ChatOpenAI
            
        local_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
        local_model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
        
        log.info(f"Menggunakan LLM Lokal: {local_model} ({local_url})")
        llm = ChatOpenAI(
            base_url=local_url,
            api_key="ollama", # dummy key
            model=local_model,
            temperature=0.8
        )
    elif ai_type == "openrouter":
        # Gunakan OpenRouter API
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            log.info("Menginstall langchain-openai untuk koneksi OpenRouter...")
            import subprocess
            subprocess.run(["pip", "install", "langchain-openai"], check=True)
            from langchain_openai import ChatOpenAI
            
        or_key = os.getenv("OPENROUTER_API_KEY")
        or_model = os.getenv("OPENROUTER_MODEL", "google/gemma-2-9b-it:free")
        
        if not or_key:
            raise ValueError("OPENROUTER_API_KEY belum diisi di file .env!")
            
        log.info(f"Menggunakan OpenRouter Model: {or_model}")
        llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=or_key,
            model=or_model,
            temperature=0.8,
            default_headers={
                "HTTP-Referer": "https://github.com/septiawanhadi/BotInstagram",
                "X-Title": "UMKM Scraper Bot"
            }
        )
    else:
        # Gunakan Gemini (Cloud)
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError("langchain-google-genai belum terinstall.")
            
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY belum diisi di file .env!")
            
        llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            google_api_key=GEMINI_API_KEY,
            temperature=0.8,
        )

    username = lead.get("username", "")
    full_name = lead.get("full_name") or username
    category = lead.get("category", "bisnis")
    bio = lead.get("biography", "")
    followers = int(lead.get("follower_count", 0) or 0)
    website_type = lead.get("website_type", "kosong")
    has_phone = bool(lead.get("phone"))

    # Retrieve konteks relevan
    success_context = get_relevant_context(username, category)

    system_prompt = """Kamu adalah sales copywriter ahli untuk jasa web development bernama @dripcodedev.

Tugasmu: Tulis pesan DM Instagram yang sangat personal dan natural untuk satu akun UMKM spesifik.

Aturan PENTING:
1. JANGAN PERNAH menyebut atau menyertakan username dummy yang diawali '@osm_' (seperti @osm_4830378537). Sebagai gantinya, sebutkan nama asli bisnisnya secara langsung (misal: Soto Banjar Acil Miah).
2. Pesan harus terasa ramah dan ditulis oleh manusia secara personal, hindari gaya bahasa kaku atau kata ganti "Gue", "Aku", "Saya". Gunakan sapaan yang sopan dan akrab seperti "Kak" atau sebut nama bisnisnya.
3. Sebutkan detail spesifik dari bisnis mereka (seperti menu andalan, lokasi, atau bidang usahanya) agar mereka tahu ini bukan pesan otomatis/spam.
4. JANGAN gunakan tanda petik ganda untuk membungkus seluruh isi pesan.
5. Jangan terlalu panjang — maksimal 3-4 kalimat pendek.
6. Akhiri dengan pertanyaan atau ajakan yang ringan dan ramah (soft CTA), bukan jualan langsung.
7. Tulis HANYA teks pesan DM saja, tanpa penjelasan atau penutup lainnya."""

    user_prompt = f"""Buat DM Instagram yang personal untuk bisnis ini:

PROFIL BISNIS:
- Nama Bisnis: {full_name}
- Kategori: {category}
- Informasi Tambahan / Lokasi / Deskripsi: "{bio}"
- Status website: {website_type} ({"tidak punya website asli" if website_type in ["kosong", "marketplace", "linkinbio"] else "sudah punya website"})

Tulis DM pendek, ramah, dan personal yang ditujukan langsung ke pemilik {full_name} agar mereka tertarik untuk berdiskusi."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    response = llm.invoke(messages)
    return response.content.strip()


# ============================================================
# TRACKING
# ============================================================
def load_sent_usernames() -> set:
    sent = set()
    if Path(TRACKING_FILE).exists():
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "sent":
                    sent.add(row["username"])
    return sent


def log_result(username: str, status: str, message: str = ""):
    Path("output").mkdir(exist_ok=True)
    file_exists = Path(TRACKING_FILE).exists()
    with open(TRACKING_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "username", "status", "message"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "status": status,
            "message": message[:200],
        })


# ============================================================
# MAIN RUNNER
# ============================================================
def run(limit: int = 10, min_score: int = 60, test_mode: bool = False):
    """Jalankan RAG DM campaign."""
    print("\n" + "=" * 55)
    print("  RAG-POWERED DM GENERATOR UNTUK UMKM")
    if test_mode:
        print("  [MODE TEST - Tidak kirim DM sungguhan]")
    print("=" * 55)

    # Load leads dari CSV
    csv_files = sorted(glob.glob("output/umkm_leads_*.csv"), reverse=True)
    if not csv_files:
        print("[ERROR] Tidak ada CSV leads. Jalankan scraper.py dahulu.")
        return

    leads = []
    with open(csv_files[0], "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                score = int(row.get("lead_score", 0) or 0)
                if score >= min_score:
                    leads.append(row)
            except (ValueError, TypeError):
                continue

    sent = load_sent_usernames()
    pending = [l for l in leads if l.get("username") not in sent]
    to_process = pending[:limit]

    print(f"  Total leads   : {len(leads)}")
    print(f"  Sudah di-DM   : {len(sent)}")
    print(f"  Antrian baru  : {len(pending)}")
    print(f"  Akan diproses : {len(to_process)}")
    print("=" * 55 + "\n")

    # Login Instagram (hika bukan test/generate-only)
    cl = None
    generate_only = test_mode
    
    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    
    if not generate_only:
        if not username or not password or username == "username_akun_baru_anda":
            log.info("Credentials Instagram tidak diisi. Bot akan berjalan dalam mode [GENERATE ONLY] (Hanya membuat draf pesan).")
            generate_only = True
        else:
            try:
                from instagrapi import Client
                cl = Client()
                session_file = Path("session.json")
                if session_file.exists():
                    try:
                        cl.load_settings(session_file)
                    except Exception:
                        pass
                cl.login(username, password)
                cl.dump_settings(session_file)
                log.info(f"Login berhasil sebagai @{username}")
            except Exception as e:
                log.warning(f"Login Instagram gagal: {e}. Beralih ke mode [GENERATE ONLY].")
                generate_only = True

    sent_count = 0
    drafts_created = []
    
    for i, lead in enumerate(to_process, 1):
        uname = lead.get("username", "")
        print(f"[{i}/{len(to_process)}] Generating DM untuk @{uname}...")

        try:
            # Generate DM personal dengan RAG + Gemini
            dm_text = generate_personalized_dm(lead)

            print(f"\n  --- DM DRAF UNTUK @{uname} ---")
            print(f"  {dm_text}")
            print(f"  ----------------------------\n")

            drafts_created.append({
                "username": uname,
                "full_name": lead.get("full_name", ""),
                "lead_score": lead.get("lead_score", ""),
                "phone": lead.get("phone", ""),
                "email": lead.get("email", ""),
                "instagram_url": lead.get("instagram_url", f"https://instagram.com/{uname}"),
                "pesan_dm_rag": dm_text,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            if generate_only:
                log_result(uname, "draft_created", dm_text)
                # Tambahkan delay agar tidak terkena limitasi rate-limit Gemini API
                time.sleep(random.randint(6, 10))
                continue

            # Kirim DM sungguhan jika login sukses
            user_id = cl.user_id_from_username(uname)
            cl.direct_send(dm_text, [user_id])
            print(f"  [OK] DM terkirim ke @{uname}!")
            log_result(uname, "sent", dm_text)
            sent_count += 1

            # Delay antar DM
            if i < len(to_process):
                delay = random.randint(45, 120)
                print(f"  Menunggu {delay} detik...\n")
                time.sleep(delay)

        except Exception as e:
            print(f"  [ERROR] Gagal memproses @{uname}: {e}")
            log_result(uname, "failed")

    # Simpan hasil draf ke CSV terpisah jika ada draf yang dibuat
    if drafts_created:
        draft_file = Path("output/rag_dm_drafts.csv")
        file_exists = draft_file.exists()
        with open(draft_file, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=drafts_created[0].keys())
            if not file_exists:
                writer.writeheader()
            writer.writerows(drafts_created)
        print(f"\n[OK] Draf pesan berhasil disimpan ke: {draft_file}")

    print("\n" + "=" * 55)
    print("  SELESAI")
    if generate_only:
        print(f"  Mode            : Generate Only (Draf)")
        print(f"  Draf dihasilkan : {len(drafts_created)}")
    else:
        print(f"  DM terkirim     : {sent_count}/{len(to_process)}")
        print(f"  Log             : {TRACKING_FILE}")
    print("=" * 55)


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAG DM Generator untuk UMKM")
    parser.add_argument("--index", action="store_true",
                        help="Build/update vector database dari CSV leads")
    parser.add_argument("--test", action="store_true",
                        help="Preview DM yang dihasilkan tanpa kirim")
    parser.add_argument("--limit", type=int, default=10,
                        help="Jumlah DM yang diproses (default: 10)")
    parser.add_argument("--min-score", type=int, default=60,
                        help="Minimum lead score (default: 60)")
    args = parser.parse_args()

    if args.index:
        print("Indexing leads ke ChromaDB...")
        count = index_leads_to_vectordb()
        print(f"[OK] {count} leads berhasil di-index!")
    else:
        run(limit=args.limit, min_score=args.min_score, test_mode=args.test)

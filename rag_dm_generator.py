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
import sys
import csv
import json
import glob
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Reconfigure stdout/stderr to UTF-8 to handle emojis safely on Windows
for stream in (sys.stdout, sys.stderr):
    if stream and hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s -- %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rag-dm")

BASE_DIR = Path(__file__).resolve().parent
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TRACKING_FILE = str(BASE_DIR / "output" / "rag_dm_log.csv")

# ============================================================
# CONTOH SUKSES — Knowledge Base untuk RAG
# Ini adalah contoh hasil nyata yang digunakan AI sebagai referensi
# ============================================================
SUCCESS_STORIES = [
    {
        "business": "Local Restaurant",
        "category": "food/restaurant",
        "problem": "Only discoverable via Instagram, customers from far away couldn't order",
        "solution": "Built a website with online menu & Google Maps integration",
        "result": "Visits increased 40%, now appears on first page of Google search",
    },
    {
        "business": "Handmade Fashion Brand",
        "category": "fashion/textile",
        "problem": "Sold only on marketplaces, no brand identity",
        "solution": "Website with collection gallery & brand story",
        "result": "Wholesale buyers started reaching out directly, higher margins",
    },
    {
        "business": "Home Bakery",
        "category": "bakery/food",
        "problem": "Orders only via WhatsApp, hard to manage & often missed",
        "solution": "Website with online order form & payment gateway",
        "result": "Production capacity doubled thanks to organized ordering system",
    },
    {
        "business": "Garment Workshop",
        "category": "garment/clothing",
        "problem": "Only got clients from word of mouth",
        "solution": "Portfolio website with product gallery & testimonials",
        "result": "Landed 3 new corporate clients in the first 2 months",
    },
]

# Country code to language name mapping
COUNTRY_LANGUAGE_MAP = {
    "ID": "Indonesian",
    "GB": "English",
    "US": "English",
    "AU": "English",
    "NZ": "English",
    "CA": "English",
    "IE": "English",
    "SG": "English",
    "MY": "Malay",
    "JP": "Japanese",
    "KR": "Korean",
    "CN": "Chinese",
    "TW": "Chinese",
    "TH": "Thai",
    "VN": "Vietnamese",
    "PH": "Filipino",
    "IN": "Hindi",
    "DE": "German",
    "FR": "French",
    "ES": "Spanish",
    "IT": "Italian",
    "PT": "Portuguese",
    "BR": "Portuguese",
    "NL": "Dutch",
    "RU": "Russian",
    "TR": "Turkish",
    "SA": "Arabic",
    "AE": "Arabic",
    "EG": "Arabic",
    "PL": "Polish",
    "SE": "Swedish",
    "NO": "Norwegian",
    "DK": "Danish",
    "FI": "Finnish",
    "CZ": "Czech",
    "HU": "Hungarian",
    "RO": "Romanian",
    "GR": "Greek",
    "MX": "Spanish",
    "AR": "Spanish",
    "CL": "Spanish",
    "CO": "Spanish",
}

def get_language_for_country(country_code: str) -> str:
    """Get the target language for DM drafts based on country code."""
    return COUNTRY_LANGUAGE_MAP.get(country_code.upper(), "English")


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
            
        local_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1").strip()
        # Otomatis tambahkan /v1 jika pengguna lupa menulisnya (seperti saat copy dari LM Studio)
        if not local_url.endswith("/v1") and not local_url.endswith("/v1/"):
            local_url = local_url.rstrip("/") + "/v1"
            
        local_model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
        
        log.info(f"Menggunakan LLM Lokal: {local_model} ({local_url})")
        llm = ChatOpenAI(
            base_url=local_url,
            api_key="ollama", # dummy key
            model=local_model,
            temperature=0.8,
            default_headers={
                "bypass-tunnel-reminder": "true"
            }
        )
    elif ai_type == "ninerouter" or ai_type == "9router":
        # Gunakan 9Router local AI gateway (OpenAI-compatible)
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            log.info("Menginstall langchain-openai untuk koneksi 9Router...")
            import subprocess
            subprocess.run(["pip", "install", "langchain-openai"], check=True)
            from langchain_openai import ChatOpenAI
            
        nr_url = os.getenv("NINEROUTER_URL", "http://localhost:20128/v1").strip()
        if not nr_url.endswith("/v1") and not nr_url.endswith("/v1/"):
            nr_url = nr_url.rstrip("/") + "/v1"
            
        nr_model = os.getenv("NINEROUTER_MODEL", "9router")
        nr_key = os.getenv("NINEROUTER_API_KEY", "sk-9router")
        
        log.info(f"Menggunakan 9Router: {nr_model} ({nr_url})")
        llm = ChatOpenAI(
            base_url=nr_url,
            api_key=nr_key,
            model=nr_model,
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
    category = lead.get("category", "business")
    bio = lead.get("biography", "")
    followers = int(lead.get("follower_count", 0) or 0)
    website_type = lead.get("website_type", "kosong")
    has_phone = bool(lead.get("phone"))
    
    # Determine target language from country code
    country_code = lead.get("country_code", "")
    target_language = get_language_for_country(country_code)

    # Retrieve konteks relevan
    success_context = get_relevant_context(username, category)

    system_prompt = f"""You are an expert sales copywriter and outreach specialist for @dripcodedev (Dripcode), a premium web development agency.

Your task is to write a highly personalized, conversational, and compelling Instagram DM in {target_language} to pitch custom website development services to a local business (SMB).

Core Sales & Negotiation Guidelines (Follow this exact structural flow):
1. Greeting & Introduction: Greet politely (e.g. "Selamat malam/siang Bapak/Ibu..."), apologize for disturbing, and introduce your name 'Didra' from Dripkode.
2. Build Instant Rapport: Genuinely praise their branding consistency, growth, or unique aesthetics to show you're not a generic bot.
3. Observation & Core Hook: Mention you checked their Instagram link-in-bio (Linkfly/Linktree/etc.) and highlight the immense potential of having a dedicated Official Website (Company Profile) as their main information hub.
4. Value Proposition: Explain how an official website boosts credibility (especially for investors/partners), consolidates catalogs/locations/contacts professionally, and protects their brand on search engines (SEO) for the long run.
5. Risk-Free Soft CTA (Mockup Offer): Offer a quick, simple custom visual draft mockup of their website concept designed by Dripcode. Ask for permission to send it over for free as an internal reference.
6. Closing: Thank them politely and wish them success.

Reference Outreach Template (Use this exact structural reference and tone, which is approx 950 chars):
"Selamat malam Bapak/Ibu, mohon maaf mengganggu waktunya. Salam kenal, saya Didra dari Dripkode. Saya sangat mengagumi konsistensi branding dan pesatnya pertumbuhan bisnis Bapak/Ibu belakangan ini. Saat mengunjungi tautan Linkfly di profil Instagram bisnis Bapak/Ibu, kami melihat potensi yang sangat besar jika Bapak/Ibu memiliki Official Website (Company Profile) mandiri sebagai pusat informasi utamanya. Keberadaan website mandiri ini akan sangat efektif untuk meningkatkan kredibilitas brand, terutama di mata calon investor atau mitra. Selain itu, website dapat menyatukan informasi katalog menu, lokasi cabang, dan kontak dalam satu halaman berdesain profesional, sekaligus mengamankan identitas brand di mesin pencari untuk jangka panjang. Kebetulan kami di Dripkode baru saja merancang draf visual sederhana konsep website yang cocok dengan karakter bisnis Bapak/Ibu. Jika Bapak/Ibu berkenan, bolehkah saya mengirimkan draf visual tersebut di sini? Sifatnya gratis, murni untuk referensi tim Bapak/Ibu saja. Terima kasih banyak atas perhatiannya. Sukses selalu untuk bisnis Bapak/Ibu."

Rules:
1. NEVER include or reference dummy usernames starting with '@osm_' (e.g., @osm_4830378537). Instead, address the business by its real name.
2. DO NOT use double quotes to wrap the entire message.
3. Output ONLY the raw DM text itself, without any explanations, pleasantries, introductory labels, or quotes.
4. Maintain a warm, polite, and highly professional Indonesian business tone.
5. The ENTIRE message MUST be written in {target_language}."""

    user_prompt = f"""Draft a personalized Instagram DM for this business:

BUSINESS PROFILE:
- Business Name: {full_name}
- Category: {category}
- Info / Bio / Location: "{bio}"
- Website Status: {website_type} ({"currently has no website" if website_type in ["kosong", "marketplace", "linkinbio"] else "already has a website"})
- Country: {country_code}

Write a short, engaging, and personalized outreach DM in {target_language} addressed to the owner of {full_name} to start a friendly business conversation."""

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
def run(limit: int = 0, min_score: int = 60, test_mode: bool = False):
    """Jalankan RAG DM campaign."""
    print("\n" + "=" * 55)
    print("  RAG-POWERED DM GENERATOR UNTUK UMKM")
    if test_mode:
        print("  [MODE TEST - Tidak kirim DM sungguhan]")
    print("=" * 55)

    # Load leads dari db_helper (Firebase atau fallback CSV lokal)
    import db_helper
    raw_leads = db_helper.get_leads()
    if not raw_leads:
        print("[ERROR] Tidak ada data leads di database atau folder output. Jalankan scraper dahulu.")
        return

    leads = []
    for row in raw_leads:
        try:
            score = int(row.get("lead_score", row.get("score", 0)) or 0)
            if score >= min_score:
                leads.append(row)
        except (ValueError, TypeError):
            continue

    sent = load_sent_usernames()
    pending = [l for l in leads if l.get("username") not in sent]
    to_process = pending if limit <= 0 else pending[:limit]

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
                session_file = BASE_DIR / "session.json"
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

            ig_url = lead.get("instagram_url", "")
            if not ig_url and not uname.startswith("osm_"):
                ig_url = f"https://instagram.com/{uname}"

            row_data = lead.copy()
            row_data["pesan_dm_rag"] = dm_text
            row_data["instagram_url"] = ig_url
            row_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            drafts_created.append(row_data)

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

    # Simpan hasil draf ke db_helper jika ada draf yang dibuat
    if drafts_created:
        try:
            import db_helper
            city = to_process[0].get("city", "Ciwidey") if to_process else "Ciwidey"
            # Load existing drafts
            existing_drafts = db_helper.get_drafts()
            
            # Merge new drafts into existing drafts (prevent duplicates by username)
            merged_drafts = {d.get("username"): d for d in existing_drafts if d.get("username")}
            for new_d in drafts_created:
                username = new_d.get("username")
                if username:
                    new_d.setdefault("city", city)
                    new_d.setdefault("status_dm", "belum_terkirim")
                    new_d.setdefault("status_email", "belum_terkirim")
                    merged_drafts[username] = new_d
                    
            db_helper.save_drafts(list(merged_drafts.values()), city)
            print(f"\n[OK] Draf pesan berhasil disimpan via db_helper.")
        except Exception as e:
            print(f"\n[WARNING] Gagal menyimpan draf via db_helper: {e}")

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
    parser.add_argument("--limit", type=int, default=0,
                        help="Jumlah DM yang diproses (default: 0 untuk semua)")
    parser.add_argument("--min-score", type=int, default=60,
                        help="Minimum lead score (default: 60)")
    args = parser.parse_args()

    if args.index:
        print("Indexing leads ke ChromaDB...")
        count = index_leads_to_vectordb()
        print(f"[OK] {count} leads berhasil di-index!")
    else:
        run(limit=args.limit, min_score=args.min_score, test_mode=args.test)

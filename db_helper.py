import os
import re
import csv
import glob
import logging
from pathlib import Path
from datetime import datetime

# Konfigurasi Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("db_helper")

CRED_PATH = Path("firebase-credentials.json")
if not CRED_PATH.exists():
    CRED_PATH = Path("firebase-credentials.json.json")

db_client = None
use_firebase = False

def init_db():
    """Inisialisasi koneksi Firebase Firestore client secara aman."""
    global db_client, use_firebase
    if db_client is not None:
        return db_client
        
    if CRED_PATH.exists():
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            
            # Cegah re-inisialisasi app yang sama
            if not firebase_admin._apps:
                cred = credentials.Certificate(str(CRED_PATH))
                firebase_admin.initialize_app(cred)
                
            db_client = firestore.client()
            use_firebase = True
            log.info("🔥 Google Firebase Cloud Firestore Berhasil Terkoneksi!")
        except Exception as e:
            log.error(f"⚠️ Gagal menghubungkan ke Firebase: {e}. Menggunakan fallback lokal CSV.")
            use_firebase = False
            db_client = None
    else:
        log.info("ℹ️ File 'firebase-credentials.json' tidak ditemukan. Menggunakan penyimpanan lokal CSV.")
        use_firebase = False
        db_client = None
        
    return db_client

def sanitize_doc_id(city, business_name):
    """Membersihkan teks agar menjadi Document ID Firestore yang valid."""
    raw = f"{city}_{business_name}"
    # Ganti spasi dengan underscore, hapus karakter non-alphanumeric/non-underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', raw.lower().replace(' ', '_'))
    return sanitized or "unnamed_document"

# Initialize immediately
init_db()

# ==========================================
# 1. LEADS OPERATIONS
# ==========================================

def save_leads(leads, city):
    """Menyimpan list of dict leads ke Firebase Firestore atau lokal CSV."""
    init_db()
    if use_firebase and db_client:
        try:
            batch = db_client.batch()
            for lead in leads:
                doc_id = sanitize_doc_id(city, lead.get("full_name", "unnamed"))
                doc_ref = db_client.collection("leads").document(doc_id)
                
                # Konversi data mentah agar kompatibel dengan Firestore
                lead_data = {
                    "city": city,
                    "business_name": lead.get("full_name", ""),
                    "username": lead.get("username", ""),
                    "phone": lead.get("phone", ""),
                    "email": lead.get("email", ""),
                    "address": lead.get("address", ""),
                    "category": lead.get("category", ""),
                    "instagram_url": lead.get("instagram_url", ""),
                    "external_url": lead.get("external_url", ""),
                    "score": int(lead.get("score", 0)),
                    "latitude": float(lead.get("latitude", 0.0)) if lead.get("latitude") else 0.0,
                    "longitude": float(lead.get("longitude", 0.0)) if lead.get("longitude") else 0.0,
                    "created_at": datetime.now()
                }
                batch.set(doc_ref, lead_data)
            batch.commit()
            log.info(f"💾 Berhasil menyimpan {len(leads)} leads ke Firebase Firestore (Collection: 'leads')")
            return "firebase"
        except Exception as e:
            log.error(f"⚠️ Gagal menyimpan ke Firebase, beralih ke lokal: {e}")
            
    # Fallback lokal CSV
    Path("output").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = Path(f"output/umkm_leads_{city.lower()}_{timestamp}.csv")
    
    if not leads:
        return str(filename)
        
    fieldnames = list(leads[0].keys())
    # Pastikan latitude & longitude ada di fieldnames
    for col in ["latitude", "longitude"]:
        if col not in fieldnames:
            fieldnames.append(col)
            
    try:
        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(leads)
        log.info(f"💾 Berhasil menyimpan {len(leads)} leads ke file lokal: {filename}")
        return str(filename)
    except Exception as e:
        log.error(f"⚠️ Gagal menulis CSV lokal: {e}")
        return None

def get_leads(city=None):
    """Membaca data leads dari Firebase Firestore atau file lokal CSV terbaru."""
    init_db()
    if use_firebase and db_client:
        try:
            query = db_client.collection("leads")
            if city:
                query = query.where("city", "==", city)
            docs = query.stream()
            leads = []
            for doc in docs:
                data = doc.to_dict()
                # Petakan kembali struktur agar kompatibel dengan script lama
                lead = {
                    "full_name": data.get("business_name", ""),
                    "username": data.get("username", ""),
                    "phone": data.get("phone", ""),
                    "email": data.get("email", ""),
                    "address": data.get("address", ""),
                    "category": data.get("category", ""),
                    "instagram_url": data.get("instagram_url", ""),
                    "external_url": data.get("external_url", ""),
                    "score": data.get("score", 0),
                    "latitude": data.get("latitude", 0.0),
                    "longitude": data.get("longitude", 0.0)
                }
                leads.append(lead)
            return leads
        except Exception as e:
            log.error(f"⚠️ Gagal membaca dari Firebase, mencoba file lokal: {e}")
            
    # Fallback lokal CSV (cari yang paling baru)
    pattern = "output/umkm_leads_*.csv"
    csv_files = sorted(glob.glob(pattern), reverse=True)
    if not csv_files:
        return []
        
    # Cari berkas kota yang cocok jika dispesifikasikan
    target_file = None
    if city:
        for f in csv_files:
            if city.lower() in f.lower():
                target_file = f
                break
    if not target_file:
        target_file = csv_files[0]
        
    try:
        leads = []
        with open(target_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                leads.append(dict(row))
        return leads
    except Exception as e:
        log.error(f"⚠️ Gagal membaca berkas CSV lokal: {e}")
        return []

# ==========================================
# 2. DRAFTS OPERATIONS
# ==========================================

def save_drafts(drafts, city):
    """Menyimpan draf pesan promosi AI RAG ke Firebase Firestore atau lokal CSV."""
    init_db()
    if use_firebase and db_client:
        try:
            batch = db_client.batch()
            for draft in drafts:
                # Menggunakan sanitasi kota + nama bisnis sebagai ID agar unik
                doc_id = sanitize_doc_id(city, draft.get("full_name", draft.get("business_name", "unnamed")))
                doc_ref = db_client.collection("drafts").document(doc_id)
                
                draft_data = {
                    "city": city,
                    "business_name": draft.get("full_name", draft.get("business_name", "")),
                    "username": draft.get("username", ""),
                    "phone": draft.get("phone", ""),
                    "email": draft.get("email", ""),
                    "instagram_url": draft.get("instagram_url", ""),
                    "external_url": draft.get("external_url", ""),
                    "pesan_dm_rag": draft.get("pesan_dm_rag", ""),
                    "pesan_email_rag": draft.get("pesan_email_rag", ""),
                    "status_dm": draft.get("status_dm", "belum_terkirim"),
                    "status_email": draft.get("status_email", "belum_terkirim"),
                    "score": int(draft.get("score", 0)) if draft.get("score") else 0,
                    "latitude": float(draft.get("latitude", 0.0)) if draft.get("latitude") else 0.0,
                    "longitude": float(draft.get("longitude", 0.0)) if draft.get("longitude") else 0.0,
                    "created_at": datetime.now()
                }
                batch.set(doc_ref, draft_data)
            batch.commit()
            log.info(f"💾 Berhasil menyimpan {len(drafts)} draf ke Firebase Firestore (Collection: 'drafts')")
            return "firebase"
        except Exception as e:
            log.error(f"⚠️ Gagal menyimpan draf ke Firebase, beralih ke lokal: {e}")
            
    # Fallback lokal CSV
    Path("output").mkdir(exist_ok=True)
    filename = Path("output/rag_dm_drafts.csv")
    if not drafts:
        return str(filename)
        
    fieldnames = list(drafts[0].keys())
    # Tambah status_dm & status_email ke headers jika belum ada
    for col in ["status_dm", "status_email", "latitude", "longitude"]:
        if col not in fieldnames:
            fieldnames.append(col)
            
    try:
        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(drafts)
        log.info(f"💾 Berhasil menyimpan {len(drafts)} draf ke lokal CSV: {filename}")
        return str(filename)
    except Exception as e:
        log.error(f"⚠️ Gagal menulis draf ke CSV: {e}")
        return None

def get_drafts(city=None):
    """Membaca semua draf dari Firebase Firestore atau lokal CSV."""
    init_db()
    if use_firebase and db_client:
        try:
            query = db_client.collection("drafts")
            if city:
                query = query.where("city", "==", city)
            docs = query.stream()
            drafts = []
            for doc in docs:
                data = doc.to_dict()
                draft = {
                    "full_name": data.get("business_name", ""),
                    "business_name": data.get("business_name", ""),
                    "username": data.get("username", ""),
                    "phone": data.get("phone", ""),
                    "email": data.get("email", ""),
                    "instagram_url": data.get("instagram_url", ""),
                    "external_url": data.get("external_url", ""),
                    "pesan_dm_rag": data.get("pesan_dm_rag", ""),
                    "pesan_email_rag": data.get("pesan_email_rag", ""),
                    "status_dm": data.get("status_dm", "belum_terkirim"),
                    "status_email": data.get("status_email", "belum_terkirim"),
                    "score": data.get("score", 0),
                    "latitude": data.get("latitude", 0.0),
                    "longitude": data.get("longitude", 0.0)
                }
                drafts.append(draft)
            return drafts
        except Exception as e:
            log.error(f"⚠️ Gagal membaca draf dari Firebase: {e}")
            
    # Fallback lokal CSV
    filename = Path("output/rag_dm_drafts.csv")
    if not filename.exists():
        # Coba juga rag_dm_drafts_resolved.csv
        filename = Path("output/rag_dm_drafts_resolved.csv")
        if not filename.exists():
            return []
            
    try:
        drafts = []
        with open(filename, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                drafts.append(dict(row))
        return drafts
    except Exception as e:
        log.error(f"⚠️ Gagal membaca CSV draf lokal: {e}")
        return []

def update_draft_status(city, business_name, channel, status):
    """Memperbarui status pengiriman (DM/Email) draf tertentu."""
    init_db()
    if use_firebase and db_client:
        try:
            doc_id = sanitize_doc_id(city, business_name)
            doc_ref = db_client.collection("drafts").document(doc_id)
            
            field = "status_dm" if channel.lower() == "dm" else "status_email"
            doc_ref.update({field: status})
            log.info(f"🔄 Berhasil memperbarui {field} -> '{status}' untuk {business_name} di Firestore.")
            return True
        except Exception as e:
            log.error(f"⚠️ Gagal mengupdate status di Firebase: {e}")
            
    # Fallback lokal CSV (baca, ubah, tulis kembali)
    draft_files = ["output/rag_dm_drafts.csv", "output/rag_dm_drafts_resolved.csv", "output/rag_dm_drafts_resolved2.csv"]
    updated_any = False
    
    for filename in draft_files:
        filepath = Path(filename)
        if not filepath.exists():
            continue
            
        try:
            rows = []
            fieldnames = []
            with open(filepath, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    match_name = row.get("full_name", row.get("business_name", ""))
                    if match_name.lower().strip() == business_name.lower().strip():
                        col_name = "status_dm" if channel.lower() == "dm" else "status_email"
                        if col_name in row:
                            row[col_name] = status
                            updated_any = True
                    rows.append(row)
            
            if updated_any:
                with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                log.info(f"🔄 Berhasil memperbarui status {channel} -> '{status}' di berkas lokal {filename}.")
        except Exception as e:
            log.error(f"⚠️ Gagal mengupdate file lokal {filename}: {e}")
            
    return updated_any

# ==========================================
# 3. CAMPAIGN LOGS OPERATIONS
# ==========================================

def save_campaign_log(campaign_type, recipient, status, response_details=""):
    """Menyimpan log pengiriman DM atau Email."""
    init_db()
    if use_firebase and db_client:
        try:
            db_client.collection("campaign_logs").add({
                "campaign_type": campaign_type,
                "recipient": recipient,
                "status": status,
                "response_details": response_details,
                "created_at": datetime.now()
            })
            log.info(f"💾 Log pengiriman {campaign_type} ke {recipient} disimpan di Firestore.")
            return True
        except Exception as e:
            log.error(f"⚠️ Gagal menulis log kampanye ke Firebase: {e}")
            
    # Fallback lokal CSV
    Path("output").mkdir(exist_ok=True)
    filename = Path(f"output/{campaign_type}_sent_log.csv")
    
    file_exists = filename.exists()
    fieldnames = ["timestamp", "recipient", "status", "response_details"]
    
    try:
        with open(filename, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "recipient": recipient,
                "status": status,
                "response_details": response_details
            })
        log.info(f"💾 Log pengiriman {campaign_type} disimpan ke lokal {filename}.")
        return True
    except Exception as e:
        log.error(f"⚠️ Gagal menyimpan log lokal: {e}")
        return False

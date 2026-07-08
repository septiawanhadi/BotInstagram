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
                doc_id = sanitize_doc_id(city, lead.get("full_name", lead.get("business_name", "unnamed")))
                doc_ref = db_client.collection("leads").document(doc_id)
                
                # Salin seluruh field dinamis agar tidak ada kolom yang terpotong
                lead_data = {}
                for k, v in lead.items():
                    if k == "":
                        continue
                    if v is None:
                        lead_data[k] = ""
                    elif isinstance(v, (int, float)):
                        lead_data[k] = v
                    elif isinstance(v, str):
                        if v.lower() == "true":
                            lead_data[k] = True
                        elif v.lower() == "false":
                            lead_data[k] = False
                        elif v.isdigit():
                            lead_data[k] = int(v)
                        else:
                            try:
                                lead_data[k] = float(v)
                            except ValueError:
                                lead_data[k] = v
                    else:
                        lead_data[k] = str(v)
                
                # Pastikan field wajib ada
                lead_data["city"] = city
                lead_data["created_at"] = datetime.now()
                
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
                # Hapus created_at agar tidak error saat Flask melakukan JSON serialization
                if "created_at" in data:
                    del data["created_at"]
                
                # Kompatibilitas field nama bisnis lama
                if "business_name" in data and "full_name" not in data:
                    data["full_name"] = data["business_name"]
                elif "full_name" in data and "business_name" not in data:
                    data["business_name"] = data["full_name"]
                    
                leads.append(data)
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
                doc_id = sanitize_doc_id(city, draft.get("full_name", draft.get("business_name", "unnamed")))
                doc_ref = db_client.collection("drafts").document(doc_id)
                
                draft_data = {}
                for k, v in draft.items():
                    if k == "":
                        continue
                    if v is None:
                        draft_data[k] = ""
                    elif isinstance(v, (int, float)):
                        draft_data[k] = v
                    elif isinstance(v, str):
                        if v.lower() == "true":
                            draft_data[k] = True
                        elif v.lower() == "false":
                            draft_data[k] = False
                        elif v.isdigit():
                            draft_data[k] = int(v)
                        else:
                            try:
                                draft_data[k] = float(v)
                            except ValueError:
                                draft_data[k] = v
                    else:
                        draft_data[k] = str(v)
                        
                draft_data["city"] = city
                draft_data["created_at"] = datetime.now()
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
                if "created_at" in data:
                    del data["created_at"]
                
                if "business_name" in data and "full_name" not in data:
                    data["full_name"] = data["business_name"]
                elif "full_name" in data and "business_name" not in data:
                    data["business_name"] = data["full_name"]
                    
                drafts.append(data)
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

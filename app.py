"""
app.py
Flask Web Backend untuk UMKM Scraper & RAG DM Campaign Dashboard
"""
import os
import sys
import csv
import glob
import re
import time
import smtplib
import subprocess
import threading
import logging
import requests as http_requests
from pathlib import Path
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, render_template, jsonify, request
try:
    from flask_cors import CORS
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "flask-cors"], check=True)
    from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv(override=True)

# Konfigurasi Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("web-app")

app = Flask(__name__)
CORS(app)

# Status Eksekusi Global
process_status = {
    "is_running": False,
    "current_script": None,
    "exit_code": None,
    "log_output": []
}

process_lock = threading.Lock()
current_subprocess = None

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_latest_csv(pattern: str) -> Optional[Path]:
    """Cari file CSV terbaru berdasarkan pola file di folder output."""
    files = glob.glob(f"output/{pattern}")
    if not files:
        return None
    # Urutkan berdasarkan waktu modifikasi terbaru
    latest_file = max(files, key=os.path.getmtime)
    return Path(latest_file)

def run_script_worker(command: list[str], script_name: str):
    """Worker Thread untuk menjalankan script Python dan merekam output log."""
    global process_status, current_subprocess
    
    with process_lock:
        process_status["is_running"] = True
        process_status["current_script"] = script_name
        process_status["exit_code"] = None
        process_status["log_output"] = []

    log.info(f"Memulai eksekusi script: {' '.join(command)}")
    
    try:
        # Jalankan process di direktori script berada
        project_dir = os.path.abspath(os.path.dirname(__file__))
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        p = subprocess.Popen(
            command,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=env
        )
        current_subprocess = p
        
        # Baca output baris demi baris secara real-time
        for line in iter(p.stdout.readline, ""):
            line_str = line.rstrip()
            if line_str:
                with process_lock:
                    process_status["log_output"].append(line_str)
                    # Batasi log agar tidak membebani memori
                    if len(process_status["log_output"]) > 1000:
                        process_status["log_output"].pop(0)
                        
        p.stdout.close()
        return_code = p.wait()
        
        with process_lock:
            process_status["exit_code"] = return_code
            process_status["log_output"].append(f"\n--- PROSES SELESAI DENGAN EXIT CODE: {return_code} ---")
            
    except Exception as e:
        with process_lock:
            process_status["exit_code"] = -1
            process_status["log_output"].append(f"[ERROR WEB SYSTEM] Gagal menjalankan script: {e}")
            
    finally:
        with process_lock:
            process_status["is_running"] = False
            current_subprocess = None
        log.info(f"Eksekusi script '{script_name}' selesai.")


# ============================================================
# API ENDPOINTS
# ============================================================

@app.route("/")
def index():
    """Halaman Utama Dashboard."""
    return render_template("index.html")

@app.route("/api/stats")
def stats():
    """Membaca statistik performa dari output folder dan log."""
    # 1. Hitung total leads dari OSM terbaru
    osm_file = get_latest_csv("umkm_leads_*.csv")
    total_leads = 0
    high_score_leads = 0
    if osm_file and osm_file.exists():
        try:
            with open(osm_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_leads += 1
                    try:
                        score = int(row.get("lead_score", 0) or 0)
                        if score >= 60:
                            high_score_leads += 1
                    except ValueError:
                        pass
        except Exception as e:
            log.error(f"Gagal membaca file osm: {e}")

    # 2. Hitung draf yang berhasil di-resolve
    draft_file = Path("output/rag_dm_drafts_resolved.csv")
    if not draft_file.exists():
        draft_file = Path("output/rag_dm_drafts.csv")
        
    total_drafts = 0
    resolved_drafts = 0
    if draft_file.exists():
        try:
            with open(draft_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_drafts += 1
                    username = row.get("username", "")
                    if username and not username.startswith("osm_"):
                        resolved_drafts += 1
        except Exception as e:
            log.error(f"Gagal membaca file draf: {e}")

    # 3. Hitung status DM dikirim
    sent_log = Path("output/dm_sent_log.csv")
    dm_sent = 0
    dm_failed = 0
    dm_skipped = 0
    if sent_log.exists():
        try:
            with open(sent_log, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = row.get("status")
                    if status == "sent":
                        dm_sent += 1
                    elif status == "failed":
                        dm_failed += 1
                    elif status in ["skipped_dummy", "skipped"]:
                        dm_skipped += 1
        except Exception as e:
            log.error(f"Gagal membaca log sent: {e}")

    # 4. Hitung status Email dikirim
    email_log = Path("output/email_sent_log.csv")
    email_sent = 0
    email_failed = 0
    if email_log.exists():
        try:
            with open(email_log, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = row.get("status")
                    if status == "sent":
                        email_sent += 1
                    elif status == "failed":
                        email_failed += 1
        except Exception as e:
            log.error(f"Gagal membaca log email_sent: {e}")

    return jsonify({
        "total_leads": total_leads,
        "high_score_leads": high_score_leads,
        "total_drafts": total_drafts,
        "resolved_drafts": resolved_drafts,
        "dm_sent": dm_sent,
        "dm_failed": dm_failed,
        "dm_skipped": dm_skipped,
        "email_sent": email_sent,
        "email_failed": email_failed,
        "active_leads_file": osm_file.name if osm_file else "None",
        "active_drafts_file": draft_file.name if draft_file.exists() else "None"
    })

@app.route("/api/env", methods=["GET", "POST"])
def manage_env():
    """Membaca dan memperbarui konfigurasi .env."""
    env_file = Path(".env")
    
    if request.method == "POST":
        data = request.json or {}
        try:
            # Baca file .env lama untuk melestarikan komentar
            lines = []
            if env_file.exists():
                with open(env_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            
            # Buat kamus untuk melacak key mana yang sudah diupdate
            updated_keys = set()
            new_lines = []
            
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in data:
                        new_lines.append(f"{key}={data[key]}\n")
                        updated_keys.add(key)
                        continue
                new_lines.append(line)
                
            # Tambahkan kunci baru yang belum ada di file lama
            for key, val in data.items():
                if key not in updated_keys:
                    new_lines.append(f"{key}={val}\n")
            
            # Tulis kembali
            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
                
            # Paksa python-dotenv me-reload file .env yang baru ditulis
            load_dotenv(override=True)
            return jsonify({"status": "success", "message": "Konfigurasi .env berhasil disimpan!"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Gagal menyimpan file .env: {e}"}), 500
            
    # GET METHOD
    env_data = {}
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        parts = stripped.split("=", 1)
                        env_data[parts[0].strip()] = parts[1].strip()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Gagal membaca file .env: {e}"}), 500
            
    # Return default template values jika kosong
    default_keys = [
        "IG_USERNAME", "IG_PASSWORD", "IG_SESSIONID", 
        "AI_TYPE", "GEMINI_API_KEY", "GEMINI_MODEL",
        "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
        "LOCAL_LLM_URL", "LOCAL_LLM_MODEL",
        "NINEROUTER_URL", "NINEROUTER_MODEL", "NINEROUTER_API_KEY",
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM_NAME",
        "EMAIL_SERVICE_TYPE", "HOSTINGER_API_TOKEN"
    ]
    for key in default_keys:
        if key not in env_data:
            env_data[key] = ""
            
    return jsonify(env_data)

@app.route("/api/drafts", methods=["GET", "POST"])
def get_drafts():
    """Membaca dan memperbarui isi draf pesan kustom RAG AI di tabel editor."""
    draft_file = Path("output/rag_dm_drafts_resolved.csv")
    if not draft_file.exists():
        draft_file = Path("output/rag_dm_drafts.csv")
        
    if not draft_file.exists():
        return jsonify({"status": "empty", "drafts": [], "message": "File draf belum dibuat. Jalankan generator terlebih dahulu."})

    if request.method == "POST":
        data = request.json or {}
        updated_username = data.get("old_username")
        new_username = data.get("new_username")
        new_message = data.get("message")
        
        if not updated_username:
            return jsonify({"status": "error", "message": "Parameter old_username wajib disertakan."}), 400

        try:
            # Baca seluruh isi CSV ke memori
            rows = []
            fieldnames = []
            with open(draft_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    if row.get("username") == updated_username:
                        if new_username:
                            row["username"] = new_username
                            if not new_username.startswith("osm_"):
                                row["instagram_url"] = f"https://instagram.com/{new_username}"
                            else:
                                row["instagram_url"] = ""
                        if new_message is not None:
                            row["pesan_dm_rag"] = new_message
                    rows.append(row)
            
            # Tulis ulang kembali ke file CSV
            with open(draft_file, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                
            return jsonify({"status": "success", "message": "Perubahan draf berhasil disimpan!"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Gagal mengupdate draf: {e}"}), 500

    # GET METHOD
    drafts = []
    try:
        with open(draft_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                drafts.append(row)
        return jsonify({
            "status": "success", 
            "file_name": draft_file.name,
            "drafts": drafts
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal membaca file draf: {e}"}), 500

@app.route("/api/run", methods=["POST"])
def run_script():
    """Memicu eksekusi salah satu script Python di background thread."""
    global process_status
    
    if process_status["is_running"]:
        return jsonify({
            "status": "error", 
            "message": f"Script '{process_status['current_script']}' sedang berjalan. Harap tunggu hingga selesai."
        }), 400
        
    data = request.json or {}
    script = data.get("script")
    args = data.get("args", [])
    
    # Map script ke file executable lokal
    script_map = {
        "scraper": "osm_scraper.py",
        "generator": "rag_dm_generator.py",
        "resolver": "resolve_ig_usernames.py",
        "dm_sender": "dm_sender.py",
        "email_sender": "email_sender.py"
    }
    
    if script not in script_map:
        return jsonify({"status": "error", "message": f"Script '{script}' tidak valid."}), 400
        
    target_file = script_map[script]
    
    # Susun command eksekusi
    # Gunakan python interpreter lokal yang sama dengan server Flask
    command = [sys.executable, target_file] + args
    
    # Jalankan di thread asinkron
    t = threading.Thread(target=run_script_worker, args=(command, script))
    t.daemon = True
    t.start()
    
    return jsonify({
        "status": "success", 
        "message": f"Script '{script}' berhasil dijalankan di background.",
        "command": " ".join(command)
    })

@app.route("/api/run/status")
def run_status():
    """Mengecek status eksekusi terminal log console saat ini."""
    with process_lock:
        return jsonify({
            "is_running": process_status["is_running"],
            "current_script": process_status["current_script"],
            "exit_code": process_status["exit_code"],
            "log_lines": process_status["log_output"]
        })

@app.route("/api/run/stop", methods=["POST"])
def run_stop():
    """Menghentikan paksa script yang sedang berjalan (Kill Task)."""
    global current_subprocess
    if current_subprocess:
        try:
            current_subprocess.kill()
            log.warning("Proses dihentikan paksa oleh pengguna.")
            return jsonify({"status": "success", "message": "Proses berhasil dihentikan secara paksa!"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Gagal menghentikan proses: {e}"}), 500
    return jsonify({"status": "info", "message": "Tidak ada proses aktif yang sedang berjalan."})


@app.route("/api/leads")
def get_leads():
    """Return merged leads data from db_helper (Firebase or local CSV)."""
    import db_helper
    
    # 1. Load leads from db_helper
    leads = db_helper.get_leads()
    leads_data = {}
    
    for lead in leads:
        username = lead.get("username", "")
        if not username:
            continue
        leads_data[username] = dict(lead)
        # Set default empty fields
        leads_data[username].setdefault("pesan_dm_rag", "")
        leads_data[username].setdefault("pesan_email_rag", "")
        leads_data[username].setdefault("dm_status", "pending")
        leads_data[username].setdefault("email_status", "pending")
        
    # 2. Overlay drafts from db_helper
    drafts = db_helper.get_drafts()
    for draft in drafts:
        username = draft.get("username", "")
        if not username:
            continue
        if username in leads_data:
            leads_data[username]["pesan_dm_rag"] = draft.get("pesan_dm_rag", "")
            leads_data[username]["pesan_email_rag"] = draft.get("pesan_email_rag", "")
            if draft.get("status_dm"):
                leads_data[username]["dm_status"] = draft.get("status_dm")
            if draft.get("status_email"):
                leads_data[username]["email_status"] = draft.get("status_email")
            if not leads_data[username].get("instagram_url"):
                leads_data[username]["instagram_url"] = draft.get("instagram_url", "")
        else:
            # Lead only in drafts
            leads_data[username] = dict(draft)
            leads_data[username].setdefault("dm_status", draft.get("status_dm", "pending"))
            leads_data[username].setdefault("email_status", draft.get("status_email", "pending"))
            
    # Return dynamic file names for compatibility
    use_fb = db_helper.use_firebase
    return jsonify({
        "status": "success",
        "leads_file": "Firebase Cloud Firestore" if use_fb else "Lokal CSV",
        "draft_file": "Firebase Cloud Firestore" if use_fb else "Lokal CSV",
        "leads": list(leads_data.values())
    })


@app.route("/api/leads/send-email", methods=["POST"])
def leads_send_email():
    """Send a single cold email to one lead using SMTP or Hostinger API."""
    data = request.json or {}
    username = data.get("username", "")
    email_addr = data.get("email", "").strip()
    full_name = data.get("full_name", username)
    message = data.get("message", "").strip()

    if not email_addr or "@" not in email_addr:
        return jsonify({"status": "error", "message": "Alamat email tidak valid."}), 400
    if not message:
        return jsonify({"status": "error", "message": "Draf pesan kosong — hasilkan draft terlebih dahulu."}), 400

    service_type = os.getenv("EMAIL_SERVICE_TYPE", "smtp").lower()
    from_name = os.getenv("SMTP_FROM_NAME", "DripCode Web Development")
    subject = f"Website Professional untuk {full_name} — DripCode"

    # Build HTML from email_sender module
    try:
        from email_sender import build_html_template
        html_body = build_html_template(full_name, message)
    except Exception:
        html_body = f"<p>{message.replace(chr(10), '<br>')}</p>"

    try:
        if service_type == "hostinger":
            hostinger_token = os.getenv("HOSTINGER_API_TOKEN")
            if not hostinger_token:
                return jsonify({"status": "error", "message": "HOSTINGER_API_TOKEN belum diisi di .env"}), 500

            headers_h = {
                "Authorization": f"Bearer {hostinger_token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            # Get mailbox id
            r_me = http_requests.get("https://api.mail.hostinger.com/api/v1/me", headers=headers_h, timeout=15)
            r_me.raise_for_status()
            mailboxes = r_me.json().get("data", {}).get("mailboxes", [])
            if not mailboxes:
                return jsonify({"status": "error", "message": "Tidak ada mailbox aktif di Hostinger."}), 500
            mailbox_id = mailboxes[0].get("resourceId")

            payload = {"to": [email_addr], "displayName": from_name, "subject": subject, "text": message, "html": html_body}
            r_send = http_requests.post(f"https://api.mail.hostinger.com/api/v1/mailboxes/{mailbox_id}/send",
                                         json=payload, headers=headers_h, timeout=25)
            if r_send.status_code not in [200, 204]:
                raise Exception(f"Hostinger API {r_send.status_code}: {r_send.text}")
        else:
            smtp_host = os.getenv("SMTP_HOST")
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_user = os.getenv("SMTP_USER")
            smtp_pass = os.getenv("SMTP_PASS")
            if not smtp_host or not smtp_user or not smtp_pass:
                return jsonify({"status": "error", "message": "Konfigurasi SMTP tidak lengkap di .env"}), 500

            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.starttls()
            server.login(smtp_user, smtp_pass)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{from_name} <{smtp_user}>"
            msg["To"] = email_addr
            msg.attach(MIMEText(message, "plain"))
            msg.attach(MIMEText(html_body, "html"))
            server.sendmail(smtp_user, email_addr, msg.as_string())
            server.quit()

        # Log the sent email via db_helper
        import db_helper
        db_helper.save_campaign_log("email", email_addr, "sent", f"To: {full_name}")
        # Cari data kota lead untuk penentuan ID Firestore
        leads = db_helper.get_leads()
        city = "Ciwidey"
        for l in leads:
            if l.get("username") == username:
                city = l.get("city", "Ciwidey")
                break
        db_helper.update_draft_status(city, full_name, "email", "sent")

        return jsonify({"status": "sent", "message": f"Email berhasil dikirim ke {email_addr}"})

    except Exception as e:
        # Log failed attempt via db_helper
        try:
            import db_helper
            db_helper.save_campaign_log("email", email_addr, "failed", str(e)[:200])
            # Cari data kota lead
            leads = db_helper.get_leads()
            city = "Ciwidey"
            for l in leads:
                if l.get("username") == username:
                    city = l.get("city", "Ciwidey")
                    break
            db_helper.update_draft_status(city, full_name, "email", "failed")
        except Exception:
            pass
        return jsonify({"status": "error", "message": f"Gagal mengirim email: {e}"}), 500


@app.route("/api/leads/send-dm", methods=["POST"])
def leads_send_dm():
    """Kirim single DM ke lead tertentu menggunakan instagrapi."""
    data = request.json or {}
    username = data.get("username", "")
    message = data.get("message", "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Parameter username wajib."}), 400
    if not message:
        return jsonify({"status": "error", "message": "Pesan DM kosong."}), 400

    try:
        from instagrapi import Client
    except ImportError:
        return jsonify({"status": "error", "message": "instagrapi belum di-install."}), 500

    ig_user = os.getenv("IG_USERNAME")
    ig_pass = os.getenv("IG_PASSWORD")
    sessionid = os.getenv("IG_SESSIONID")

    if not sessionid and (not ig_user or not ig_pass):
        return jsonify({"status": "error", "message": "Kredensial Instagram tidak lengkap di .env"}), 400

    try:
        cl = Client()
        session_file = Path("session.json")
        # Try loading session
        if sessionid and sessionid != "isi_session_id_browser_anda_disini":
            try:
                cl.login_by_sessionid(sessionid)
                cl.username = ig_user or "user"
            except Exception as e:
                log.warning(f"Bypass session failed: {e}, falling back to regular login")
                if session_file.exists():
                    try:
                        cl.load_settings(session_file)
                        cl.login(ig_user, ig_pass)
                    except Exception:
                        cl.login(ig_user, ig_pass)
                        cl.dump_settings(session_file)
                else:
                    cl.login(ig_user, ig_pass)
                    cl.dump_settings(session_file)
        else:
            if session_file.exists():
                try:
                    cl.load_settings(session_file)
                    cl.login(ig_user, ig_pass)
                except Exception:
                    cl.login(ig_user, ig_pass)
                    cl.dump_settings(session_file)
            else:
                cl.login(ig_user, ig_pass)
                cl.dump_settings(session_file)

        # Resolve user ID and send DM
        user_id = cl.user_id_from_username(username)
        cl.direct_send(message, [user_id])

        # Cari data kota & nama bisnis lead
        import db_helper
        leads = db_helper.get_leads()
        city = "Ciwidey"
        business_name = username
        for l in leads:
            if l.get("username") == username:
                city = l.get("city", "Ciwidey")
                business_name = l.get("full_name", l.get("business_name", username))
                break

        # Log direct result
        from dm_sender import log_dm_result
        log_dm_result(username, "sent", message, city, business_name)

        return jsonify({"status": "sent", "message": f"DM berhasil dikirim ke @{username}"})

    except Exception as e:
        # Log failure
        try:
            import db_helper
            leads = db_helper.get_leads()
            city = "Ciwidey"
            business_name = username
            for l in leads:
                if l.get("username") == username:
                    city = l.get("city", "Ciwidey")
                    business_name = l.get("full_name", l.get("business_name", username))
                    break
            from dm_sender import log_dm_result
            log_dm_result(username, "failed", str(e), city, business_name)
        except Exception:
            pass
        return jsonify({"status": "error", "message": f"Gagal mengirim DM: {e}"}), 500


@app.route("/api/leads/generate-draft", methods=["POST"])
def leads_generate_draft():
    """Generate an AI-personalized DM draft for a single lead and save it to the drafts CSV."""
    data = request.json or {}
    username = data.get("username", "")
    if not username:
        return jsonify({"status": "error", "message": "Parameter username wajib."}), 400

    # Build lead dict from request (avoids re-reading CSVs in the AI call)
    lead = {
        "username": username,
        "full_name": data.get("full_name", username),
        "category": data.get("category", "business"),
        "biography": data.get("biography", ""),
        "follower_count": data.get("follower_count", 0),
        "website_type": data.get("website_type", "kosong"),
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
        "country_code": data.get("country_code", ""),
        "city": data.get("city", ""),
    }

    try:
        from rag_dm_generator import generate_personalized_dm
        draft_text = generate_personalized_dm(lead)
    except Exception as e:
        return jsonify({"status": "error", "message": f"AI generator error: {e}"}), 500

    # Save the generated draft to the db_helper
    try:
        import db_helper
        drafts = db_helper.get_drafts()
        found = False
        city = lead.get("city", "Ciwidey") or "Ciwidey"
        
        # update draft in the list
        for d in drafts:
            if d.get("username") == username:
                d["pesan_dm_rag"] = draft_text
                found = True
                break
                
        if not found:
            new_draft = {
                "business_name": lead.get("full_name", username),
                "username": username,
                "city": city,
                "phone": lead.get("phone", ""),
                "email": lead.get("email", ""),
                "pesan_dm_rag": draft_text,
                "pesan_email_rag": "",
                "status_dm": "belum_terkirim",
                "status_email": "belum_terkirim"
            }
            drafts.append(new_draft)
            
        db_helper.save_drafts(drafts, city)
    except Exception as e:
        log.warning(f"Gagal menyimpan draft via db_helper: {e}")

    return jsonify({"status": "success", "draft": draft_text, "username": username})


@app.route("/api/leads/save", methods=["POST"])
def leads_save_row():
    """Save edits (username, DM draft, email draft) for a single lead in the drafts db_helper."""
    data = request.json or {}
    old_username = data.get("old_username", "")
    new_username = data.get("new_username", old_username)
    pesan_dm = data.get("pesan_dm_rag")
    pesan_email = data.get("pesan_email_rag")

    if not old_username:
        return jsonify({"status": "error", "message": "Parameter old_username wajib."}), 400

    try:
        import db_helper
        drafts = db_helper.get_drafts()
        updated = False
        city = "Ciwidey" # Default city fallback
        
        for d in drafts:
            if d.get("username") == old_username:
                d["username"] = new_username
                if not new_username.startswith("osm_"):
                    d["instagram_url"] = f"https://instagram.com/{new_username}"
                else:
                    d["instagram_url"] = ""
                if pesan_dm is not None:
                    d["pesan_dm_rag"] = pesan_dm
                if pesan_email is not None:
                    d["pesan_email_rag"] = pesan_email
                city = d.get("city", "Ciwidey")
                updated = True
                
        if updated:
            db_helper.save_drafts(drafts, city)
            return jsonify({"status": "success", "message": "Draf berhasil disimpan."})
        else:
            return jsonify({"status": "error", "message": "Lead tidak ditemukan."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal menyimpan: {e}"}), 500

if __name__ == "__main__":
    # Buat direktori output jika belum ada
    Path("output").mkdir(exist_ok=True)
    
    # Jalankan server
    port = int(os.environ.get("PORT", 5000))
    print("=======================================================")
    print("  UMKM SCRAPER & RAG BOT DASHBOARD RUNNING")
    print(f"  Buka di browser: http://localhost:{port}")
    print("=======================================================")
    
    app.run(host="0.0.0.0", port=port, debug=False)

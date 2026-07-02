"""
app.py
Flask Web Backend untuk UMKM Scraper & RAG DM Campaign Dashboard
"""
import os
import csv
import glob
import subprocess
import threading
import time
import logging
from pathlib import Path
from typing import Optional
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

# Konfigurasi Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("web-app")

app = Flask(__name__)

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
        p = subprocess.Popen(
            command,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace"
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

    return jsonify({
        "total_leads": total_leads,
        "high_score_leads": high_score_leads,
        "total_drafts": total_drafts,
        "resolved_drafts": resolved_drafts,
        "dm_sent": dm_sent,
        "dm_failed": dm_failed,
        "dm_skipped": dm_skipped,
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
        "LOCAL_LLM_URL", "LOCAL_LLM_MODEL"
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
        "dm_sender": "dm_sender.py"
    }
    
    if script not in script_map:
        return jsonify({"status": "error", "message": f"Script '{script}' tidak valid."}), 400
        
    target_file = script_map[script]
    
    # Susun command eksekusi
    # Gunakan python interpreter lokal
    command = ["python", target_file] + args
    
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

if __name__ == "__main__":
    # Buat direktori output jika belum ada
    Path("output").mkdir(exist_ok=True)
    
    print("=======================================================")
    print("  UMKM SCRAPER & RAG BOT DASHBOARD RUNNING")
    print("  Buka di browser: http://localhost:5000")
    print("=======================================================")
    
    # Jalankan server
    app.run(host="localhost", port=5000, debug=True)

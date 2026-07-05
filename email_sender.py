"""
email_sender.py — Eksekutor Pengiriman Cold Email Massal Otomatis (SMTP)
Membaca file draf RAG dan mengirimkan pesan penawaran terpersonalisasi via Email.
"""
import os
import sys
import csv
import time
import random
import logging
import smtplib
import argparse
import requests
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Paksa terminal Windows menggunakan UTF-8 agar mendukung cetak karakter emoji
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s -- %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("email-sender")

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = str(BASE_DIR / "output" / "email_sent_log.csv")


def get_sent_emails() -> set:
    """Membaca log email terkirim untuk menghindari pengiriman ganda."""
    sent_emails = set()
    if not os.path.exists(LOG_FILE):
        return sent_emails

    try:
        with open(LOG_FILE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "sent" and row.get("email"):
                    sent_emails.add(row["email"].strip().lower())
    except Exception as e:
        log.warning(f"Gagal membaca log pengiriman email: {e}")
    return sent_emails


def log_email_status(username: str, name: str, email: str, status: str, error_msg: str = ""):
    """Mencatat status pengiriman email ke file CSV log."""
    file_exists = os.path.exists(LOG_FILE)
    
    # Pastikan folder output ada
    Path(LOG_FILE).parent.mkdir(exist_ok=True)
    
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "username", "full_name", "email", "status", "error"])
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                username,
                name,
                email,
                status,
                error_msg
            ])
    except Exception as e:
        log.error(f"Gagal menulis log pengiriman email: {e}")


def build_html_template(business_name: str, message_text: str) -> str:
    """Membungkus pesan personal RAG AI dalam template HTML email yang profesional."""
    # Konversi baris baru menjadi tag <br>
    html_message = message_text.replace("\n", "<br>")
    
    from_name = os.getenv("SMTP_FROM_NAME", "DripCode Web Development")
    
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: #1e293b;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            background-color: #f8fafc;
        }}
        .email-wrapper {{
            width: 100%;
            background-color: #f8fafc;
            padding: 20px 0;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }}
        .header {{
            background: linear-gradient(135deg, #4f46e5, #6366f1);
            color: #ffffff;
            padding: 30px 20px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}
        .content {{
            padding: 30px 25px;
            font-size: 15px;
            color: #334155;
        }}
        .footer {{
            background-color: #f1f5f9;
            padding: 20px;
            font-size: 12px;
            color: #64748b;
            text-align: center;
            border-top: 1px solid #e2e8f0;
        }}
        .footer a {{
            color: #4f46e5;
            text-decoration: none;
        }}
        .btn {{
            display: inline-block;
            background-color: #4f46e5;
            color: #ffffff !important;
            padding: 10px 20px;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 600;
            margin-top: 15px;
        }}
    </style>
</head>
<body>
    <div class="email-wrapper">
        <div class="container">
            <div class="header">
                <h1>{from_name}</h1>
            </div>
            <div class="content">
                {html_message}
            </div>
            <div class="footer">
                Pesan ini dikirim khusus untuk <strong>{business_name}</strong>.<br>
                Hubungi kami via WhatsApp atau balas email ini untuk diskusi lebih lanjut.<br>
                &copy; {time.strftime('%Y')} {from_name}. All rights reserved.
            </div>
        </div>
    </div>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="SMTP Cold Email Executer")
    parser.add_argument("--csv", type=str, help="Path ke CSV resolved drafts")
    parser.add_argument("--limit", type=int, default=10, help="Batas jumlah email yang dikirim")
    args = parser.parse_args()

    # Cari file draf CSV secara otomatis jika tidak didefinisikan
    csv_path = args.csv
    if not csv_path:
        csv_path = str(BASE_DIR / "output" / "rag_dm_drafts_resolved.csv")
        if not os.path.exists(csv_path):
            csv_path = str(BASE_DIR / "output" / "rag_dm_drafts.csv")

    if not os.path.exists(csv_path):
        log.error(f"File draf CSV tidak ditemukan di: {csv_path}. Harap jalankan AI RAG Generator terlebih dahulu.")
        sys.exit(1)

    # Tentukan Tipe Email Outreach Service
    service_type = os.getenv("EMAIL_SERVICE_TYPE", "smtp").lower()
    from_name = os.getenv("SMTP_FROM_NAME", "DripCode Web Development")

    if service_type == "hostinger":
        # Gunakan Hostinger Agentic Mail API
        hostinger_token = os.getenv("HOSTINGER_API_TOKEN")
        if not hostinger_token:
            log.error("EMAIL_SERVICE_TYPE disetel ke 'hostinger', tetapi HOSTINGER_API_TOKEN kosong di file .env!")
            sys.exit(1)
            
        headers = {
            "Authorization": f"Bearer {hostinger_token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Ambil mailbox resource ID secara dinamis
        log.info("Mengambil detail mailbox dari Hostinger Agentic Mail API...")
        try:
            r_me = requests.get("https://api.mail.hostinger.com/api/v1/me", headers=headers, timeout=20)
            r_me.raise_for_status()
            me_data = r_me.json()
            mailboxes = me_data.get("data", {}).get("mailboxes", [])
            if not mailboxes:
                log.error("Tidak ditemukan mailbox aktif yang dapat dikelola oleh API token ini.")
                sys.exit(1)
            
            # Gunakan mailbox pertama
            mailbox = mailboxes[0]
            mailbox_id = mailbox.get("resourceId")
            sender_address = mailbox.get("address")
            log.info(f"[OK] Terhubung ke Mailbox: {sender_address} (ID: {mailbox_id})")
        except Exception as e_me:
            log.error(f"Gagal otentikasi ke Hostinger Agentic Mail API: {e_me}")
            sys.exit(1)
    else:
        # Load konfigurasi SMTP dari .env
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port_str = os.getenv("SMTP_PORT", "587")
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASS")

        if not smtp_host or not smtp_user or not smtp_pass:
            log.error("Konfigurasi SMTP belum lengkap di file .env! (Wajib mengisi SMTP_HOST, SMTP_USER, dan SMTP_PASS).")
            sys.exit(1)

        try:
            smtp_port = int(smtp_port_str)
        except ValueError:
            log.error(f"Port SMTP tidak valid: {smtp_port_str}")
            sys.exit(1)

    # Ambil log email yang sudah terkirim sebelumnya
    sent_emails = get_sent_emails()

    # Baca file draf CSV
    leads = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                leads.append(row)
    except Exception as e:
        log.error(f"Gagal membaca file CSV draf: {e}")
        sys.exit(1)

    # Saring leads yang memiliki email valid
    active_leads = []
    for lead in leads:
        email = lead.get("email", "").strip()
        if not email or "@" not in email:
            continue
        
        # Lewati jika sudah pernah dikirimi email sukses
        if email.lower() in sent_emails:
            continue
            
        active_leads.append(lead)

    log.info("=" * 60)
    log.info(f"  EMAIL COLD OUTREACH EXECUTOR ({service_type.upper()})")
    log.info("=" * 60)
    log.info(f"  Total leads draf : {len(leads)}")
    log.info(f"  Sudah di-email   : {len(sent_emails)}")
    log.info(f"  Antrian baru     : {len(active_leads)}")
    log.info(f"  Batas kirim      : {args.limit}")
    log.info("=" * 60)

    if not active_leads:
        log.info("Tidak ada email baru dalam antrian untuk dikirim.")
        sys.exit(0)

    # Ambil sejumlah limit target
    leads_to_process = active_leads[:args.limit]

    # Inisialisasi koneksi server SMTP jika tipe adalah SMTP
    server = None
    if service_type == "smtp":
        log.info(f"Menghubungkan ke server SMTP: {smtp_host}:{smtp_port}...")
        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.starttls()
                
            server.login(smtp_user, smtp_pass)
            log.info("[OK] Berhasil login ke server SMTP!")
        except Exception as e:
            log.error(f"Gagal menghubungkan atau login ke SMTP server: {e}")
            sys.exit(1)

    sent_count = 0
    failed_count = 0

    try:
        for idx, lead in enumerate(leads_to_process, 1):
            username = lead.get("username", "")
            name = lead.get("full_name") or username
            email = lead.get("email", "").strip()
            pesan_dm = lead.get("pesan_dm_rag", "")

            log.info(f"[{idx}/{len(leads_to_process)}] Mengirim email ke {name} ({email})...")

            if not pesan_dm:
                log.warning(f"  -> DILEWATI: Draf pesan kosong.")
                log_email_status(username, name, email, "skipped_empty")
                continue

            try:
                subject = f"Penawaran Jasa Pembuatan Website Professional — {name}"
                text_body = pesan_dm
                html_body = build_html_template(name, pesan_dm)

                if service_type == "hostinger":
                    # Kirim via Hostinger Agentic Mail REST API
                    send_url = f"https://api.mail.hostinger.com/api/v1/mailboxes/{mailbox_id}/send"
                    payload = {
                        "to": [email],
                        "displayName": from_name,
                        "subject": subject,
                        "text": text_body,
                        "html": html_body
                    }
                    
                    r_send = requests.post(send_url, json=payload, headers=headers, timeout=25)
                    # OpenAPI menyatakan 204 No Content adalah sukses
                    if r_send.status_code in [200, 204]:
                        log.info(f"  -> BERHASIL dikirim via Hostinger API ke {email}")
                        log_email_status(username, name, email, "sent")
                        sent_count += 1
                    else:
                        error_text = r_send.text
                        raise Exception(f"Hostinger API returned {r_send.status_code}: {error_text}")
                else:
                    # Kirim via standard SMTP
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = subject
                    msg["From"] = f"{from_name} <{smtp_user}>"
                    msg["To"] = email

                    msg.attach(MIMEText(text_body, "plain"))
                    msg.attach(MIMEText(html_body, "html"))

                    server.sendmail(smtp_user, email, msg.as_string())
                    log.info(f"  -> BERHASIL dikirim via SMTP ke {email}")

                    log_email_status(username, name, email, "sent")
                    sent_count += 1
                
                # Jeda waktu acak 10-20 detik antar email agar tidak ditandai spam
                if idx < len(leads_to_process):
                    delay = random.randint(10, 20)
                    log.info(f"  Menunggu {delay} detik sebelum email berikutnya...")
                    time.sleep(delay)

            except Exception as e_send:
                log.error(f"  -> GAGAL mengirim ke {email}: {e_send}")
                log_email_status(username, name, email, "failed", str(e_send))
                failed_count += 1

    finally:
        # Tutup koneksi server SMTP secara aman jika dibuka
        if server:
            try:
                server.quit()
                log.info("Koneksi server SMTP ditutup.")
            except Exception:
                pass

    log.info("=" * 60)
    log.info("  SELESAI")
    log.info(f"  Email terkirim : {sent_count}")
    log.info(f"  Email gagal    : {failed_count}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()

"""
analyzer.py — Menganalisis data mentah OSM JSON dan mengekspornya ke format CSV dan Excel (xlsx)
"""
import glob
import json
import logging
import os
from datetime import datetime
from pathlib import Path
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("analyzer")

def main():
    print("=" * 60)
    print("  UMKM Leads Analyzer & Exporter")
    print("=" * 60 + "\n")

    output_dir = Path("output")
    if not output_dir.exists():
        log.error("Folder output/ tidak ditemukan. Jalankan osm_scraper.py terlebih dahulu.")
        return

    # Cari data mentah JSON terbaru
    json_files = sorted(glob.glob("output/umkm_raw_*.json"), reverse=True)
    if not json_files:
        log.error("Tidak ditemukan file data mentah 'output/umkm_raw_*.json'.")
        log.info("Silakan jalankan scraper terlebih dahulu.")
        return

    latest_json = Path(json_files[0])
    log.info(f"Membaca data mentah terbaru dari: {latest_json}")

    with open(latest_json, "r", encoding="utf-8") as f:
        leads = json.load(f)

    if not leads:
        log.warning("File JSON kosong. Tidak ada data untuk dianalisis.")
        return

    # Filter out permanently closed, abandoned, or disused businesses
    filtered_leads = []
    for lead in leads:
        name = lead.get("full_name", "").lower()
        bio = lead.get("biography", "").lower()
        
        # Check for closed terms in name or description
        if any(term in name or term in bio for term in ["closed", "tutup permanen", "permanently closed", "tutup selamanya"]):
            continue
        filtered_leads.append(lead)
    
    leads = filtered_leads

    # Lakukan perhitungan/update lead_score jika belum ada
    for lead in leads:
        if "lead_score" not in lead:
            score = 50
            if lead.get("phone"):
                score += 20
            if lead.get("email"):
                score += 20
            if lead.get("category") and lead.get("category") != "Bisnis Lokal":
                score += 10
            lead["lead_score"] = min(score, 100)

    # Ekspor menggunakan pandas
    df = pd.DataFrame(leads)

    # Ekstrak timestamp dari nama file JSON untuk menjaga konsistensi nama file
    # Format nama file: umkm_raw_YYYYMMDD_HHMMSS.json
    try:
        parts = latest_json.stem.split("_")
        if len(parts) >= 4:
            timestamp = f"{parts[2]}_{parts[3]}"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    except Exception:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Path ekspor
    csv_path = output_dir / f"umkm_leads_{timestamp}.csv"
    xlsx_path = output_dir / f"umkm_leads_{timestamp}.xlsx"

    # Simpan ke CSV
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log.info(f"[OK] Berhasil mengekspor CSV ke: {csv_path}")

    # Simpan ke Excel
    try:
        df.to_excel(xlsx_path, index=False, engine="openpyxl")
        log.info(f"[OK] Berhasil mengekspor Excel (xlsx) ke: {xlsx_path}")
    except Exception as e:
        log.error(f"Gagal mengekspor Excel: {e}")

    print("\n" + "=" * 60)
    print("  SELESAI. Silakan jalankan generator atau resolver selanjutnya.")
    print("=" * 60)

if __name__ == "__main__":
    main()

# 🚀 UMKM Scraper & RAG Direct Message Bot

Sistem pemasaran otonom berbasis kecerdasan buatan (AI) yang dirancang untuk mencari data tempat usaha (UMKM) lokal secara gratis, merancang pesan penawaran kustom menggunakan teknologi RAG (Retrieval-Augmented Generation), dan mengirimkan pesan Instagram DM otomatis.

Kini dilengkapi dengan **Web Dashboard GUI** untuk kontrol visual penuh tanpa perlu menyentuh terminal!

---

## 💻 Web Dashboard Management (GUI)
Anda sekarang dapat mengontrol seluruh alur kerja program secara visual melalui halaman web interaktif.

### Cara Menjalankan Dashboard:
1. Jalankan server backend Flask di terminal Anda:
   ```powershell
   python app.py
   ```
2. Buka browser (Brave/Chrome/Edge) Anda dan akses alamat berikut:
   🔗 **[http://localhost:5000](http://localhost:5000)**

### Fitur Dashboard Web:
- **Statistik Kampanye Dinamis**: Melihat jumlah total leads, leads bernilai tinggi, status DM sukses, gagal, dan terlewati secara real-time.
- **Workflow Control & Virtual Terminal**: Cukup klik tombol **Jalankan** untuk memicu Scraper, Generator AI, Resolver, atau Pengirim DM. Dilengkapi konsol terminal log mengalir secara real-time.
- **Leads & Copywriting Editor**: Edit nama pengguna target (dummy `osm_xxxx` ke akun asli) dan pesan promosi kustom AI langsung di tabel web, lalu simpan dengan tombol klik disket hijau.
- **Settings Form Terintegrasi**: Mengubah konfigurasi `.env` (seperti Kunci API, model AI, dan Session ID Instagram) langsung lewat formulir halaman web.

---

## 🌟 Fitur Utama Mesin Bot
1. **Scraping Peta Gratis & Tanpa Batas (`osm_scraper.py`)**: Mengekstrak data bisnis lokal di kota tertentu langsung dari OpenStreetMap (OSM) Overpass API. 100% gratis tanpa login.
2. **AI RAG Evaluator & Copywriter (`rag_dm_generator.py`)**: Menyaring leads potensial tanpa website, menyimpan ke database vektor lokal (**ChromaDB**), dan merumuskan draf pesan kustom. Mendukung model:
   - **Google Gemini API** (Cloud)
   - **OpenRouter API** (Llama 3.1, Gemma, Mistral)
   - **Ollama** (Offline/Lokal secara gratis lewat Google Colab)
3. **Pencarian Akun Instagram Otomatis (`resolve_ig_usernames.py`)**: Menghubungkan nama bisnis hasil ekstraksi peta ke akun Instagram asli mereka.
4. **Pengirim DM Massal Aman (`dm_sender.py`)**: Mengirimkan DM kustom menggunakan teknik **Bypass Session ID Cookie** untuk melompati pemeriksaan keamanan Instagram.

---

## 🛠️ Persyaratan Sistem & Instalasi

### 1. Kloning Proyek & Masuk ke Folder
```powershell
cd umkm-scraper
```

### 2. Instal Library Python Dependensi
Pastikan Python 3.9+ sudah terinstal, lalu jalankan:
```powershell
pip install -r requirements.txt
```

### 3. Salin & Isi Konfigurasi `.env`
Salin file `.env.template` menjadi `.env` dan isi variabel di dalamnya. (Anda juga bisa mengisi data ini langsung lewat menu Settings di Web Dashboard).

---

## 🎯 Panduan Alur Kerja (Cara Menjalankan via Terminal)
Jika Anda tidak ingin menggunakan Web GUI, Anda tetap bisa menjalankan skrip manual di terminal secara berurutan:

### Langkah 1: Scraping Data Peta Wilayah
```powershell
python osm_scraper.py
```
*Output mentah disimpan di `output/`.*

### Langkah 2: Buat Draf Pesan Promosi Kustom AI (RAG)
```powershell
# Jalankan mode tes (preview saja)
python rag_dm_generator.py --test --limit 5 --min-score 45
```
*Output disimpan di `output/rag_dm_drafts.csv`.*

### Langkah 3: Cari Username Instagram Asli target UMKM
```powershell
python resolve_ig_usernames.py
```
*Output disimpan di `output/rag_dm_drafts_resolved.csv`.*

### Langkah 4: Eksekusi Pengiriman DM Otomatis
```powershell
python dm_sender.py --csv output/rag_dm_drafts_resolved.csv --limit 30
```

---

## 📂 Struktur Folder
```text
umkm-scraper/
├── chroma_db/                  # Database Vektor ChromaDB untuk RAG lokal
├── output/                     # Hasil log scraper, draf AI, dan status DM
├── templates/                  # Folder template HTML
│   └── index.html              # Antarmuka Dashboard Web Utama
├── app.py                      # Server backend web Flask
├── .env                        # File konfigurasi utama (DIABAIKAN OLEH GIT)
├── .gitignore                  # File pengecualian upload Git
├── dm_sender.py                # Script pengirim pesan DM Instagram
├── osm_scraper.py              # Script scraper data wilayah via OpenStreetMap
├── rag_dm_generator.py         # Script perancang draf penawaran kustom AI
├── requirements.txt            # Daftar library Python dependensi proyek
├── resolve_ig_usernames.py     # Script pencocokan username asli Instagram
└── README.md                   # Dokumentasi proyek (file ini)
```

---

## 🔒 Catatan Keamanan Akun Instagram
- **Wajib menggunakan Session ID**: Selalu gunakan cookie `sessionid` browser untuk meminimalkan risiko pemblokiran login baru oleh Instagram.
- **Jeda Waktu Aman**: Script `dm_sender.py` sudah dilengkapi jeda acak 30 hingga 90 detik antar pesan untuk meniru perilaku wajar manusia. Jangan perkecil nilai delay ini.

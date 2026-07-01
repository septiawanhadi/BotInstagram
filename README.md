# 🚀 UMKM Scraper & RAG Direct Message Bot

Bot pemasaran otonom berbasis kecerdasan buatan (AI) yang dirancang untuk mencari data tempat usaha (UMKM) lokal secara gratis, merancang pesan penawaran kustom yang personal menggunakan teknologi RAG (Retrieval-Augmented Generation), dan mengirimkan pesan Instagram DM otomatis menggunakan bypass Session ID browser.

---

## 🌟 Fitur Utama
1. **Scraping Peta Gratis & Tanpa Batas (`osm_scraper.py`)**: Mengekstrak data bisnis lokal (Restoran, Cafe, Barbershop, Spa, dll) di kota tertentu langsung dari OpenStreetMap (OSM) Overpass API. 100% gratis tanpa perlu kredensial login atau limitasi web-scraping biasa.
2. **AI RAG Evaluator & Copywriter (`rag_dm_generator.py`)**: Menyaring leads potensial yang belum memiliki website, memasukkannya ke database vektor lokal (**ChromaDB**), dan merumuskan draf pesan cold-outreach yang personal, natural, dan ramah khas Indonesia. Mendukung multi-model:
   - **Google Gemini API** (Cloud)
   - **OpenRouter API** (Llama 3.1, Gemma, Mistral, dll)
   - **Ollama** (Offline/Lokal secara gratis tanpa batasan)
3. **Pencarian Akun Instagram Otomatis (`resolve_ig_usernames.py`)**: Menghubungkan nama bisnis hasil ekstraksi peta ke akun Instagram asli mereka menggunakan pencarian cerdas API Instagram.
4. **Pengirim DM Massal Aman (`dm_sender.py`)**: Mengirimkan DM kustom hasil AI langsung ke akun target. Menggunakan teknik **Bypass Session ID Cookie** untuk melompati pemeriksaan keamanan Instagram (Challenge/2FA) secara 100% aman.

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
Salin file `.env.template` menjadi `.env` dan isi variabel di dalamnya:
```ini
# Credentials akun Instagram bot Anda
IG_USERNAME=username_akun_bot
IG_PASSWORD=password_akun_bot
IG_SESSIONID=masukkan_session_id_browser_di_sini   # (Wajib untuk bypass verifikasi)

# Pilihan Tipe AI: cloud (Gemini), local (Ollama), atau openrouter (OpenRouter)
AI_TYPE=openrouter

# Konfigurasi Google Gemini (Jika AI_TYPE=cloud)
GEMINI_API_KEY=api_key_gemini_anda
GEMINI_MODEL=gemini-2.5-flash

# Konfigurasi OpenRouter (Jika AI_TYPE=openrouter)
OPENROUTER_API_KEY=api_key_openrouter_anda
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct

# Konfigurasi LLM Lokal (Jika AI_TYPE=local & memakai Ollama)
LOCAL_LLM_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=gemma4:e4b
```

---

## 🎯 Panduan Alur Kerja (Cara Menjalankan)

Jalankan script secara berurutan sesuai langkah-langkah di bawah ini:

### Langkah 1: Scraping Data Peta Wilayah
Mengekstrak bisnis di wilayah target (contoh: Surabaya) yang tidak memiliki situs web resmi:
```powershell
python osm_scraper.py
```
*Hasil output mentah akan disimpan di folder `output/`.*

### Langkah 2: Buat Draf Pesan Promosi Kustom AI (RAG)
Menilai relevansi leads dan membuat rancangan teks pesan DM kustom unik untuk tiap bisnis:
```powershell
# Jalankan mode tes (preview) untuk 5 akun dengan skor prioritas >= 45
python rag_dm_generator.py --test --limit 5 --min-score 45

# Jalankan proses sungguhan untuk 30 akun teratas
python rag_dm_generator.py --limit 30 --min-score 45
```
*Hasil draf teks pesan AI akan disimpan di `output/rag_dm_drafts.csv`.*

### Langkah 3: Cari Username Instagram Asli target UMKM
Menghubungkan nama bisnis target ke akun Instagram nyata mereka di internet:
```powershell
python resolve_ig_usernames.py
```
*Script akan menghasilkan file target matang di `output/rag_dm_drafts_resolved.csv`.*

### Langkah 4: Eksekusi Pengiriman DM Otomatis
Mengirimkan pesan penawaran kustom AI secara massal dan aman (dengan jeda 30-90 detik per pengiriman):
```powershell
python dm_sender.py --csv output/rag_dm_drafts_resolved.csv --limit 30
```
*Log status pengiriman sukses/gagal dicatat di `output/dm_sent_log.csv`.*

---

## 📂 Struktur Folder
```text
umkm-scraper/
├── chroma_db/                  # Database Vektor ChromaDB untuk RAG lokal
├── output/                     # Hasil log scraper, draf AI, dan status DM
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
- **Wajib menggunakan Session ID**: Selalu gunakan nilai cookie `sessionid` dari browser Chrome/Brave/Edge Anda yang sudah login untuk meminimalkan risiko pemblokiran login baru oleh sistem deteksi bot Instagram.
- **Jeda Waktu Aman**: Script `dm_sender.py` sudah dilengkapi jeda acak (*random delay*) 30 hingga 90 detik antar pesan untuk meniru perilaku wajar manusia. Jangan perkecil nilai delay ini demi keselamatan akun Anda.

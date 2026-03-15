# 🩺 Dr. Tagger

**Treats your broken tags** — An intelligent MP3 auto-tagger with a sleek dark UI.

Dr. Tagger automatically identifies and tags your MP3 files using multiple metadata sources (Discogs, Beatport, Traxsource) and audio fingerprinting (AcoustID/Chromaprint).

---

## ✨ Features

- **Auto-Tagging** — Scans your MP3 library and automatically identifies tracks via audio fingerprinting and metadata APIs
- **Manual Search** — Search across Discogs, Beatport, and Traxsource when auto-detection fails
- **Cover Art** — Automatic cover art embedding from metadata sources + manual JPG upload
- **Before/After Comparison** — Tag Details modal shows original vs. proposed tags side-by-side
- **Backup & Restore** — Automatic file backups before writing tags, with one-click restore
- **Live Progress** — Real-time scan/tag progress via WebSocket
- **Recursive Scanning** — Scans all subdirectories within your audio folder
- **Audio Preview** — Built-in audio player with play/pause controls

## 🛠 Tech Stack

| Layer    | Technology                    |
|----------|-------------------------------|
| Backend  | Python, FastAPI, Uvicorn      |
| Frontend | Vanilla HTML/CSS/JS           |
| Database | SQLite (WAL mode)             |
| Audio    | Mutagen (ID3), Chromaprint    |
| APIs     | Discogs, Beatport, Traxsource |

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [fpcalc](https://acoustid.org/chromaprint) (Chromaprint CLI tool) — place `fpcalc.exe` in the project root

### Installation

```bash
# Clone the repository
git clone https://github.com/akadawa/dr.tagger.git
cd dr.tagger

# Create virtual environment
python -m venv .venv

# Activate it
# Windows:
.\.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and add your Discogs API key
# Get one at: https://www.discogs.com/settings/developers
```

### Running

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8002
```

Then open [http://localhost:8002](http://localhost:8002) in your browser.

## 📁 Project Structure

```
dr.tagger/
├── backend/
│   ├── main.py            # FastAPI server, API endpoints, WebSocket
│   ├── database.py        # SQLite database layer
│   └── tagger_engine.py   # Audio fingerprinting, API lookups, tag writing
├── frontend/
│   ├── index.html          # Main UI
│   ├── script.js           # Frontend logic
│   ├── style.css           # Dark theme styles
│   └── logo.png            # Dr. Tagger mascot
├── audiofiles/             # Drop your MP3 files here
├── backup/                 # Auto-created backups before tagging
├── covers/uploaded/        # Manually uploaded cover art
├── .env.example            # Environment template
├── requirements.txt        # Python dependencies
└── README.md
```

## 📖 Usage

1. **Drop MP3 files** into the `audiofiles/` directory (subdirectories supported)
2. **Click "Start Scan"** to begin automatic identification
3. **Review results** — tracks show status badges (FOUND, NOT FOUND, etc.)
4. **Manual search** — Click the 🔎 icon on unidentified tracks to search manually
5. **Upload covers** — Open Tag Details (✏ icon) and click "Upload JPG"
6. **Click "Write Tags"** to apply all changes to your files
7. **Restore** — Use the Restore button to revert any changes from backups

## 📝 License

MIT

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "tags.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    # Create tracks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            artist TEXT,
            title TEXT,
            orig_artist TEXT,
            orig_title TEXT,
            orig_genre TEXT,
            album TEXT,
            genre TEXT,
            year TEXT,
            score INTEGER,
            match_source TEXT,
            fingerprint TEXT,
            cover_url TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: Add cover_url if it doesn't exist
    try:
        cursor.execute("ALTER TABLE tracks ADD COLUMN cover_url TEXT")
    except sqlite3.OperationalError:
        pass # Already exists
    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect(DB_PATH)

def add_or_update_track(file_path, status='pending', tags=None, score=0, match_source=None, fingerprint=None, original=None):
    if tags is None:
        tags = {}
    if original is None:
        original = {}
        
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tracks (file_path, status, artist, title, orig_artist, orig_title, orig_genre, album, genre, year, score, match_source, fingerprint, cover_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            status=excluded.status,
            artist=excluded.artist,
            title=excluded.title,
            orig_artist=COALESCE(tracks.orig_artist, excluded.orig_artist),
            orig_title=COALESCE(tracks.orig_title, excluded.orig_title),
            orig_genre=COALESCE(tracks.orig_genre, excluded.orig_genre),
            album=excluded.album,
            genre=excluded.genre,
            year=excluded.year,
            score=excluded.score,
            match_source=excluded.match_source,
            fingerprint=excluded.fingerprint,
            cover_url=excluded.cover_url,
            updated_at=CURRENT_TIMESTAMP
    """, (
        file_path, status, tags.get('artist'), tags.get('title'), 
        original.get('artist'), original.get('title'), original.get('genre'),
        tags.get('album'), tags.get('genre'), tags.get('year'), 
        score, match_source, fingerprint, tags.get('cover_url')
    ))
    conn.commit()
    conn.close()

def get_all_tracks():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tracks ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_track_by_id(track_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def clear_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tracks")
        conn.commit()
        conn.close()
        print("DB: Table 'tracks' cleared successfully.")
    except Exception as e:
        print(f"DB ERROR: Failed to clear table: {e}")

def update_track_metadata(track_id, tags, status=None):
    """Updates the metadata for a specific track ID, optionally update status."""
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
            UPDATE tracks 
            SET artist=?, title=?, album=?, genre=?, year=?, cover_url=?, status=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (tags.get('artist'), tags.get('title'), tags.get('album'), 
              tags.get('genre'), tags.get('year'), tags.get('cover_url'), status, track_id))
    else:
        cursor.execute("""
            UPDATE tracks 
            SET artist=?, title=?, album=?, genre=?, year=?, cover_url=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (tags.get('artist'), tags.get('title'), tags.get('album'), 
              tags.get('genre'), tags.get('year'), tags.get('cover_url'), track_id))
    conn.commit()
    conn.close()

def update_track_path(track_id, new_path, status=None):
    """Updates the file path for a specific track ID, optionally update status."""
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("UPDATE tracks SET file_path=?, status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", 
                      (new_path, status, track_id))
    else:
        cursor.execute("UPDATE tracks SET file_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", 
                      (new_path, track_id))
    conn.commit()
    conn.close()

def update_track_info(track_id, artist, title, album, year, genre):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tracks 
        SET artist=?, title=?, album=?, year=?, genre=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (artist, title, album, year, genre, track_id))
    conn.commit()
    conn.close()

def update_track_status(track_id, status):
    """Updates the status for a specific track ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE tracks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, track_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")

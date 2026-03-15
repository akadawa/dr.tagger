from fastapi import FastAPI, WebSocket, BackgroundTasks, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import shutil
import asyncio
import os
import json
from pathlib import Path
from backend.database import init_db, add_or_update_track, get_all_tracks, clear_db, update_track_metadata, update_track_path, get_track_by_id, update_track_status, update_track_info
from backend.tagger_engine import process_file, apply_tags_to_file, get_audio_metadata, manual_search

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# WebSocket manager for live updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                # 1s timeout to prevent hanging on slow clients
                await asyncio.wait_for(connection.send_json(message), timeout=1.0)
            except Exception as e:
                print(f"WS Broadcast error: {e}")
                pass

manager = ConnectionManager()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "backup"
BACKUP_DIR.mkdir(exist_ok=True)
UPLOAD_DIR = BASE_DIR / "covers" / "uploaded"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def backup_file(db_path: str):
    """Copies a file to the backup directory. db_path is the relative path from DB."""
    try:
        source = AUDIO_DIR / db_path
        if not source.exists():
            return False
            
        # Maintain subdirectory structure in backup
        dest = BACKUP_DIR / db_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        if not dest.exists():
            shutil.copy2(source, dest)
            return True
    except Exception as e:
        print(f"Backup error for {db_path}: {e}")
    return False

def clear_backups():
    """Removes all files and subdirectories from the backup directory."""
    for item in BACKUP_DIR.iterdir():
        if item.name == '.gitkeep':
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

def clear_uploads():
    """Removes all uploaded cover art files."""
    for item in UPLOAD_DIR.iterdir():
        if item.name == '.gitkeep':
            continue
        item.unlink()

AUDIO_DIR = BASE_DIR / "audiofiles"

@app.get("/api/tracks")
async def list_tracks():
    """Lists all tracks from the database."""
    return await asyncio.to_thread(get_all_tracks)

@app.get("/api/search")
async def search_metadata(q: str):
    """Performs a manual search for metadata."""
    if not q:
        return []
    return await asyncio.to_thread(manual_search, q)

@app.post("/api/scan")
async def start_scan(background_tasks: BackgroundTasks):
    """Triggers a scan of the audiofiles directory."""
    background_tasks.add_task(run_scan)
    return {"message": "Scan started"}

@app.post("/api/clear")
async def clear_tracks():
    """Clears all tracks from the database and empties backup + uploaded covers."""
    print("API: Clearing database, backups, and uploaded covers...")
    await asyncio.to_thread(clear_db)
    await asyncio.to_thread(clear_backups)
    await asyncio.to_thread(clear_uploads)
    return {"message": "Database, backups, and uploads cleared"}

@app.post("/api/restore")
async def restore_tracks(track_ids: list[int]):
    """Restores selected tracks from the backup folder."""
    restored_count = 0
    for tid in track_ids:
        track = await asyncio.to_thread(get_track_by_id, tid)
        if not track:
            continue
            
        rel_path = track['file_path']
        abs_source_path = AUDIO_DIR / rel_path
        backup_path = BACKUP_DIR / rel_path
        
        if backup_path.exists():
            try:
                # Ensure destination directory exists
                abs_source_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy back from backup to original location
                shutil.copy2(backup_path, abs_source_path)
                
                # Re-scan the file to update the DB with original metadata
                metadata = await asyncio.to_thread(get_audio_metadata, str(abs_source_path))
                if metadata:
                    await asyncio.to_thread(
                        update_track_info,
                        tid,
                        metadata.get('artist'),
                        metadata.get('title'),
                        metadata.get('album'),
                        metadata.get('year'),
                        metadata.get('genre')
                    )
                
                # Update status back to 'restored' to reflect it's back to original state
                await asyncio.to_thread(update_track_status, tid, "restored")
                restored_count += 1
            except Exception as e:
                print(f"Restore error for {abs_source_path}: {e}")
                
    return {"message": f"Restored {restored_count} tracks", "count": restored_count}

@app.get("/api/audio/{filename:path}")
async def stream_audio(filename: str):
    """Streams an audio file from the audiofiles directory."""
    from fastapi.responses import FileResponse
    # Normalize slashes and remove leading
    clean_filename = filename.replace("\\", "/").lstrip("/")
    file_path = (AUDIO_DIR / clean_filename).resolve()
    
    if not file_path.exists() or not file_path.suffix.lower() == ".mp3":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"File not found: {clean_filename}")
        
    # Ensure the file is actually inside AUDIO_DIR for security
    if not str(file_path).startswith(str(AUDIO_DIR.resolve())):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Forbidden")
        
    return FileResponse(str(file_path), media_type="audio/mpeg", headers={
        "Accept-Ranges": "bytes"
    })

@app.get("/api/cover/uploaded/{filename}")
async def get_uploaded_cover(filename: str):
    """Serves a manually uploaded cover art."""
    from fastapi.responses import FileResponse
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(str(file_path))

@app.get("/api/cover/{filename:path}")
async def get_cover(filename: str):
    """Extracts and serves the embedded cover art from an MP3's ID3 APIC tag."""
    from fastapi.responses import Response
    from fastapi import HTTPException
    from mutagen.id3 import ID3
    
    # Normalize slashes and remove leading
    clean_filename = filename.replace("\\", "/").lstrip("/")
    file_path = (AUDIO_DIR / clean_filename).resolve()
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    # Security check
    if not str(file_path).startswith(str(AUDIO_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    try:
        tags = ID3(str(file_path))
        # Search for any APIC frame regardless of description
        apic = None
        for key in tags.keys():
            if key.startswith('APIC'):
                apic = tags[key]
                break
        if apic:
            return Response(content=apic.data, media_type=apic.mime or 'image/jpeg')
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="No cover art found")

@app.post("/api/tracks/{track_id}/upload_cover")
async def upload_cover(track_id: int, file: UploadFile = File(...)):
    """Handles manual cover art upload (JPG/JPEG only)."""
    if not file.content_type in ["image/jpeg", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Only JPG/JPEG images are allowed")
    
    # Check extension too
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg"]:
        raise HTTPException(status_code=400, detail="Only .jpg or .jpeg files are allowed")

    track = get_track_by_id(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Save file with unique name based on track ID
    save_name = f"cover_{track_id}{ext}"
    save_path = UPLOAD_DIR / save_name
    
    with save_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Return the URL/path to be stored in DB
    cover_url = f"/api/cover/uploaded/{save_name}"
    
    # Update track metadata in DB with the new cover_url (staging)
    # Fetch existing tags to update only cover_url
    tags = {
        'artist': track['artist'],
        'title': track['title'],
        'album': track['album'],
        'genre': track['genre'],
        'year': track['year'],
        'cover_url': cover_url # Store relative web URL for UI and engine resolution
    }
    update_track_metadata(track_id, tags, status='manual-tagged')
    
    # Broadcast UI update
    await manager.broadcast({"type": "track_updated"})
    
    return {"cover_url": cover_url, "message": "Cover uploaded successfully"}

@app.post("/api/tracks/{track_id}/update")
async def update_track(track_id: int, tags: dict):
    """Manually update tags for a track in DB (staged status)."""
    track = get_track_by_id(track_id)
    if not track:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Track not found")
    
    # Update DB with provided status (defaults to manual-tagged if not specified)
    new_status = tags.get('status', 'manual-tagged')
    update_track_metadata(track_id, tags, status=new_status)
    
    # Broadcast UI update
    await manager.broadcast({"type": "track_updated"})
    
    return {"message": "Track staging updated successfully"}


# Renaming endpoints removed as per user request


async def run_scan():
    """Background task to scan files and tag them."""
    if not AUDIO_DIR.exists():
        await manager.broadcast({"type": "error", "message": f"Directory {AUDIO_DIR} not found"})
        return

    # Recursive scan using pathlib.rglob
    # We store the path RELATIVE to AUDIO_DIR in the database
    files_paths = [f.relative_to(AUDIO_DIR) for f in AUDIO_DIR.rglob("*.mp3") if f.is_file()]
    total = len(files_paths)
    
    await manager.broadcast({"type": "progress", "current": 0, "total": total, "status": "Starting scan..."})

    for i, rel_path in enumerate(files_paths):
        filename = rel_path.name
        file_path = str(AUDIO_DIR / rel_path)
        # For the database and UI, we use the relative path string
        db_path = str(rel_path)
        
        # Notify UI
        await manager.broadcast({
            "type": "processing", 
            "filename": filename, 
            "current": i + 1, 
            "total": total
        })

        try:
            # Process the file - involves network/fingerprinting, so thread it with timeout
            result = await asyncio.wait_for(
                asyncio.to_thread(process_file, file_path),
                timeout=60.0 # 60s for full fingerprint + network lookup
            )
            
            # Save to DB - disk I/O, thread it
            await asyncio.to_thread(
                add_or_update_track,
                file_path=db_path, # Store RELATIVE path in DB
                status=result['status'],
                tags=result.get('data') or {},
                score=result.get('data', {}).get('score', 0) if result.get('data') else 0,
                match_source=result.get('data', {}).get('source') if result.get('data') else None,
                fingerprint=result.get('fingerprint'),
                original=result.get('original')
            )

            # Broadcast update
            await manager.broadcast({
                "type": "track_updated",
                "filename": filename,
                "status": result['status'],
                "data": result.get('data')
            })

            percent = int(((i + 1) / total) * 100)
            await manager.broadcast({
                "type": "progress",
                "current": i + 1,
                "total": total,
                "percent": percent,
                "status": f"Scanning: {percent}%"
            })
        except asyncio.TimeoutError:
            print(f"TIMEOUT scanning {filename}")
            await manager.broadcast({"type": "info", "message": f"Timeout scanning {filename}. Skipping..."})
        except Exception as e:
            print(f"ERROR scanning {filename}: {e}")
            await manager.broadcast({"type": "error", "message": f"Error scanning {filename}: {str(e)}"})

    await manager.broadcast({"type": "progress", "current": total, "total": total, "percent": 100, "status": "Scan complete!"})
    await manager.broadcast({"type": "scan_finished"})

@app.post("/api/autotag")
async def run_autotag(background_tasks: BackgroundTasks):
    """Triggers the actual tagging (writing to files) for tracks with 'found' status."""
    background_tasks.add_task(process_autotag)
    return {"message": "Auto-tagging started"}

async def process_autotag():
    """Background task to write tags to files for all 'found' tracks."""
    # DB read in thread
    tracks_all = await asyncio.to_thread(get_all_tracks)
    # Include tracks that have actual tags to write. Exclude untagged/not-found.
    tracks = [t for t in tracks_all if t['status'] in ('found', 'manual-tagged', 'searched', 'tagged')]
    total = len(tracks)
    
    if total == 0:
        await manager.broadcast({"type": "progress", "current": 0, "total": 0, "status": "No tracks to tag."})
        return

    await manager.broadcast({"type": "progress", "current": 0, "total": total, "status": "Starting tagging..."})

    for i, track in enumerate(tracks):
        # Calculate and broadcast progress percentage
        percent = int(((i + 1) / total) * 100)
        await manager.broadcast({
            "type": "progress",
            "current": i + 1,
            "total": total,
            "percent": percent,
            "status": f"Tagging: {percent}%"
        })

        # Broadcast current file
        await manager.broadcast({
            "type": "processing",
            "filename": os.path.basename(track['file_path']),
            "current": i + 1,
            "total": total
        })

        # Don't write 'Not found' to the actual genre tag
        tags_to_write = {
            'artist': track['artist'],
            'title': track['title'],
            'album': track['album'],
            'genre': track['genre'] if track['genre'] != 'Not found' else None,
            'year': track['year'],
            'cover_url': track.get('cover_url')
        }

        try:
            rel_path = track['file_path']
            abs_path = str(AUDIO_DIR / rel_path)

            # Create backup before writing if not already backed up
            await asyncio.to_thread(backup_file, rel_path)

            # Apply tags to physical file - Disk I/O, thread it with timeout
            success = await asyncio.wait_for(
                asyncio.to_thread(apply_tags_to_file, abs_path, tags_to_write),
                timeout=10.0 # 10s should be plenty for local disk I/O
            )
            
            if success:
                # Update DB status to 'tagged' - Disk I/O, thread it
                await asyncio.to_thread(update_track_status, track['id'], "tagged")
                # Broadcast UI update
                await manager.broadcast({"type": "track_updated", "track_id": track['id'], "status": "tagged"})
        except asyncio.TimeoutError:
            print(f"TIMEOUT tagging {track['file_path']}")
            await manager.broadcast({"type": "info", "message": f"Timeout tagging {os.path.basename(track['file_path'])}. Skipping..."})
        except Exception as e:
            print(f"ERROR tagging {track['file_path']}: {e}")
            await manager.broadcast({"type": "error", "message": f"Error tagging {os.path.basename(track['file_path'])}: {str(e)}"})
        
    await manager.broadcast({"type": "progress", "current": total, "total": total, "status": "Tagging complete!"})
    
    # Transition remaining 'not-found' tracks to 'untagged'
    await asyncio.to_thread(_transition_not_found_to_untagged)
    await manager.broadcast({"type": "track_updated"})

def _transition_not_found_to_untagged():
    """Updates all 'not-found' or 'not_found' tracks to 'untagged' in the DB."""
    from backend.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE tracks SET status='untagged' WHERE status IN ('not-found', 'not_found')")
    conn.commit()
    conn.close()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Serve Frontend
app.mount("/", StaticFiles(directory=str(BASE_DIR / "frontend"), html=True), name="frontend")

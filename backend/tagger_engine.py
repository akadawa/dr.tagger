import acoustid
import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TYER, TDRC, TBPM, TKEY, COMM
import os
import re
import requests
import time
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Note: For production use, get an API key from https://acoustid.org/login
# Using the client application ID is standard for pyacoustid
API_KEY = "8XaBELgH" # AcoustID Public API Key for pyacoustid
DISCOGS_API_KEY = os.getenv("DISCOGS_API_KEY", "MTOEWEYabCrawqiorOtdatthIkgFDIQesxVlfkbT") # Discogs Personal Access Token

# Make search for fpcalc more robust - check current directory
FPCALC_PATH = Path(__file__).resolve().parent.parent / "fpcalc.exe"
if FPCALC_PATH.exists():
    acoustid.FPCALC_COMMAND = str(FPCALC_PATH)

def get_page(url, referer=None):
    """Fetches a page with robust mobile browser headers to avoid detection."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    if referer:
        headers['Referer'] = referer
    
    try:
        # Avoid creating a new session every time for better performance/stealth
        resp = requests.get(url, headers=headers, timeout=15)
        return resp
    except Exception as e:
        print(f"  - Request error for {url}: {e}")
        return None

def get_fingerprint(file_path):
    """Calculates the fingerprint of the audio file."""
    try:
        duration, fingerprint = acoustid.fingerprint_file(file_path)
        return duration, fingerprint
    except Exception as e:
        import traceback
        err_msg = str(e)
        if "fpcalc not found" in err_msg:
            print(f"ERROR: fpcalc.exe not found or not executable. Path: {FPCALC_PATH}")
        else:
            print(f"CRITICAL ERROR fingerprinting {file_path}:\n{traceback.format_exc()}")
        return None, err_msg

def lookup_metadata(duration, fingerprint):
    """Looks up metadata using AcoustID and MusicBrainz."""
    try:
        # Step 1: Query AcoustID for MusicBrainz IDs
        # Include 'tags' to get genres/classifications
        response = acoustid.lookup(apikey=API_KEY, fingerprint=fingerprint, duration=duration, meta=['recordings', 'releases', 'tags'])
        
        results = []
        if isinstance(response, dict):
            if 'results' in response:
                results = response['results']
            elif 'recordings' in response:
                results = [{'recordings': response['recordings'], 'score': 1.0}]
        elif isinstance(response, list):
            results = response
        
        print(f"AcoustID lookup returned {len(results)} results.")
        matches = []
        for result in results:
            if not isinstance(result, dict):
                continue
                
            score = float(result.get('score', 0)) * 100
            if 'recordings' in result:
                for recording in result['recordings']:
                    if not isinstance(recording, dict):
                        continue
                        
                    # Robust artist extraction
                    artist = "Unknown Artist"
                    artists = recording.get('artists')
                    if artists and isinstance(artists, list):
                        if isinstance(artists[0], dict):
                            artist = artists[0].get('name', "Unknown Artist")
                        else:
                            artist = str(artists[0])

                    match = {
                        'title': recording.get('title', "Unknown Title"),
                        'artist': artist,
                        'score': score,
                        'source': 'MusicBrainz (AcoustID)',
                        'genre': 'Not found' # Default value
                    }
                    
                    # Extract Genre (Tags) from recording
                    tags = recording.get('tags', [])
                    if tags and isinstance(tags, list):
                        # Join top 3 tags as genres
                        genre_list = [t.get('name') for t in tags if isinstance(t, dict) and t.get('name')]
                        if genre_list:
                            match['genre'] = " / ".join(genre_list[:3])
                        
                    print(f"  - Possible Match: {match['artist']} - {match['title']} (Score: {score:.2f})")
                    
                    if 'releases' in recording and isinstance(recording['releases'], list) and len(recording['releases']) > 0:
                        release = recording['releases'][0]
                        if isinstance(release, dict):
                            match['album'] = release.get('title')
                            match['year'] = release.get('year') or release.get('date', {}).get('year')
                    
                    matches.append(match)
        
        # Sort by score descending
        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches[0] if matches else None
    except Exception as e:
        import traceback
        print(f"Error looking up metadata: {e}")
        return None

def search_by_filename(file_path):
    """Fallback: Try to extract artist and title from filename."""
    filename = Path(file_path).stem
    
    # Extract catalog ID in brackets [CAT001]
    import re
    catalog_id = None
    cat_match = re.search(r'\[(.*?)\]', filename)
    if cat_match:
        catalog_id = cat_match.group(1).strip()

    # Common separators
    separators = [" - ", " – ", " — ", " _ ", " . "]
    for sep in separators:
        if sep in filename:
            parts = [p.strip() for p in filename.split(sep) if p.strip()]
            
            if not parts: continue
            
            # --- Deduplicate parts ---
            # e.g. "Claus - Claus - Moist Logic" -> ["Claus", "Claus", "Moist Logic"]
            unique_parts = []
            for p in parts:
                if not unique_parts or p.lower() != unique_parts[-1].lower():
                    unique_parts.append(p)
            
            if len(unique_parts) >= 2:
                artist = unique_parts[0]
                # Join the rest as title
                title = " - ".join(unique_parts[1:])
                
                # Further cleanup: if title starts with artist name again (e.g. "Artist - Artist Title")
                # we already split by separator, but check for leading word
                if title.lower().startswith(artist.lower()):
                    # Check if there's a space or separator after the repeated artist name
                    potential_title = title[len(artist):].strip()
                    if potential_title.startswith('-'):
                        potential_title = potential_title[1:].strip()
                    if potential_title:
                        title = potential_title

                # Remove brackets from title if present
                title = re.sub(r'\[.*?\]', '', title).strip()
                
                return {
                    'artist': artist,
                    'title': title,
                    'catalog_id': catalog_id,
                    'score': 85,
                    'source': 'File-Analysis (Filename)',
                    'genre': 'Not found'
                }
            elif len(unique_parts) == 1:
                # Only one part, could be just title or artist - handle gracefully
                return {
                    'artist': None,
                    'title': unique_parts[0],
                    'catalog_id': catalog_id,
                    'score': 50,
                    'source': 'File-Analysis (Filename)',
                    'genre': 'Not found'
                }
    
    return {'artist': None, 'title': None, 'catalog_id': catalog_id} if catalog_id else None

def search_discogs(artist, title):
    """Searches Discogs for artist and title. Returns rich metadata including genre and style."""
    if not artist or not title:
        return None

    try:
        headers = {
            'Authorization': f'Discogs token={DISCOGS_API_KEY}',
            'User-Agent': 'AutoTaggerPremium/1.0 +https://github.com/automp3tag'
        }
        # Search by artist + track title
        params = {
            'type': 'release',
            'artist': artist,
            'track': title,
            'per_page': 5,
            'page': 1
        }
        resp = requests.get('https://api.discogs.com/database/search', headers=headers, params=params, timeout=10)
        
        if resp.status_code == 429:
            print("  - Discogs rate limit hit, waiting 1s...")
            time.sleep(1)
            resp = requests.get('https://api.discogs.com/database/search', headers=headers, params=params, timeout=10)

        if resp.status_code != 200:
            print(f"  - Discogs search failed: HTTP {resp.status_code}")
            return None

        data = resp.json()
        results = data.get('results', [])

        if not results:
            print(f"  - Discogs: No results for '{artist} - {title}'")
            return None

        # Take the best (first) result
        hit = results[0]
        resource_url = hit.get('resource_url')

        # Fetch detailed release info for full genre/style/label/year
        genre_list = hit.get('genre', []) + hit.get('style', [])
        genres = " / ".join(genre_list[:4]) if genre_list else 'Not found'

        # Parse title from result — usually "Artist - Title" or just Title
        result_title = hit.get('title', f"{artist} - {title}")
        # Discogs formats as "Artist - Album", so try to extract
        parts = result_title.split(' - ', 1)
        result_artist = parts[0].strip() if len(parts) > 1 else artist
        result_album = parts[1].strip() if len(parts) > 1 else None

        # Year
        year = str(hit.get('year', '')) or None

        # Label
        label_info = hit.get('label', [])
        label = label_info[0] if label_info else None

        match = {
            'artist': result_artist,
            'title': title,
            'album': result_album,
            'year': year,
            'genre': genres,
            'label': label,
            'cover_url': hit.get('cover_image') or hit.get('thumb'),  # Discogs cover art
            'score': 91,
            'source': 'Discogs'
        }

        return match

    except Exception as e:
        print(f"  - Discogs search error: {e}")
        return None


def search_discogs_by_catno(catalog_id):
    """Searches Discogs for a specific catalog number. Very high precision."""
    if not catalog_id: return None
    try:
        headers = {
            'Authorization': f'Discogs token={DISCOGS_API_KEY}',
            'User-Agent': 'AutoTaggerPremium/1.0 +https://github.com/automp3tag'
        }
        params = {'type': 'release', 'catno': catalog_id, 'per_page': 1}
        print(f"  - Searching Discogs by Catalog ID: {catalog_id}")
        resp = requests.get('https://api.discogs.com/database/search', headers=headers, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            results = data.get('results', [])
            if results:
                hit = results[0]
                # Map to our standard format
                match = {
                    'artist': hit.get('title', '').split(' - ')[0],
                    'title': 'Unknown', # Title often not in basic search result for release
                    'album': hit.get('title', '').split(' - ')[-1],
                    'year': hit.get('year'),
                    'genre': " / ".join(hit.get('genre', []) + hit.get('style', [])),
                    'label': hit.get('label', [None])[0],
                    'cover_url': hit.get('cover_image'),
                    'score': 98, # Catalog match is nearly certain
                    'source': 'Discogs (Catalog ID)'
                }
                return match
        return None
    except Exception as e:
        print(f"  - Discogs Catalog Search error: {e}")
        return None


def search_beatport(artist, title, catalog_id=None):
    """Scrapes Beatport for track metadata using __NEXT_DATA__."""
    import json as _json, re
    if not (artist and title) and not catalog_id: return None
    try:
        # Priority 1: Catalog ID
        # Priority 2: Artist + Title
        # Priority 3: Title only
        queries = []
        if catalog_id: queries.append(catalog_id)
        if artist and title: queries.append(f"{artist} {title}")
        if title: queries.append(title)
        
        resp = None
        for query in queries:
            search_url = f"https://www.beatport.com/search?q={requests.utils.quote(query)}"
            print(f"  - Searching Beatport: {query}")
            resp = get_page(search_url, referer="https://www.beatport.com/")
            if resp and resp.status_code == 200:
                if re.search(r'href="(/track/[^"]+)"', resp.text) or '<script id="__NEXT_DATA__"' in resp.text:
                    break
        
        if not resp or resp.status_code != 200:
            return None
        
        # Parse search results
        next_m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text, re.DOTALL)
        track_url = None
        if next_m:
            try:
                search_data = _json.loads(next_m.group(1))
                queries_data = search_data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
                for q in queries_data:
                    results = q.get('state', {}).get('data', {}).get('results', [])
                    if results and isinstance(results, list):
                        # Find best match artist-title
                        for r in results:
                            if r.get('type') == 'track' or '/track/' in r.get('url', ''):
                                url = r.get('url')
                                track_url = f"https://www.beatport.com{url}" if url.startswith('/') else url
                                break
                    if track_url: break
            except: pass

        if not track_url:
            m = re.search(r'href="(/track/[^"]+)"', resp.text)
            if m: track_url = f"https://www.beatport.com{m.group(1)}"

        if not track_url: return None
        
        print(f"  - Beatport match: {track_url}")
        track_resp = get_page(track_url, referer=search_url)
        if not track_resp or track_resp.status_code != 200: return None
        
        next_data_m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', track_resp.text, re.DOTALL)
        if not next_data_m: return None
        
        data = _json.loads(next_data_m.group(1))
        track_info = data.get('props', {}).get('pageProps', {}).get('track')
        if not track_info:
            queries_data = data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
            for q in queries_data:
                d = q.get('state', {}).get('data', {})
                if d.get('type') == 'track' or (d.get('name') and d.get('artists')):
                    track_info = d
                    break
        
        if not track_info: return None
        
        res_artists = [a.get('name') for a in track_info.get('artists', [])]
        res_artist = ", ".join(res_artists) if res_artists else artist
        res_title = track_info.get('name', title)
        res_album = (track_info.get('release') or {}).get('name')
        res_label = (track_info.get('label') or {}).get('name') or (track_info.get('release') or {}).get('label', {}).get('name')
        res_genre = (track_info.get('genre') or {}).get('name', 'Techno')
        res_bpm = track_info.get('bpm')
        res_key = (track_info.get('key') or {}).get('name')
        res_year = (track_info.get('release') or {}).get('publish_date', '').split('-')[0]
        res_cover = (track_info.get('image') or {}).get('uri') or (track_info.get('release', {}).get('image') or {}).get('uri')
        
        if res_bpm and res_key:
            res_genre = f"{res_genre} / {res_bpm} BPM / {res_key}"
            # Keep raw values for dedicated tags
            track_info['bpm'] = res_bpm
            track_info['key'] = res_key
        return {
            'artist': res_artist, 'title': res_title, 'album': res_album,
            'year': res_year, 'genre': res_genre, 'label': res_label,
            'bpm': res_bpm, 'key': res_key,
            'cover_url': res_cover, 'score': 95 if catalog_id else 92, 'source': 'Beatport',
            'url': track_url
        }
    except Exception as e:
        print(f"  - Beatport error: {e}")
        return None


def search_traxsource(artist, title, catalog_id=None):
    """Scrapes Traxsource for track metadata using LD+JSON."""
    import json as _json, re
    if not (artist and title) and not catalog_id: return None
    try:
        queries = []
        if catalog_id: queries.append(catalog_id)
        if artist and title: queries.append(f"{artist} {title}")
        if title: queries.append(title)
        
        resp = None
        for query in queries:
            search_url = f"https://www.traxsource.com/search?term={requests.utils.quote(query)}"
            print(f"  - Searching Traxsource: {query}")
            resp = get_page(search_url, referer="https://www.traxsource.com/")
            if resp and resp.status_code == 200 and re.search(r'href="(/track/[^"]+)"', resp.text):
                break

        if not resp or resp.status_code != 200: return None
        
        m = re.search(r'href="(/track/[^"]+)"', resp.text)
        if not m: return None
        
        track_url = f"https://www.traxsource.com{m.group(1)}"
        print(f"  - Traxsource match: {track_url}")
        track_resp = get_page(track_url, referer=search_url)
        if not track_resp or track_resp.status_code != 200: return None
        
        ld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', track_resp.text, re.DOTALL)
        if not ld_match: return None
        
        ld = _json.loads(ld_match.group(1))
        if isinstance(ld, list): ld = ld[0]
        
        res_artist = ld.get('byArtist', {}).get('name', artist)
        res_title = ld.get('name', title)
        res_album = (ld.get('inAlbum') or {}).get('name')
        res_cover = ld.get('image')
        res_genre = ld.get('genre', 'House/Techno')
        
        bpm_m = re.search(r'BPM:</strong>\s*(\d+)', track_resp.text)
        if bpm_m: res_genre = f"{res_genre} ({bpm_m.group(1)} BPM)"
        
        return {
            'artist': res_artist, 'title': res_title, 'album': res_album,
            'genre': res_genre, 'cover_url': res_cover,
            'bpm': bpm_m.group(1) if bpm_m else None,
            'score': 95 if catalog_id else 90, 'source': 'Traxsource',
            'url': track_url
        }
    except Exception as e:
        print(f"  - Traxsource error: {e}")
        return None


def search_juno(artist, title, catalog_id=None):
    """Scrapes Juno Download for track metadata targeting the tracks filter."""
    import re
    if not (artist and title) and not catalog_id: return None
    try:
        queries = []
        if catalog_id: queries.append(catalog_id)
        if artist and title: queries.append(f"{artist} {title}")
        if title: queries.append(title)
        
        resp = None
        for query in queries:
            search_url = f"https://www.junodownload.com/search/?q[all][0]={requests.utils.quote(query)}&solr_search_main_filter=tracks"
            print(f"  - Searching Juno: {query}")
            resp = get_page(search_url, referer="https://www.junodownload.com/")
            if resp and resp.status_code == 200 and re.search(r'href="(/products/[^"]+/)"', resp.text):
                break

        if not resp or resp.status_code != 200: return None
        
        m = re.search(r'href="(/products/[^"]+/)"', resp.text)
        if not m: return None
        
        track_url = f"https://www.junodownload.com{m.group(1)}"
        print(f"  - Juno match: {track_url}")
        track_resp = get_page(track_url, referer=search_url)
        if not track_resp or track_resp.status_code != 200: return None
        
        res_title = re.search(r'<meta property="og:title" content="([^"]+)"', track_resp.text)
        res_title = res_title.group(1) if res_title else title
        res_cover = re.search(r'<meta property="og:image" content="([^"]+)"', track_resp.text)
        res_cover = res_cover.group(1) if res_cover else None
        
        bpm_match = re.search(r'BPM:</strong>\s*(\d+)', track_resp.text)
        bpm = bpm_match.group(1) if bpm_match else None
        genre_match = re.search(r'Genre:</strong>\s*<a[^>]*>([^<]+)</a>', track_resp.text)
        genre = genre_match.group(1) if genre_match else 'Electronic'
        label_match = re.search(r'Label:</strong>\s*<a[^>]*>([^<]+)</a>', track_resp.text)
        label = label_match.group(1) if label_match else None
        
        if bpm: genre = f"{genre} / {bpm} BPM"

        return {
            'artist': artist, 'title': res_title, 'genre': genre,
            'label': label, 'cover_url': res_cover,
            'bpm': bpm,
            'score': 95 if catalog_id else 88, 'source': 'Juno Download',
            'url': track_url
        }
    except Exception as e:
        print(f"  - Juno error: {e}")
        return None


def search_bandcamp(artist, title):
    """Scrapes Bandcamp search results and extracts metadata from ld+json.
    Bandcamp has no public API, but embeds full structured data on every page."""
    import re, json as _json

    if not artist or not title:
        return None

    try:
        query = f"{artist} {title}"
        search_url = f"https://bandcamp.com/search?q={requests.utils.quote(query)}&item_type=t"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        print(f"  - Searching Bandcamp: {query}")
        resp = requests.get(search_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            print(f"  - Bandcamp search failed: HTTP {resp.status_code}")
            return None

        # Extract first track/album result URL from search results
        # Bandcamp search results contain links like: https://artist.bandcamp.com/track/...
        url_pattern = re.compile(
            r'href="(https?://[a-z0-9\-]+\.bandcamp\.com/(?:track|album)/[^"&?\s]+)'
        )
        urls = url_pattern.findall(resp.text)
        if not urls:
            print(f"  - Bandcamp: No results for '{query}'")
            return None

        # Use first result (most relevant per Bandcamp's ranking)
        release_url = urls[0].split('?')[0]  # Strip query params
        print(f"  - Bandcamp result: {release_url}")

        # Fetch the release page
        page_resp = requests.get(release_url, headers=headers, timeout=12)
        if page_resp.status_code != 200:
            print(f"  - Bandcamp page fetch failed: HTTP {page_resp.status_code}")
            return None

        # Extract JSON-LD structured data
        ld_match = re.search(
            r'<script type="application/ld\+json">?\s*(.*?)\s*</script>',
            page_resp.text, re.DOTALL
        )
        if not ld_match:
            print(f"  - Bandcamp: No ld+json found on {release_url}")
            return None

        ld = _json.loads(ld_match.group(1))

        # Extract fields from ld+json schema
        result_title  = ld.get('name', title)
        result_artist = (ld.get('byArtist') or {}).get('name', artist)
        result_album  = (ld.get('inAlbum') or {}).get('name') or ld.get('name')
        cover_url     = ld.get('image')  # Direct image URL
        keywords      = ld.get('keywords', [])  # Bandcamp tags (genres)
        date_pub      = ld.get('datePublished', '')
        # Robust year extraction: find the first 4-digit sequence (YYYY)
        year_match = re.search(r'\d{4}', date_pub)
        year = year_match.group(0) if year_match else None

        # Keywords can be a string or list
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(',')]
        # Filter out very generic/noise tags, take best 4
        genre_list = [k.strip() for k in keywords if k.strip()][:4]
        genre = ' / '.join(genre_list) if genre_list else 'Not found'

        match = {
            'artist':    result_artist,
            'title':     result_title,
            'album':     result_album,
            'year':      year,
            'genre':     genre,
            'cover_url': cover_url,
            'score':     85,  # Medium-high — title match not verified acoustically
            'source':    'Bandcamp'
        }

        print(f"  - Bandcamp found: {result_artist} - {result_title} | Genre: {genre} | Cover: {'yes' if cover_url else 'no'}")
        return match

    except Exception as e:
        print(f"  - Bandcamp search error: {e}")
        return None


def apply_tags(file_path, tags):
    """Writes ID3 tags to the MP3 file."""
    from mutagen.id3 import APIC
    try:
        audio = ID3(file_path)
    except Exception:
        audio = ID3()

    if tags.get('title'):
        audio['TIT2'] = TIT2(encoding=3, text=tags['title'])
    if tags.get('artist'):
        audio['TPE1'] = TPE1(encoding=3, text=tags['artist'])
    if tags.get('album'):
        audio['TALB'] = TALB(encoding=3, text=tags['album'])
    if tags.get('genre') and tags['genre'] != 'Not found':
        genre_values = [g.strip() for g in tags['genre'].split(' / ') if g.strip()]
        audio['TCON'] = TCON(encoding=3, text=genre_values)
    if tags.get('year'):
        audio['TYER'] = TYER(encoding=3, text=str(tags['year']))
        audio['TDRC'] = TDRC(encoding=3, text=str(tags['year']))
    if tags.get('bpm'):
        audio['TBPM'] = TBPM(encoding=3, text=str(tags['bpm']))
    if tags.get('key'):
        audio['TKEY'] = TKEY(encoding=3, text=str(tags['key']))

    # Embed cover art if available and not already present
    cover_url = tags.get('cover_url')
    has_apic = any(k.startswith('APIC') for k in audio.keys())
    if cover_url and not has_apic:
        try:
            # Use browser-like headers — works for both Discogs CDN and Bandcamp
            img_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
                'Referer': 'https://bandcamp.com/',
            }
            # Discogs also needs auth token
            if 'discogs' in cover_url.lower() or 'bcbits' not in cover_url.lower():
                img_headers['Authorization'] = f'Discogs token={DISCOGS_API_KEY}'
                img_headers['Referer'] = 'https://www.discogs.com/'
            img_resp = requests.get(cover_url, headers=img_headers, timeout=15)
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                mime = img_resp.headers.get('Content-Type', 'image/jpeg').split(';')[0]
                audio['APIC:'] = APIC(
                    encoding=3,
                    mime=mime,
                    type=3,   # 3 = Front Cover
                    desc='',  # Empty desc = key is 'APIC:' for easy retrieval
                    data=img_resp.content
                )
                print(f"  - Cover art embedded ({len(img_resp.content)//1024}KB) from {cover_url[:40]}...")
            else:
                print(f"  - Cover art download failed: HTTP {img_resp.status_code}, size {len(img_resp.content)}")
        except Exception as e:
            print(f"  - Cover art download error: {e}")

    audio.save(file_path)
    return True

def get_audio_metadata(file_path):
    """Reads basic ID3 tags from an MP3 file."""
    try:
        audio = ID3(file_path)
        return {
            'artist': str(audio.get('TPE1', '')),
            'title': str(audio.get('TIT2', '')),
            'album': str(audio.get('TALB', '')),
            'genre': str(audio.get('TCON', '')),
            'year': str(audio.get('TYER', '') or audio.get('TDRC', ''))
        }
    except Exception as e:
        print(f"Error reading metadata from {file_path}: {e}")
        return None

def apply_tags_to_file(file_path, tags):
    """Manually apply specific tags to an MP3 file."""
    try:
        try:
            audio = ID3(file_path)
        except Exception:
            audio = ID3()
            
        if tags.get('artist'): audio['TPE1'] = TPE1(encoding=3, text=tags['artist'])
        if tags.get('title'): audio['TIT2'] = TIT2(encoding=3, text=tags['title'])
        if tags.get('album'): audio['TALB'] = TALB(encoding=3, text=tags['album'])
        if tags.get('genre'):
            genre_str = tags['genre']
            genre_values = [g.strip() for g in genre_str.split(' / ') if g.strip()]
            audio['TCON'] = TCON(encoding=3, text=genre_values)
            
            # Proactive: Try to extract BPM/Key from the genre string if not explicitly provided
            pattern_bpm = re.compile(r'(\d+(?:\.\d+)?)\s*BPM', re.IGNORECASE)
            for g in genre_values:
                # BPM extraction
                if not tags.get('bpm'):
                    m = pattern_bpm.search(g)
                    if m: audio['TBPM'] = TBPM(encoding=3, text=m.group(1))
                
                # Key extraction (usually looks like 'Am', '1A', 'G#min', etc.)
                # This is tricky without a full list, but we can look for common DJ key formats
                # if it's a separate atom and not 'BPM' or 'Genre'
                if not tags.get('key') and (re.match(r'^[1-9][0-2]?[AB]$', g) or re.match(r'^[A-G][#b]?(?:m|maj|min|maj)?$', g)):
                     audio['TKEY'] = TKEY(encoding=3, text=g)
        if tags.get('year'):
            year_val = str(tags['year'])
            audio['TYER'] = TYER(encoding=3, text=year_val)
            audio['TDRC'] = TDRC(encoding=3, text=year_val)
        
        # Also handle BPM/Key if they came in tags (e.g. from scrapers or manual entry in genre)
        if tags.get('bpm'):
            audio['TBPM'] = TBPM(encoding=3, text=str(tags['bpm']))
        if tags.get('key'):
            audio['TKEY'] = TKEY(encoding=3, text=str(tags['key']))
            
        # Embed cover art if provided
        cover_url = tags.get('cover_url')
        if cover_url:
            try:
                from mutagen.id3 import APIC
                # If cover_url is a local path (uploaded), or starts with http
                if cover_url.startswith('http'):
                    # Use browser-like headers
                    img_headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
                    }
                    if 'discogs' in cover_url.lower():
                        img_headers['Authorization'] = f'Discogs token={DISCOGS_API_KEY}'
                    img_resp = requests.get(cover_url, headers=img_headers, timeout=15)
                    if img_resp.status_code == 200:
                        img_data = img_resp.content
                        mime = img_resp.headers.get('Content-Type', 'image/jpeg').split(';')[0]
                    else:
                        img_data = None
                elif cover_url.startswith('/api/cover/uploaded/'):
                    # Resolve web URL to local file path
                    filename = cover_url.split('/')[-1]
                    cover_path = Path(__file__).parent.parent / "covers" / "uploaded" / filename
                    if cover_path.exists():
                        img_data = cover_path.read_bytes()
                        import mimetypes
                        mime, _ = mimetypes.guess_type(str(cover_path))
                        mime = mime or 'image/jpeg'
                    else:
                        img_data = None
                else:
                    # Assume local file path or other
                    cover_path = Path(cover_url)
                    if cover_path.exists():
                        img_data = cover_path.read_bytes()
                        import mimetypes
                        mime, _ = mimetypes.guess_type(str(cover_path))
                        mime = mime or 'image/jpeg'
                    else:
                        img_data = None

                if img_data:
                    # Remove old APIC frames to ensure the new one replaces them
                    audio.delall('APIC')
                    audio['APIC:'] = APIC(
                        encoding=3,
                        mime=mime,
                        type=3,   # 3 = Front Cover
                        desc='',
                        data=img_data
                    )
                    print(f"  - Manual cover art embedded ({len(img_data)//1024}KB)")
            except Exception as e:
                print(f"  - Manual cover art error: {e}")
            
        audio.save(file_path)
        return True
    except Exception as e:
        print(f"ERROR applying tags: {e}")
        return False


# rename_track_file removed

def search_musicbrainz(artist, title):
    """Searches MusicBrainz directly for artist and title."""
    if not artist or not title:
        return None
        
    try:
        # User-Agent is required by MusicBrainz API policy
        headers = {'User-Agent': 'AutoTaggerPremium/1.0 ( contact@example.com )'}
        query = f'artist:"{artist}" AND recording:"{title}"'
        url = f"https://musicbrainz.org/ws/2/recording?query={requests.utils.quote(query)}&fmt=json"
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        data = response.json()
        recordings = data.get('recordings', [])
        
        if not recordings:
            return None
            
        # Take the first (best) match
        rec = recordings[0]
        # Calculate a simple score based on confidence or just set a standard high score
        # MusicBrainz doesn't provide a 0-100 score in the same way AcoustID does, 
        # but if we found a recording via direct query, it's usually a good match.
        
        res_artist = "Unknown Artist"
        if rec.get('artist-credit'):
            res_artist = rec['artist-credit'][0].get('name', "Unknown Artist")
            
        match = {
            'artist': res_artist,
            'title': rec.get('title', "Unknown Title"),
            'score': 90, # High confidence for direct search
            'source': 'MusicBrainz (Direct Search)',
            'genre': 'Not found'
        }

        # Extract tags as genres
        tags = rec.get('tags', [])
        if tags:
            genre_list = [t.get('name') for t in tags if t.get('name')]
            if genre_list:
                match['genre'] = " / ".join(genre_list[:3])
        
        # Try to find album info
        releases = rec.get('releases', [])
        if releases:
            match['album'] = releases[0].get('title')
            date = releases[0].get('date')
            if date:
                match['year'] = date.split('-')[0]
                
        return match
    except Exception as e:
        print(f"MusicBrainz search error: {e}")
        return None

def process_file(file_path):
    """Complete pipeline for a single file."""
    print(f"Processing: {file_path}")
    
    # Capture original tags
    original_tags = {'artist': None, 'title': None, 'genre': None}
    try:
        audio = ID3(file_path)
        original_tags['artist'] = str(audio.get('TPE1', ''))
        original_tags['title'] = str(audio.get('TIT2', ''))
        original_tags['genre'] = str(audio.get('TCON', ''))
    except Exception:
        pass

    duration, fingerprint_or_error = get_fingerprint(file_path)
    
    if duration is None:
        return {'status': 'error', 'message': f'Fingerprint failed: {fingerprint_or_error}', 'original': original_tags}
    
    fingerprint = fingerprint_or_error

    # --- Step 1: AcoustID fingerprint lookup ---
    acoustid_metadata = lookup_metadata(duration, fingerprint)
    metadata = acoustid_metadata

    # --- Step 2: parse filename for search queries ---
    file_info = search_by_filename(file_path)

    # Determine artist/title for API searches
    search_artist = None
    search_title = None
    catalog_id = None
    if acoustid_metadata:
        search_artist = acoustid_metadata.get('artist')
        search_title = acoustid_metadata.get('title')
    
    if file_info:
        search_artist = search_artist or file_info.get('artist')
        search_title = search_title or file_info.get('title')
        catalog_id = file_info.get('catalog_id')

    # --- Step 2b: Fallback to internal ID3 tags if still missing ---
    if not search_artist and original_tags.get('artist'):
        search_artist = original_tags.get('artist')
    if not search_title and original_tags.get('title'):
        search_title = original_tags.get('title')

    # --- Step 3: Discogs (Primary API) ---
    if search_artist and search_title:
        print(f"  - Searching Discogs for: {search_artist} - {search_title}")
        discogs_metadata = search_discogs(search_artist, search_title)
        if discogs_metadata:
            # Discogs wins — prefer it for genre/style accuracy
            # Keep AcoustID title if it found one (more precise for tracks vs. albums)
            if acoustid_metadata:
                discogs_metadata['title'] = acoustid_metadata.get('title', discogs_metadata['title'])
                discogs_metadata['artist'] = acoustid_metadata.get('artist', discogs_metadata['artist'])
            metadata = discogs_metadata

    # --- Step 4: Techno-Specific Sources (Beatport, Traxsource, Juno) ---
    # Trigger if Discogs missed or score is low
    if (not metadata or float(metadata.get('score', 0)) <= 90) and (search_artist or catalog_id):
        # Beatport
        print(f"  - Checking Beatport...")
        bp_metadata = search_beatport(search_artist, search_title, catalog_id)
        if bp_metadata:
            if not metadata: metadata = bp_metadata
            else:
                metadata['genre'] = bp_metadata.get('genre', metadata.get('genre'))
                metadata['source'] = f"{metadata.get('source')} + Beatport"
                if not metadata.get('cover_url'): metadata['cover_url'] = bp_metadata.get('cover_url')
        
        # Traxsource
        if (not metadata or metadata.get('genre') == 'Not found'):
            print(f"  - Checking Traxsource...")
            tx_metadata = search_traxsource(search_artist, search_title, catalog_id)
            if tx_metadata:
                if not metadata: metadata = tx_metadata
                else:
                    metadata['genre'] = tx_metadata.get('genre', metadata.get('genre'))
                    metadata['source'] = f"{metadata.get('source')} + Traxsource"

        # Juno
        if (not metadata or metadata.get('genre') == 'Not found'):
            print(f"  - Checking Juno Download...")
            jn_metadata = search_juno(search_artist, search_title, catalog_id)
            if jn_metadata:
                if not metadata: metadata = jn_metadata
                else:
                    metadata['genre'] = jn_metadata.get('genre', metadata.get('genre'))
                    metadata['source'] = f"{metadata.get('source')} + Juno"

    # --- Step 5: MusicBrainz (Secondary API) ---
    if not metadata or metadata.get('genre') == 'Not found':
        if search_artist and search_title:
            print(f"  - Searching MusicBrainz for: {search_artist} - {search_title}")
            mb_metadata = search_musicbrainz(search_artist, search_title)
            if mb_metadata:
                if not metadata:
                    metadata = mb_metadata
                elif mb_metadata.get('genre') and mb_metadata['genre'] != 'Not found':
                    metadata['genre'] = mb_metadata['genre']
                    metadata['source'] = metadata['source'] + ' + MusicBrainz (Genre)'

    # --- Step 5b: Discogs Catalog Search Focus (Final Precision Fallback for Techno) ---
    if (not metadata or float(metadata.get('score', 0)) <= 90) and catalog_id:
        print(f"  - Catalog ID found ({catalog_id}), performing precision search...")
        cat_metadata = search_discogs_by_catno(catalog_id)
        if cat_metadata:
            # If we had a partial match, merge the precision data
            if not metadata:
                metadata = cat_metadata
            else:
                # Catalog ID is usually more accurate for labels/years/genres
                metadata.update({
                    'genre': cat_metadata.get('genre', metadata.get('genre')),
                    'label': cat_metadata.get('label', metadata.get('label')),
                    'year': cat_metadata.get('year', metadata.get('year')),
                    'source': f"{metadata['source']} + Discogs (Cat)"
                })
                if not metadata.get('cover_url'): 
                    metadata['cover_url'] = cat_metadata.get('cover_url')

    # --- Step 6: Bandcamp (fallback for unrecognized / exclusive releases) ---
    # Trigger if no metadata found OR score too low OR Discogs/MB had no genre
    if (not metadata or float(metadata.get('score', 0)) <= 80) and search_artist and search_title:
        print(f"  - Trying Bandcamp for: {search_artist} - {search_title}")
        bc_metadata = search_bandcamp(search_artist, search_title)
        if bc_metadata:
            if not metadata:
                metadata = bc_metadata
            else:
                # Merge: Bandcamp fills in missing genre and cover
                if not metadata.get('genre') or metadata.get('genre') == 'Not found':
                    metadata['genre'] = bc_metadata.get('genre', metadata.get('genre'))
                if not metadata.get('cover_url'):
                    metadata['cover_url'] = bc_metadata.get('cover_url')
                metadata['source'] = metadata.get('source', '') + ' + Bandcamp'

    # --- Step 6: Filename fallback (last resort) ---
    if not metadata:
        # A file with no metadata at all
        return {'status': 'not_found', 'data': file_info, 'fingerprint': fingerprint, 'original': original_tags}

    # --- Determine Scan Status (without writing to file) ---
    # User Request: If source is 'File-Analysis (Filename)', it's 'not_found'
    if metadata.get('source') == 'File-Analysis (Filename)':
        return {'status': 'not_found', 'data': metadata, 'fingerprint': fingerprint, 'original': original_tags}
    
    # If we have a decent API match but haven't written yet
    if float(metadata.get('score', 0)) > 80:
        return {'status': 'found', 'data': metadata, 'fingerprint': fingerprint, 'original': original_tags}
    
    return {'status': 'not_found', 'data': metadata, 'fingerprint': fingerprint, 'original': original_tags}

def manual_search(query):
    """Aggregates search results from multiple providers based on a query string."""
    results = []
    
    # Simple regex to split "Artist - Title"
    search_artist = None
    search_title = query
    if " - " in query:
        parts = query.split(" - ", 1)
        search_artist = parts[0].strip()
        search_title = parts[1].strip()

    # --- 1. Discogs ---
    try:
        headers = {
            'Authorization': f'Discogs token={DISCOGS_API_KEY}',
            'User-Agent': 'AutoTaggerPremium/1.0'
        }
        params = {'type': 'release', 'per_page': 5}
        if search_artist:
            params['artist'] = search_artist
            params['track'] = search_title
        else:
            params['q'] = query
            
        resp = requests.get('https://api.discogs.com/database/search', headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            hits = resp.json().get('results', [])
            for h in hits:
                genre_list = h.get('genre', []) + h.get('style', [])
                results.append({
                    'artist': h.get('title').split(' - ')[0] if ' - ' in h.get('title', '') else search_artist or 'Unknown',
                    'title': h.get('title').split(' - ')[1] if ' - ' in h.get('title', '') else h.get('title'),
                    'album': h.get('title'),
                    'year': h.get('year'),
                    'genre': " / ".join(genre_list[:3]) if genre_list else 'Not found',
                    'cover_url': h.get('cover_image'),
                    'source': 'Discogs',
                    'url': f"https://www.discogs.com{h.get('uri')}" if h.get('uri') else None
                })
    except Exception as e:
        print(f"Manual Search: Discogs error: {e}")

    # --- 2. Beatport ---
    try:
        # Since search_beatport already performs a search, let's try to use it
        # but it returns only 1 result. For now, we'll keep it simple or expand later.
        bp = search_beatport(search_artist, search_title)
        if bp:
            results.append(bp)
    except: pass

    # --- 3. Traxsource ---
    try:
        tx = search_traxsource(search_artist, search_title)
        if tx:
            results.append(tx)
    except: pass

    # --- 4. Juno ---
    try:
        jn = search_juno(search_artist, search_title)
        if jn:
            results.append(jn)
    except: pass

    return results

if __name__ == "__main__":
    pass

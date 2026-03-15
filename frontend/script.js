/** Version: 1.1 - Icon Update **/
// ─── DOM REFERENCES ───
const trackList    = document.getElementById('track-items');
const scanBtn      = document.getElementById('scan-btn');
const autotagBtn   = document.getElementById('autotag-btn');
const clearBtn     = document.getElementById('clear-btn');
const progressBar  = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const statusLabel  = document.getElementById('status-label');
const modalOverlay = document.getElementById('modal-overlay');
const closeModal   = document.getElementById('close-modal');
const modalBody    = document.getElementById('modal-comparison-body');
const modalTrackId = document.getElementById('modal-track-id');
const editTagBtn   = document.getElementById('edit-tag-btn');
const saveTagBtn   = document.getElementById('save-tag-btn');
const cancelTagBtn = document.getElementById('cancel-tag-btn');
const editFooter   = document.getElementById('modal-edit-footer');
const restoreBtn   = document.getElementById('restore-btn');
const mainControls = document.getElementById('main-controls');
const restoreControls = document.getElementById('restore-controls');
const restoreAcceptBtn = document.getElementById('restore-accept-btn');
const restoreCancelBtn = document.getElementById('restore-cancel-btn');

// Footer player
const playerTitle    = document.getElementById('player-title');
const playerArtist   = document.getElementById('player-artist');
const playerPlay     = document.getElementById('player-play');
const playerPrev     = document.getElementById('player-prev');
const playerNext     = document.getElementById('player-next');
const playerFill     = document.getElementById('player-progress-fill');
const playerTime     = document.getElementById('player-time');
const playerProgBg   = document.getElementById('player-progress-bg');
const searchInput    = document.getElementById('search-input');
const playerCover    = document.getElementById('player-cover');
const eqCanvas       = document.getElementById('eq-canvas');
const eqCtx          = eqCanvas.getContext('2d');

// ─── STATE ───
let socket          = null;
let allTracks       = [];
let currentAudio    = null;
let currentPlayBtn  = null;
let currentTrackIdx = -1;
let isEditMode      = false;
let editingTrack    = null;
let isRestoreMode   = false;

// ─── WEB AUDIO API ───
let audioCtx   = null;
let analyser   = null;
let animFrame  = null;
let audioSource = null;

console.log("[DR.TAGGER] Script initializing...");

function stopAudio() {
    console.log("[PLAYER] Stopping audio...");
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.src = '';
        currentAudio.load();
        currentAudio = null;
    }
    if (currentPlayBtn) {
        currentPlayBtn.innerHTML = '&#9654;';
        currentPlayBtn.classList.remove('playing');
    }
    currentPlayBtn = null;
    currentTrackIdx = -1;
    stopEQ();
    hideCover();
    playerPlay.innerHTML = '&#9654;';
    playerPlay.classList.remove('is-playing');
    playerFill.style.width = '0%';
    playerTime.textContent = '0:00 / 0:00';
    playerTitle.textContent = '— No track playing —';
    playerArtist.textContent = '';
}

function setupAnalyser() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioSource) { try { audioSource.disconnect(); } catch(e){} }
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 128;           // 64 frequency bins
    analyser.smoothingTimeConstant = 0.75;
    audioSource = audioCtx.createMediaElementSource(currentAudio);
    audioSource.connect(analyser);
    analyser.connect(audioCtx.destination);
}

function startEQ() {
    eqCanvas.classList.add('eq-active');
    if (animFrame) cancelAnimationFrame(animFrame);
    const bufLen = analyser.frequencyBinCount;
    const data   = new Uint8Array(bufLen);
    const W = eqCanvas.width;
    const H = eqCanvas.height;
    const gap = 2;
    const barW = Math.floor(W / bufLen) - gap;

    function draw() {
        animFrame = requestAnimationFrame(draw);
        analyser.getByteFrequencyData(data);
        eqCtx.clearRect(0, 0, W, H);
        for (let i = 0; i < bufLen; i++) {
            const barH = Math.max(1, (data[i] / 255) * H);
            const x = i * (barW + gap);
            eqCtx.fillStyle = 'rgba(255,255,255,0.9)';
            eqCtx.fillRect(x, H - barH, barW, barH);
        }
    }
    draw();
}

function stopEQ() {
    if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null; }
    eqCanvas.classList.remove('eq-active');
    eqCtx.clearRect(0, 0, eqCanvas.width, eqCanvas.height);
}

function loadCover(filePath) {
    // Force forward slashes for URLs
    const normalized = filePath.replace(/\\/g, '/');
    const url = `/api/cover/${encodeURIComponent(normalized)}`;
    playerCover.onload  = () => playerCover.classList.add('visible');
    playerCover.onerror = () => { playerCover.classList.remove('visible'); playerCover.src = ''; };
    playerCover.src = url;
}

function hideCover() {
    playerCover.classList.remove('visible');
    playerCover.src = '';
}

function formatTime(s) {
    const m = Math.floor(s / 60);
    const sec = String(Math.floor(s % 60)).padStart(2, '0');
    return `${m}:${sec}`;
}

function updateFooter(track) {
    if (!track) {
        playerTitle.textContent  = '— No track playing —';
        playerArtist.textContent = '';
        return;
    }
    const title  = track.title  || track.file_path.split(/[\\/]/).pop();
    const artist = track.artist || '';
    playerTitle.textContent  = title;
    playerArtist.textContent = artist;
}

function playTrack(idx) {
    if (idx < 0 || idx >= allTracks.length) return;
    const track    = allTracks[idx];
    const filePath = track.file_path; // Use full relative path
    const normalized = filePath.replace(/\\/g, '/');
    const audioUrl = `/api/audio/${encodeURIComponent(normalized)}`;

    if (currentAudio) {
        currentAudio.pause();
        currentAudio.ontimeupdate = null;
        currentAudio.onended      = null;
    }
    if (currentPlayBtn) {
        currentPlayBtn.innerHTML = '&#9654;';
        currentPlayBtn.classList.remove('playing');
    }

    playerFill.style.width = '0%';
    playerTime.textContent = '0:00 / 0:00';

    currentAudio    = new Audio(audioUrl);
    currentTrackIdx = idx;
    selectTrack(idx); // Sync selection highlight

    const rows = trackList.querySelectorAll('.track-item');
    const visibleIdx = [...rows].findIndex((row, rIdx) => {
        return rIdx === idx; // Use index rather than filename matching
    });
    if (visibleIdx >= 0) {
        const btn = rows[visibleIdx].querySelector('.play-btn');
        if (btn) {
            btn.innerHTML = '&#9632;';
            btn.classList.add('playing');
            currentPlayBtn = btn;
        }
    }

    currentAudio.play();
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    setupAnalyser();
    startEQ();
    loadCover(filePath);
    playerPlay.innerHTML = '&#9646;&#9646;';
    playerPlay.classList.add('is-playing');

    currentAudio.ontimeupdate = () => {
        const pct = (currentAudio.currentTime / currentAudio.duration) * 100 || 0;
        playerFill.style.width = `${pct}%`;
        playerTime.textContent = `${formatTime(currentAudio.currentTime)} / ${formatTime(currentAudio.duration || 0)}`;
    };

    currentAudio.onended = () => {
        if (currentPlayBtn) {
            currentPlayBtn.innerHTML = '&#9654;';
            currentPlayBtn.classList.remove('playing');
        }
        stopEQ();
        hideCover();
        playerPlay.innerHTML = '&#9654;';
        playerPlay.classList.remove('is-playing');
        playerFill.style.width = '0%';
        currentAudio    = null;
        currentPlayBtn  = null;
        const next = currentTrackIdx + 1;
        if (next < allTracks.length) playTrack(next);
        else updateFooter(null);
    };
}

// ─── SEARCH ───
searchInput.addEventListener('input', () => {
    const q = searchInput.value.toLowerCase().trim();
    const rows = trackList.querySelectorAll('.track-item');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = !q || text.includes(q) ? '' : 'none';
    });
});

// ─── WEBSOCKET ───
function connectWS() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

    socket.onopen = () => {
        connStatus.textContent = '● Connected';
        connStatus.style.color = '';
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'progress') {
            const percent = data.percent !== undefined ? data.percent : (data.total ? Math.round((data.current / data.total) * 100) : 0);
            progressBar.style.width = `${percent}%`;
            progressText.textContent = `${percent}%`;
            statusLabel.textContent = data.status;

            if (data.status === 'Tagging complete!' || data.status === 'No tracks to tag.') {
                autotagBtn.disabled = false;
                scanBtn.disabled = false;
                restoreBtn.disabled = false;
                autotagBtn.textContent = 'Write Tags';
            }
        } else if (data.type === 'scan_finished') {
            scanBtn.disabled = false;
            scanBtn.textContent = 'Start Scan';
            autotagBtn.disabled = false;
            statusLabel.textContent = 'Scan complete. You can now Write Tags.';
        } else if (data.type === 'track_updated') {
            refreshTracks();
        } else if (data.type === 'error') {
            alert(`Error: ${data.message}`);
            scanBtn.disabled = false;
            autotagBtn.disabled = false;
        } else if (data.type === 'processing') {
            statusLabel.textContent = `${data.filename} (${data.current}/${data.total})`;
        }
    };

    socket.onclose = () => {
        console.log("WebSocket closed. Retrying...");
        setTimeout(connectWS, 2000);
    };
}


// ─── TRACK LIST ───
async function refreshTracks() {
    try {
        const response = await fetch('/api/tracks');
        allTracks = await response.json();
        
        // Enable restore button if there are any tracks that have been processed/written
        const hasProcessedTracks = allTracks.some(t => 
            ['tagged', 'untagged', 'manual-tagged'].includes(t.status.toLowerCase())
        );
        restoreBtn.disabled = !hasProcessedTracks;
        
        renderTracks();
    } catch (err) {
        console.error('Error fetching tracks:', err);
    }
}

function getStatusBadge(status) {
    const normalized = status.toLowerCase();
    if (normalized === 'found') return '<span class="badge badge-found">FOUND</span>';
    if (normalized === 'not_found' || normalized === 'not-found') return '<span class="badge badge-not-found">NOT FOUND</span>';
    if (normalized === 'tagged') return '<span class="badge badge-tagged">TAGGED</span>';
    if (normalized === 'manual-tagged') return '<span class="badge badge-manual-tagged">MANUAL TAGGED</span>';
    if (normalized === 'restored') return '<span class="badge badge-restored">RESTORED</span>';
    if (normalized === 'searched') return '<span class="badge badge-searched">SEARCHED</span>';
    return `<span class="badge badge-pending">${status.toUpperCase().replace(/[-_]/g, ' ')}</span>`;
}

function renderTracks() {
    trackList.innerHTML = '';
    allTracks.forEach((track, idx) => {
        const fileName  = track.file_path.split(/[\\/]/).pop();
        const origArtist = track.orig_artist || '<span class="empty">Empty</span>';
        const origTitle  = track.orig_title  || '<span class="empty">Empty</span>';
        const newArtist  = track.artist || '-';
        const newTitle   = track.title  || '-';
        const genreVal   = track.genre  || 'Not found';
        const genreClass = (genreVal === 'Not found' || track.status === 'not_found' || track.status === 'not-found') ? 'genre-tag not-found' : 'genre-tag';

        const tr = document.createElement('tr');
        tr.className = 'track-item fade-in';
        if (currentTrackIdx === idx) tr.classList.add('selected');
        
        tr.onclick = () => {
            selectTrack(idx);
        };

        const playTd = document.createElement('td');
        playTd.className = 'play-cell';
        
        if (isRestoreMode) {
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'restore-checkbox';
            cb.dataset.trackId = track.id;
            cb.onclick = (e) => e.stopPropagation();
            playTd.appendChild(cb);
        } else {
            const playBtn = document.createElement('button');
            playBtn.className = 'play-btn';
            playBtn.innerHTML = (currentTrackIdx === idx && currentAudio && !currentAudio.paused) ? '&#9632;' : '&#9654;';
            if (currentTrackIdx === idx && currentAudio && !currentAudio.paused) playBtn.classList.add('playing');
            
            playBtn.onclick = (e) => {
                e.stopPropagation();
                if (currentTrackIdx === idx && currentAudio && !currentAudio.paused) {
                    stopAudio();
                } else {
                    playTrack(idx);
                }
            };
            playTd.appendChild(playBtn);
        }
        tr.appendChild(playTd);

        const actionColHtml = isRestoreMode ? '' : `
            <div class="actions-cell">
                <button class="icon-btn search-btn" title="Manual search" onclick="event.stopPropagation(); openSearchModal(allTracks[${idx}])">🔎</button>
                <button class="icon-btn edit-track-btn" title="Edit tags" onclick="event.stopPropagation(); openComparisonModal(allTracks[${idx}])">✏</button>
            </div>
        `;

        const cells = [
            `<div style="font-weight:500">${fileName}</div>`,
            getStatusBadge(track.status),
            `<span class="dimmed">${origArtist} / ${origTitle}</span>`,
            `<div style="font-weight:500">${newArtist} / ${newTitle}</div><div class="source-tag">Source: ${track.match_source || 'Unknown'}</div>`,
            `<span class="${genreClass}">${genreVal}</span>`,
            actionColHtml
        ];
        cells.forEach(html => {
            const td = document.createElement('td');
            td.innerHTML = html;
            tr.appendChild(td);
        });

        trackList.appendChild(tr);
    });
}

function selectTrack(idx) {
    if (idx < 0 || idx >= allTracks.length) return;
    currentTrackIdx = idx;
    const track = allTracks[idx];
    updateFooter(track);
    
    // Update local cover if exists (just visual update same as playTrack)
    loadCover(track.file_path);

    // Update selection highlight in list
    const rows = trackList.querySelectorAll('.track-item');
    rows.forEach((row, i) => {
        if (i === idx) row.classList.add('selected');
        else row.classList.remove('selected');
    });
}

// ─── SCAN / AUTO-TAG / CLEAR ───
scanBtn.onclick = async () => {
    try {
        scanBtn.disabled = true;
        autotagBtn.disabled = true;
        scanBtn.textContent = 'Scanning...';
        progressBar.style.width = '0%';
        statusLabel.textContent = 'Starting scan...';
        await fetch('/api/scan', { method: 'POST' });
    } catch (err) {
        console.error('Scan error:', err);
        scanBtn.disabled = false;
        scanBtn.textContent = 'Start Scan';
    }
};

autotagBtn.onclick = async () => {
    try {
        stopAudio(); // Stop playback to release file lock
        autotagBtn.disabled = true;
        scanBtn.disabled = true;
        autotagBtn.textContent = 'Writing Tags...';
        progressBar.style.width = '0%';
        statusLabel.textContent = 'Initializing writing tags...';
        await fetch('/api/autotag', { method: 'POST' });
    } catch (err) {
        console.error('Auto-tag error:', err);
        autotagBtn.disabled = false;
        autotagBtn.textContent = 'Write Tags';
    }
};

restoreBtn.onclick = () => {
    isRestoreMode = true;
    mainControls.style.display = 'none';
    restoreControls.style.display = 'flex';
    renderTracks();
};

restoreCancelBtn.onclick = () => {
    isRestoreMode = false;
    mainControls.style.display = 'flex';
    restoreControls.style.display = 'none';
    renderTracks();
};

restoreAcceptBtn.onclick = async () => {
    const checkboxes = trackList.querySelectorAll('.restore-checkbox:checked');
    const trackIds = Array.from(checkboxes).map(cb => parseInt(cb.getAttribute('data-track-id')));

    if (trackIds.length === 0) {
        alert("Please select at least one track to restore.");
        return;
    }

    try {
        restoreAcceptBtn.disabled = true;
        restoreAcceptBtn.textContent = 'Restoring...';
        const response = await fetch('/api/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(trackIds)
        });
        const result = await response.json();
        alert(result.message);
        
        isRestoreMode = false;
        mainControls.style.display = 'flex';
        restoreControls.style.display = 'none';
        await refreshTracks();
    } catch (err) {
        console.error('Restore error:', err);
        alert("Failed to restore tracks.");
    } finally {
        restoreAcceptBtn.disabled = false;
        restoreAcceptBtn.textContent = 'Accept Restore';
    }
};

clearBtn.addEventListener('click', async () => {
    try {
        stopAudio();
        clearBtn.disabled = true;
        clearBtn.textContent = 'Clearing...';
        await fetch('/api/clear', { method: 'POST' });
        progressBar.style.width = '0%';
        statusLabel.textContent = 'List cleared.';
        await refreshTracks();
        clearBtn.disabled = false;
        clearBtn.textContent = 'Clear List';
        autotagBtn.disabled = true;
        restoreBtn.disabled = true;
    } catch (err) {
        console.error('Clear error:', err);
        clearBtn.disabled = false;
    }
});

// ─── MODAL ───
function openComparisonModal(track) {
    editingTrack = track;
    modalTrackId.value = track.id;
    isEditMode = false;
    renderModalContent();
    modalOverlay.classList.add('active');
}

closeModal.onclick = () => modalOverlay.classList.remove('active');

function renderModalContent() {
    const track = editingTrack;
    const fields = [
        { id: 'artist', label: 'Artist', old: track.orig_artist, new: track.artist },
        { id: 'title',  label: 'Title',  old: track.orig_title,  new: track.title  },
        { id: 'genre',  label: 'Genre',  old: track.orig_genre,  new: track.genre  },
        { id: 'album',  label: 'Album',  old: '-',               new: track.album  },
        { id: 'year',   label: 'Year',   old: '-',               new: track.year   }
    ];

    modalBody.innerHTML = fields.map(f => {
        const isChanged = f.old !== f.new && f.new;
        const displayVal = f.new || '';
        let afterContent = `<td class="diff-value ${isChanged ? 'diff-added' : ''}">${displayVal || '-'}</td>`;
        if (isEditMode) {
            afterContent = `<td><input type="text" data-field="${f.id}" value="${displayVal}" placeholder="Enter ${f.label}..."></td>`;
        }

        return `
            <tr>
                <td class="field-name">${f.label}</td>
                <td class="dimmed">${f.old || '-'}</td>
                ${afterContent}
            </tr>
        `;
    }).join('');

    // Add Cover comparison row
    const normalized = track.file_path.replace(/\\/g, '/');
    const beforeCover = `/api/cover/${encodeURIComponent(normalized)}`;
    const afterCover = track.cover_url || '';

    const coverRow = `
        <tr>
            <td class="field-name">COVER</td>
            <td class="dimmed" style="text-align: center;">
                <img src="${beforeCover}" class="comparison-cover" onerror="this.style.display='none'">
                <span class="empty" style="${track.has_cover ? 'display:none' : ''}">No original cover</span>
            </td>
            <td style="text-align: center;">
                <div id="cover-preview-container">
                    ${afterCover ? `<img src="${afterCover}" class="comparison-cover">` : '<span class="empty">No new cover</span>'}
                </div>
                <button class="upload-btn" onclick="triggerCoverUpload()">Upload JPG</button>
                <input type="file" id="cover-upload-input" accept=".jpg,.jpeg" style="display: none;" onchange="handleCoverUpload(event)">
            </td>
        </tr>
    `;
    modalBody.innerHTML += coverRow;

    editFooter.style.display = isEditMode ? 'flex' : 'none';
    editTagBtn.style.color = isEditMode ? 'var(--accent)' : '';
}

editTagBtn.onclick = () => { isEditMode = !isEditMode; renderModalContent(); };
cancelTagBtn.onclick = () => { isEditMode = false; renderModalContent(); };
saveTagBtn.onclick = async () => {
    const inputs = modalBody.querySelectorAll('input');
    const tags = {};
    inputs.forEach(input => { tags[input.dataset.field] = input.value.trim(); });

    try {
        saveTagBtn.disabled = true;
        const trackId = modalTrackId.value;
        const resp = await fetch(`/api/tracks/${trackId}/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(tags)
        });

        if (resp.ok) {
            isEditMode = false;
            await refreshTracks();
            editingTrack = allTracks.find(t => t.id == trackId);
            renderModalContent();
        }
    } catch (err) { console.error('Save error:', err); }
    finally { saveTagBtn.disabled = false; }
};

window.triggerCoverUpload = () => {
    document.getElementById('cover-upload-input').click();
};

window.handleCoverUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.jpg') && !file.name.toLowerCase().endsWith('.jpeg')) {
        alert("Please select a .jpg or .jpeg file.");
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const trackId = modalTrackId.value;
        const resp = await fetch(`/api/tracks/${trackId}/upload_cover`, {
            method: 'POST',
            body: formData
        });

        if (resp.ok) {
            const data = await resp.json();
            // Show preview immediately
            await refreshTracks();
            editingTrack = allTracks.find(t => t.id == trackId);
            renderModalContent();
        } else {
            const error = await resp.json();
            alert(`Upload failed: ${error.detail}`);
        }
    } catch (err) {
        console.error('Upload error:', err);
        alert("An error occurred during upload.");
    }
};

// ─── MANUAL SEARCH MODAL ───
const searchModal = document.getElementById('search-modal');
const closeSearchModal = document.getElementById('close-search-modal');
const manualSearchInput = document.getElementById('manual-search-input');
const executeSearchBtn = document.getElementById('execute-search-btn');
const searchResultsContainer = document.getElementById('search-results-container');

let searchingTrack = null;

function openSearchModal(track) {
    searchingTrack = track;
    searchModal.classList.add('active');
    
    // Pre-fill search input with filename if artist/title are missing
    let defaultQuery = "";
    if (track.artist && track.title) {
        defaultQuery = `${track.artist} - ${track.title}`;
    } else {
        // Just the base filename for the search query, without extension
        const baseName = track.file_path.split(/[\\/]/).pop();
        defaultQuery = baseName.split('.')[0];
    }
    
    manualSearchInput.value = defaultQuery;
    renderSearchPlaceholder("Enter artist and title to search...");
}

closeSearchModal.onclick = () => searchModal.classList.remove('active');

executeSearchBtn.onclick = async () => {
    const query = manualSearchInput.value.trim();
    if (!query) return;
    
    renderSearchPlaceholder("Searching...");
    executeSearchBtn.disabled = true;
    
    try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        const results = await response.json();
        renderSearchResults(results);
    } catch (err) {
        console.error('Search error:', err);
        renderSearchPlaceholder("Search failed. Try again.");
    } finally {
        executeSearchBtn.disabled = false;
    }
};

function renderSearchPlaceholder(text) {
    searchResultsContainer.innerHTML = `<div class="search-placeholder">${text}</div>`;
}

function renderSearchResults(results) {
    if (!results || results.length === 0) {
        renderSearchPlaceholder("No results found.");
        return;
    }
    
    searchResultsContainer.innerHTML = '';
    results.forEach(res => {
        const item = document.createElement('div');
        item.className = 'search-result-item';
        
        const coverImg = res.cover_url ? `<img src="${res.cover_url}" class="result-cover" />` : `<div class="result-cover"></div>`;
        
        item.innerHTML = `
            ${coverImg}
            <div class="result-info">
                <div class="result-main">${res.artist} - ${res.title}</div>
                <div class="result-meta">${res.album || ''} ${res.year ? '('+res.year+')' : ''}</div>
                <div class="result-source">${res.source || 'Unknown'} - ${res.genre || ''}</div>
            </div>
            <div class="search-result-actions">
                <button class="primary choose-btn">Choose</button>
                ${res.url ? `<a href="${res.url}" target="_blank" class="button open-btn">Open</a>` : ''}
            </div>
        `;
        
        item.querySelector('.choose-btn').onclick = () => selectSearchResult(res);
        searchResultsContainer.appendChild(item);
    });
}

async function selectSearchResult(res) {
    if (!searchingTrack) return;
    
    try {
        const response = await fetch(`/api/tracks/${searchingTrack.id}/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                artist: res.artist,
                title: res.title,
                album: res.album,
                year: res.year,
                genre: res.genre,
                cover_url: res.cover_url,
                status: 'searched'
            })
        });
        
        if (response.ok) {
            searchModal.classList.remove('active');
            refreshTracks();
        } else {
            alert("Failed to update track.");
        }
    } catch (err) {
        console.error('Select result error:', err);
    }
}

// ─── MODAL CLOSING ───
window.onclick = (e) => {
    if (e.target === modalOverlay) modalOverlay.classList.remove('active');
    if (e.target === searchModal) searchModal.classList.remove('active');
};
playerPlay.onclick = () => {
    if (!currentAudio) { 
        if (currentTrackIdx >= 0) {
            playTrack(currentTrackIdx);
        } else if (allTracks.length) {
            playTrack(0);
        }
        return; 
    }
    if (currentAudio.paused) { 
        currentAudio.play(); playerPlay.innerHTML = '&#9646;&#9646;'; playerPlay.classList.add('is-playing'); startEQ(); 
    } else { 
        currentAudio.pause(); playerPlay.innerHTML = '&#9654;'; playerPlay.classList.remove('is-playing'); stopEQ(); 
    }
};

playerPrev.onclick = () => { if (currentTrackIdx > 0) playTrack(currentTrackIdx - 1); };
playerNext.onclick = () => { if (currentTrackIdx < allTracks.length - 1) playTrack(currentTrackIdx + 1); };
playerProgBg.onclick = (e) => {
    if (!currentAudio) return;
    const rect = playerProgBg.getBoundingClientRect();
    const pct  = (e.clientX - rect.left) / rect.width;
    currentAudio.currentTime = pct * currentAudio.duration;
};

// ─── INIT ───
connectWS();
refreshTracks();

/**
 * Apple Music Downloader - Main JavaScript
 */

// Global state
let socket;
let downloads = [];
let downloadedFiles = [];  // Store downloaded files
let currentMetadata = null;  // Store current album/playlist metadata
let toastEl;
let toast;
let downloadRenderTimer = null;
const artworkCache = {};  // Persistent cache for artwork URLs

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Initialize toast
    toastEl = document.getElementById('toast');
    if (toastEl) {
        toast = new bootstrap.Toast(toastEl);
    }
    
    try {
        initializeSocket();
        loadDownloads();
        loadFiles();
        updateStatus();
        checkWrapperStatus();
        loadRecentlyPlayed();
        setupEventListeners();

        // Reconcile missed WebSocket events and stale status rows.
        setInterval(() => {
            loadDownloads();
            updateStatus();
        }, 5000);
        
        // Check for missing packages and show installation UI if needed
        checkAndInstallPackages();
    } catch (error) {
        console.error('Error during initialization:', error);
    }
    
    // Load library when section is expanded
    const libraryCollapse = document.getElementById('libraryCollapse');
    if (libraryCollapse) {
        libraryCollapse.addEventListener('show.bs.collapse', () => {
            // Show refresh button
            document.getElementById('libraryHeaderButtons')?.classList.remove('d-none');
            if (!libraryLoaded) {
                checkAuthAndLoadLibrary();
            }
        });
        libraryCollapse.addEventListener('hide.bs.collapse', () => {
            // Hide refresh button
            document.getElementById('libraryHeaderButtons')?.classList.add('d-none');
        });
    }
    
    // Toggle Downloads header buttons on collapse
    const downloadsCollapse = document.getElementById('downloadsCollapse');
    if (downloadsCollapse) {
        downloadsCollapse.addEventListener('show.bs.collapse', () => {
            document.getElementById('downloadsHeaderButtons')?.classList.remove('d-none');
        });
        downloadsCollapse.addEventListener('hide.bs.collapse', () => {
            document.getElementById('downloadsHeaderButtons')?.classList.add('d-none');
        });
    }
});

/**
 * Initialize WebSocket connection
 */
function initializeSocket() {
    socket = io();
    
    socket.on('connect', () => {
        console.log('Connected to server');
        loadDownloads();
        updateStatus();
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
    });
    
    socket.on('download_update', (data) => {
        updateDownloadInList(data);
        updateStatus();
    });
    
    socket.on('download_progress', (data) => {
        updateDownloadProgress(data);
    });
    
    // Package installation events
    socket.on('package_install_start', (data) => {
        showPackageBox();
        updatePackageProgress(data);
    });
    
    socket.on('package_install_progress', (data) => {
        updatePackageProgressItem(data);
    });
    
    socket.on('package_install_complete', (data) => {
        handlePackageInstallComplete(data);
    });
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Download form submission
    document.getElementById('downloadForm').addEventListener('submit', handleDownloadSubmit);
    
    // Parse URL button (now handles both URL and search)
    document.getElementById('parseBtn').addEventListener('click', handleSearchOrParse);
    
    // URL input - auto-resize textarea and detect batch paste
    const urlInput = document.getElementById('urlInput');
    
    urlInput.addEventListener('input', () => {
        autoResizeTextarea(urlInput);
        updateBatchIndicator();
    });
    
    urlInput.addEventListener('paste', (e) => {
        setTimeout(() => {
            autoResizeTextarea(urlInput);
            updateBatchIndicator();
            
            const value = urlInput.value.trim();
            const lines = value.split('\n').filter(l => l.trim());
            const urls = lines.filter(l => isAppleMusicUrl(l));
            
            // If multiple URLs pasted, show a toast hint
            if (urls.length > 1) {
                showToast('Batch Mode', `${urls.length} URLs detected - click Go to download all`, 'info');
            } else if (urls.length === 1 && lines.length === 1) {
                // Single URL, auto-parse
                parseUrl();
            }
        }, 100);
    });
    
    // URL input - Enter key triggers search (Shift+Enter for newline)
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSearchOrParse();
        }
    });
    
    // Clear completed button
    document.getElementById('clearCompletedBtn').addEventListener('click', clearCompleted);
    
    // Refresh files button
    document.getElementById('refreshFilesBtn').addEventListener('click', loadFiles);
    
    // Refresh library button
    document.getElementById('refreshLibraryBtn').addEventListener('click', checkAuthAndLoadLibrary);

    // Refresh recently played button
    document.getElementById('refreshRecentlyPlayedBtn')?.addEventListener('click', () => loadRecentlyPlayed(true));
    
    // Track selection buttons
    document.getElementById('selectAllTracks').addEventListener('click', selectAllTracks);
    document.getElementById('deselectAllTracks').addEventListener('click', deselectAllTracks);
    
    // Playlist view buttons
    document.getElementById('backToPlaylistsBtn').addEventListener('click', backToPlaylists);
    document.getElementById('selectAllPlaylistTracks').addEventListener('click', selectAllPlaylistTracks);
    document.getElementById('deselectAllPlaylistTracks').addEventListener('click', deselectAllPlaylistTracks);
    document.getElementById('downloadPlaylistBtn').addEventListener('click', downloadSelectedPlaylistTracks);
    
    // Search-related event listeners
    setupSearchEventListeners();
}

/**
 * Handle download form submission
 */
async function handleDownloadSubmit(e) {
    e.preventDefault();
    
    // Check if we're in artist songs mode - use dedicated handler
    if (currentArtist && currentArtistTab === 'songs' && !document.getElementById('artistDetail').classList.contains('d-none')) {
        await downloadSelectedArtistSongs();
        return;
    }
    
    const url = document.getElementById('urlInput').value.trim();
    const quality = document.getElementById('qualitySelect').value;
    
    if (!url) {
        showToast('Error', 'Please enter a URL or search term', 'danger');
        return;
    }
    
    // If it's not a URL, trigger search instead
    if (!isAppleMusicUrl(url)) {
        handleSearchOrParse();
        return;
    }
    
    // Get selected tracks if album preview is visible
    let selectedTracks = [];
    if (!document.getElementById('albumPreview').classList.contains('d-none')) {
        selectedTracks = Array.from(document.querySelectorAll('.track-checkbox:checked'))
            .map(cb => parseInt(cb.value));
        
        if (selectedTracks.length === 0) {
            showToast('Error', 'Please select at least one track', 'warning');
            return;
        }
    }
    
    const downloadBtn = document.getElementById('downloadBtn');
    downloadBtn.disabled = true;
    downloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting...';
    
    try {
        const requestBody = {
            url,
            quality
        };
        
        // Add selected tracks if any
        if (selectedTracks.length > 0) {
            requestBody.selectedTracks = selectedTracks;
        }
        
        // Pass name, artist, and artwork from current metadata if available
        if (currentMetadata) {
            const attrs = currentMetadata.data?.attributes || currentMetadata.attributes || currentMetadata;
            requestBody.name = attrs.name || attrs.collectionName || '';
            requestBody.artist = attrs.artistName || attrs.artist || '';
            // Get artwork URL
            const artworkUrl = attrs.artwork?.url || attrs.artworkUrl100 || '';
            if (artworkUrl) {
                // Use full resolution artwork (3000x3000)
                requestBody.artwork = artworkUrl.replace('{w}', '3000').replace('{h}', '3000').replace(/\d+x\d+/, '3000x3000');
            }
        }
        
        const response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Download Started', `Download ID: ${data.download_id}`, 'success');
            document.getElementById('urlInput').value = '';
            document.getElementById('urlInfo').classList.add('d-none');
            document.getElementById('albumPreview').classList.add('d-none');
            hideSearchResults();
            hideArtistDetail();
            currentMetadata = null;
            loadDownloads();
            updateStatus();
        } else {
            // Check for Docker-specific error
            if (data.docker_error) {
                showToast('Docker Not Running', 'Docker Desktop must be running for downloads to work. Click "Start Docker" in the alert above.', 'danger');
                checkWrapperStatus();  // Refresh status to show Docker alert
            } else {
                showToast('Error', data.error || 'Failed to start download', 'danger');
            }
        }
    } catch (error) {
        showToast('Error', 'Failed to connect to server', 'danger');
        console.error(error);
    } finally {
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = '<i class="bi bi-download"></i> Start Download';
    }
}

/**
 * Check if input is an Apple Music URL
 */
function isAppleMusicUrl(input) {
    return input.includes('music.apple.com') || input.includes('apple.co');
}

/**
 * Handle search or parse based on input type
 */
async function handleSearchOrParse() {
    const input = document.getElementById('urlInput').value.trim();
    
    if (!input) return;
    
    // Check for multiple lines (batch mode)
    const lines = input.split('\n').map(l => l.trim()).filter(l => l);
    
    if (lines.length > 1) {
        // Multiple lines detected - check if they're URLs
        const urls = lines.filter(l => isAppleMusicUrl(l));
        
        if (urls.length > 1) {
            // Batch mode - process all URLs
            await processBatchUrls(urls);
            return;
        }
    }
    
    // Single input mode
    const singleInput = lines[0] || input;
    
    // Hide previous results
    hideSearchResults();
    hideArtistDetail();
    
    // Reset album navigation source (user is manually typing a new query)
    albumNavigationSource = null;
    
    if (isAppleMusicUrl(singleInput)) {
        // It's a URL, parse it
        await parseUrl();
    } else {
        // It's a search query
        await performSearch(singleInput);
    }
}

/**
 * Process batch URLs automatically
 */
async function processBatchUrls(urls) {
    const parseBtn = document.getElementById('parseBtn');
    parseBtn.disabled = true;
    parseBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    
    try {
        const response = await fetch('/api/batch-download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Batch Download', `Queued ${data.queued} URLs for download`, 'success');
            document.getElementById('urlInput').value = '';
            autoResizeTextarea(document.getElementById('urlInput'));
            loadDownloads();
        } else {
            showToast('Error', 'Failed to process batch import', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to connect to server', 'danger');
    } finally {
        parseBtn.disabled = false;
        parseBtn.innerHTML = '<i class="bi bi-arrow-right"></i> Go';
    }
}

/**
 * Parse Apple Music URL
 */
async function parseUrl() {
    const url = document.getElementById('urlInput').value.trim();
    
    if (!url) return;
    
    const parseBtn = document.getElementById('parseBtn');
    parseBtn.disabled = true;
    parseBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    
    // Hide search results when parsing URL
    // Preserve artist data if navigating from artist view to album
    hideSearchResults();
    hideArtistDetail(albumNavigationSource === 'artist');
    
    try {
        const response = await fetch('/api/parse-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        
        const data = await response.json();
        
        if (data.success) {
            const info = data.info;
            const urlInfoDiv = document.getElementById('urlInfo');
            const urlInfoText = document.getElementById('urlInfoText');
            
            urlInfoText.innerHTML = `
                <span class="url-type-badge url-type-${info.type}">${info.type}</span>
                Region: <strong>${info.storefront.toUpperCase()}</strong> | 
                ID: <strong>${info.id}</strong>
            `;
            urlInfoDiv.classList.remove('d-none');
            
            // Auto-select song mode if it's a song
            if (info.type === 'song') {
                const selectMode = document.getElementById('selectMode');
                if (selectMode) selectMode.checked = false;
                document.getElementById('albumPreview').classList.add('d-none');
            } else if (info.type === 'album' || info.type === 'playlist') {
                // Fetch metadata for albums and playlists
                await fetchMetadata(url);
            }
        } else {
            document.getElementById('urlInfo').classList.add('d-none');
            document.getElementById('albumPreview').classList.add('d-none');
        }
    } catch (error) {
        console.error('Failed to parse URL:', error);
    } finally {
        parseBtn.disabled = false;
        parseBtn.innerHTML = '<i class="bi bi-arrow-right"></i> Go';
    }
}

/**
 * Fetch metadata from Apple Music API
 */
async function fetchMetadata(url) {
    try {
        const response = await fetch('/api/fetch-metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentMetadata = data;
            displayAlbumPreview(data);
        } else {
            showToast('Error', data.error || 'Failed to fetch metadata', 'warning');
            document.getElementById('albumPreview').classList.add('d-none');
        }
    } catch (error) {
        console.error('Failed to fetch metadata:', error);
        document.getElementById('albumPreview').classList.add('d-none');
    }
}

/**
 * Display album/playlist preview
 */
function displayAlbumPreview(response) {
    const previewDiv = document.getElementById('albumPreview');
    const albumArt = document.getElementById('albumArt');
    const albumTitle = document.getElementById('albumTitle');
    const albumArtist = document.getElementById('albumArtist');
    const albumYear = document.getElementById('albumYear');
    const albumTrackCount = document.getElementById('albumTrackCount');
    const tracksList = document.getElementById('tracksList');
    const albumPreviewHeader = document.getElementById('albumPreviewHeader');
    
    // Show/hide back button based on navigation source
    if (albumPreviewHeader) {
        if (albumNavigationSource) {
            albumPreviewHeader.classList.remove('d-none');
        } else {
            albumPreviewHeader.classList.add('d-none');
        }
    }
    
    // Handle both formats (iTunes API returns data wrapper)
    const metadata = response.data ? response.data : response;
    const attrs = metadata.attributes || metadata;
    const name = attrs.name || 'Unknown';
    const artist = attrs.artistName || attrs.artist || 'Unknown Artist';
    const releaseDate = attrs.releaseDate || '';
    const trackCount = attrs.trackCount || 0;
    
    // Get tracks from relationships or tracks array
    let tracks = [];
    if (metadata.relationships && metadata.relationships.tracks && metadata.relationships.tracks.data) {
        tracks = metadata.relationships.tracks.data.map((track, index) => {
            const trackAttrs = track.attributes || track;
            return {
                id: track.id || index + 1,
                number: trackAttrs.trackNumber || index + 1,
                selectionIndex: index + 1,
                name: trackAttrs.name || 'Unknown Track',
                artist: trackAttrs.artistName || artist,
                duration: Math.floor((trackAttrs.durationInMillis || 0) / 1000),
                selected: true
            };
        });
    } else if (metadata.tracks) {
        tracks = metadata.tracks;
    }
    
    // Set album info
    albumTitle.textContent = name;
    albumArtist.textContent = artist;
    albumYear.textContent = releaseDate ? new Date(releaseDate).getFullYear() : 'Unknown';
    albumTrackCount.textContent = trackCount || tracks.length;
    
    // Set artwork
    const artwork = attrs.artwork;
    if (artwork && artwork.url) {
        // Replace template dimensions with actual size
        const artworkUrl = artwork.url.replace('{w}', '600').replace('{h}', '600');
        albumArt.src = artworkUrl;
        albumArt.style.display = 'block';
    } else if (response.artwork) {
        albumArt.src = response.artwork;
        albumArt.style.display = 'block';
    } else {
        albumArt.style.display = 'none';
    }
    
    // Render tracks list
    if (tracks.length > 0) {
        tracksList.innerHTML = tracks.map((track, index) => {
            const duration = formatDuration(track.duration);
            const selectionIndex = track.selectionIndex || index + 1;
            return `
                <div class="form-check track-item">
                    <input class="form-check-input track-checkbox" type="checkbox" value="${selectionIndex}"
                           id="track-${selectionIndex}" checked>
                    <label class="form-check-label" for="track-${selectionIndex}">
                        <div>
                            <div>
                                <span class="track-number text-muted me-1">${track.number}.</span>
                                <span class="track-name">${escapeHtml(track.name)}</span>
                                ${track.artist !== artist ? `<small class="text-muted"> - ${escapeHtml(track.artist)}</small>` : ''}
                            </div>
                            <span class="track-duration text-muted small">${duration}</span>
                        </div>
                    </label>
                </div>
            `;
        }).join('');
    } else {
        tracksList.innerHTML = '<div class="text-muted p-3">No tracks found</div>';
    }
    
    previewDiv.classList.remove('d-none');
}

/**
 * Format duration in seconds to MM:SS
 */
function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Strip supported audio/video extensions from display names
 */
function stripExtension(filename) {
    if (!filename) return '';
    return filename.replace(/\.(?:m4a|mp4|flac|mp3)$/i, '');
}

/**
 * Select all tracks
 */
function selectAllTracks() {
    document.querySelectorAll('.track-checkbox').forEach(checkbox => {
        checkbox.checked = true;
    });
}

/**
 * Deselect all tracks
 */
function deselectAllTracks() {
    document.querySelectorAll('.track-checkbox').forEach(checkbox => {
        checkbox.checked = false;
    });
}

/**
 * Load downloads list
 */
async function loadDownloads() {
    try {
        const response = await fetch('/api/downloads');
        downloads = await response.json();
        renderCombinedList();
    } catch (error) {
        console.error('Failed to load downloads:', error);
    }
}

/**
 * Render combined downloads and files list
 */
function renderCombinedList() {
    const filesList = document.getElementById('filesList');
    if (!filesList) return;
    
    // Filter active downloads
    const activeDownloads = downloads.filter(d => ['queued', 'downloading', 'retrying'].includes(d.status));
    
    // Sort: queued first (oldest), then downloading (newest at bottom)
    activeDownloads.sort((a, b) => {
        if (a.status === 'queued' && b.status !== 'queued') return -1;
        if (b.status === 'queued' && a.status !== 'queued') return 1;
        return 0;
    });
    
    if (activeDownloads.length === 0 && downloadedFiles.length === 0) {
        filesList.innerHTML = '<div class="text-center text-muted py-4">No downloads yet. Add a URL above to start.</div>';
        return;
    }
    
    let html = '';
    
    // Render active downloads first
    html += activeDownloads.map(download => {
        const progress = download.progress || {};
        let percent = 0;
        let statusText = download.status === 'queued' ? 'Queued...' : 'Downloading...';
        
        if (download.status === 'downloading') {
            // Calculate progress based on tracks
            if (progress.current_track && progress.total_tracks) {
                // Base progress is completed tracks
                const completedTracks = progress.current_track - 1;
                const trackWeight = 100 / progress.total_tracks;
                percent = completedTracks * trackWeight;
                
                // Add sub-progress for current track if available
                if (progress.download_percent) {
                    percent += (progress.download_percent / 100) * trackWeight;
                }
                
                statusText = `Track ${progress.current_track}/${progress.total_tracks}`;
            } else if (progress.download_percent) {
                // Single track download
                percent = progress.download_percent;
            }
            if (progress.phase) {
                statusText = progress.phase.charAt(0).toUpperCase() + progress.phase.slice(1);
            }
        }
        
        const title = download.url_info?.name || download.url_info?.type || 'Download';
        const artist = download.url_info?.artist || '';
        const artwork = download.url_info?.artwork || '';
        
        return `
        <div class="file-item file-item-download ${download.status}" data-download-id="${download.id}" onclick="showDownloadInfo('${download.id}')">
            <div class="file-item-info">
                ${artwork ? `
                <div class="file-thumbnail download-artwork">
                    <img src="${artwork}" alt="" onerror="this.parentElement.innerHTML='<i class=\'bi bi-music-note-beamed\'></i>'">
                    ${download.status === 'downloading' ? '<div class="download-overlay"><span class="spinner-border spinner-border-sm text-light"></span></div>' : ''}
                    ${download.status === 'queued' ? '<div class="download-overlay"><i class="bi bi-hourglass-split text-light"></i></div>' : ''}
                    ${download.status === 'retrying' ? '<div class="download-overlay"><i class="bi bi-arrow-repeat text-warning"></i></div>' : ''}
                </div>
                ` : `
                <div class="file-thumbnail-placeholder download-icon">
                    ${download.status === 'downloading' 
                        ? '<span class="spinner-border spinner-border-sm text-primary"></span>'
                        : download.status === 'retrying'
                            ? '<i class="bi bi-arrow-repeat text-warning"></i>'
                            : '<i class="bi bi-hourglass-split text-muted"></i>'}
                </div>
                `}
                <div class="file-details">
                    <div class="file-name">${escapeHtml(title)}</div>
                    <div class="file-meta">
                        <span class="badge badge-${download.status} me-2">${download.status}</span>
                        ${artist ? escapeHtml(artist) + ' • ' : ''}
                        <span class="badge bg-secondary">${download.options?.quality?.toUpperCase() || 'ALAC'}</span>
                    </div>
                    ${download.status === 'downloading' || download.status === 'retrying' ? `
                    <div class="download-progress-bar mt-1">
                        <div class="progress" style="height: 4px;">
                            <div class="progress-bar ${download.status === 'retrying' ? 'bg-warning' : ''}" style="width: ${download.status === 'retrying' ? 100 : percent}%"></div>
                        </div>
                        <small class="text-muted">${download.status === 'retrying' ? 'Restarting wrapper...' : statusText}</small>
                    </div>
                    ` : ''}
                </div>
            </div>
            <div class="file-actions">
                <button class="btn btn-sm btn-outline-info" onclick="event.stopPropagation(); showOutput('${download.id}')" title="View output">
                    <i class="bi bi-terminal"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation(); removeDownload('${download.id}')" title="Remove">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>
        `;
    }).join('');
    
    // Render downloaded files
    html += downloadedFiles.map((file, index) => {
        const searchQuery = `${file.artist || ''} ${file.album || ''}`.trim();
        const displayName = stripExtension(file.name);
        
        return `
        <div class="file-item" onclick="showFileInfo(${index})">
            <div class="file-item-info">
                <div class="file-thumbnail" data-path="${escapeHtml(file.path)}" data-search="${escapeHtml(searchQuery)}">
                    <i class="bi bi-music-note-beamed"></i>
                </div>
                <div class="file-details">
                    <div class="file-name">${escapeHtml(displayName)}</div>
                    <div class="file-meta">${escapeHtml(file.artist || '')}${file.album ? ' • ' + escapeHtml(file.album) : ''} • ${formatFileSize(file.size)}</div>
                </div>
            </div>
            <button class="btn btn-sm btn-outline-secondary" onclick="event.stopPropagation(); openFileInExplorer(${index})" title="Show in Explorer">
                <i class="bi bi-folder2-open"></i>
            </button>
        </div>
        `;
    }).join('');
    
    filesList.innerHTML = html;
    
    // Load artwork thumbnails from files
    loadArtworkThumbnails();
}

/**
 * Render downloads list (legacy - calls combined render)
 */
function renderDownloadsList() {
    renderCombinedList();
}

function scheduleDownloadsRender() {
    if (downloadRenderTimer !== null) return;

    downloadRenderTimer = setTimeout(() => {
        downloadRenderTimer = null;
        renderDownloadsList();
    }, 1000);
}

/**
 * Render progress for a download
 */
function renderProgress(download) {
    if (download.status === 'queued') {
        return '<span class="text-muted">Waiting...</span>';
    }
    
    if (download.status === 'downloading') {
        const progress = download.progress || {};
        let percent = 0;
        let label = 'Downloading...';
        let songName = '';
        
        // Calculate progress based on tracks
        if (progress.current_track && progress.total_tracks) {
            const completedTracks = progress.current_track - 1;
            const trackWeight = 100 / progress.total_tracks;
            percent = completedTracks * trackWeight;
            
            if (progress.download_percent) {
                percent += (progress.download_percent / 100) * trackWeight;
            }
            
            label = `Track ${progress.current_track}/${progress.total_tracks}`;
            
            // Get song name if available
            if (progress.song_name) {
                songName = progress.song_name;
            }
        } else if (progress.download_percent) {
            percent = progress.download_percent;
        }
        
        if (progress.phase) {
            label = progress.phase.charAt(0).toUpperCase() + progress.phase.slice(1);
        }
        
        // Build the progress display with optional song name
        let progressHtml = `
            <div class="progress" style="width: 100px;">
                <div class="progress-bar" style="width: ${percent}%"></div>
            </div>
            <small class="text-muted">${label}</small>
        `;
        
        if (songName) {
            progressHtml += `<br><small class="text-muted text-truncate" style="max-width: 150px; display: inline-block;" title="${songName}">${songName}</small>`;
        }
        
        return progressHtml;
    }
    
    if (download.status === 'completed') {
        return '<i class="bi bi-check-circle text-success"></i>';
    }
    
    if (download.status === 'failed') {
        return '<i class="bi bi-x-circle text-danger"></i>';
    }
    
    return '-';
}

/**
 * Update a download in the list
 */
function updateDownloadInList(data) {
    const index = downloads.findIndex(d => d.id === data.id);
    if (index >= 0) {
        downloads[index] = data;
    } else {
        downloads.push(data);
    }
    renderDownloadsList();
    
    // Show notification for completed/failed
    if (data.status === 'completed') {
        showToast('Download Complete', `${data.url_info?.type || 'Download'} finished successfully`, 'success');
        // Auto-refresh files list when download completes
        setTimeout(() => loadFiles(), 1000);
    } else if (data.status === 'failed') {
        showToast('Download Failed', data.error || 'Download encountered an error', 'danger');
    }
}

/**
 * Update download progress
 */
function updateDownloadProgress(data) {
    const index = downloads.findIndex(d => d.id === data.id);
    if (index >= 0) {
        // Merge new progress with existing, don't overwrite with null
        if (data.progress) {
            downloads[index].progress = {
                ...downloads[index].progress,
                ...data.progress
            };
        }
        if (data.line) {
            downloads[index].output = downloads[index].output || [];
            downloads[index].output.push(data.line);
            downloads[index].output = downloads[index].output.slice(-100);
        }
        scheduleDownloadsRender();
    }
}

/**
 * Show download output in modal
 */
function showOutput(downloadId) {
    const download = downloads.find(d => d.id === downloadId);
    if (!download) return;
    
    const outputContent = document.getElementById('outputContent');
    outputContent.textContent = (download.output || []).join('\n') || 'No output available';
    
    const modal = new bootstrap.Modal(document.getElementById('outputModal'));
    modal.show();
}

/**
 * Show download info modal
 */
function showDownloadInfo(downloadId) {
    const download = downloads.find(d => d.id === downloadId);
    if (!download) return;
    
    const title = download.url_info?.name || download.url_info?.type || 'Download';
    const artist = download.url_info?.artist || 'Unknown Artist';
    
    const infoHtml = `
        <div class="mb-3">
            <h5>${escapeHtml(title)}</h5>
            <p class="text-muted mb-2">${escapeHtml(artist)}</p>
        </div>
        <table class="table table-dark table-sm">
            <tr>
                <td class="text-muted" style="width: 100px;">Status</td>
                <td><span class="badge badge-${download.status}">${download.status}</span></td>
            </tr>
            <tr>
                <td class="text-muted">Type</td>
                <td><span class="url-type-badge url-type-${download.url_info?.type || 'unknown'}">${download.url_info?.type || 'Unknown'}</span></td>
            </tr>
            <tr>
                <td class="text-muted">Quality</td>
                <td><span class="badge bg-secondary">${download.options?.quality?.toUpperCase() || 'ALAC'}</span></td>
            </tr>
            <tr>
                <td class="text-muted">URL</td>
                <td class="text-break"><a href="${download.url}" target="_blank" class="text-info">${download.url}</a></td>
            </tr>
            ${download.error ? `
            <tr>
                <td class="text-muted">Error</td>
                <td class="text-danger">${escapeHtml(download.error)}</td>
            </tr>
            ` : ''}
        </table>
        ${download.output && download.output.length > 0 ? `
        <div class="mt-3">
            <h6>Output</h6>
            <pre class="bg-black text-success p-2 rounded" style="max-height: 200px; overflow-y: auto; font-size: 0.8rem;">${escapeHtml(download.output.slice(-50).join('\n'))}</pre>
        </div>
        ` : ''}
    `;
    
    document.getElementById('infoModalTitle').textContent = 'Download Info';
    document.getElementById('infoModalBody').innerHTML = infoHtml;
    
    const modal = new bootstrap.Modal(document.getElementById('infoModal'));
    modal.show();
}

/**
 * Show file info modal
 */
function showFileInfo(fileIndex) {
    const file = downloadedFiles[fileIndex];
    if (!file) return;
    const displayName = stripExtension(file.name);
    
    const infoHtml = `
        <div class="mb-3">
            <h5>${escapeHtml(displayName)}</h5>
            <p class="text-muted mb-2">${escapeHtml(file.artist || '')}${file.album ? ' • ' + escapeHtml(file.album) : ''}</p>
        </div>
        <table class="table table-dark table-sm">
            <tr>
                <td class="text-muted" style="width: 100px;">Size</td>
                <td>${formatFileSize(file.size)}</td>
            </tr>
            <tr>
                <td class="text-muted">Format</td>
                <td>${file.path.split('.').pop().toUpperCase()}</td>
            </tr>
            <tr>
                <td class="text-muted">Path</td>
                <td class="text-break" style="font-size: 0.85rem;">${escapeHtml(file.path)}</td>
            </tr>
        </table>
        <div class="mt-3">
            <button class="btn btn-primary btn-sm" onclick="openFileInExplorer(${fileIndex})">
                <i class="bi bi-folder2-open"></i> Show in Explorer
            </button>
        </div>
    `;
    
    document.getElementById('infoModalTitle').textContent = 'File Info';
    document.getElementById('infoModalBody').innerHTML = infoHtml;
    
    const modal = new bootstrap.Modal(document.getElementById('infoModal'));
    modal.show();
}

/**
 * Remove a download
 */
async function removeDownload(downloadId) {
    try {
        await fetch(`/api/downloads/${downloadId}`, { method: 'DELETE' });
        downloads = downloads.filter(d => d.id !== downloadId);
        renderDownloadsList();
        updateStatus();
    } catch (error) {
        showToast('Error', 'Failed to remove download', 'danger');
    }
}

/**
 * Clear completed downloads
 */
async function clearCompleted() {
    const completed = downloads.filter(d => d.status === 'completed' || d.status === 'failed');
    
    for (const download of completed) {
        await removeDownload(download.id);
    }
    
    showToast('Cleared', `Removed ${completed.length} completed downloads`, 'info');
}

/**
 * Update status display
 */
async function updateStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();
        
        document.getElementById('stat-queue').textContent = status.queue_size;
        document.getElementById('stat-active').textContent = status.active_downloads;
        document.getElementById('stat-completed').textContent = status.completed_downloads;
        document.getElementById('stat-failed').textContent = status.failed_downloads;
    } catch (error) {
        console.error('Failed to update status:', error);
    }
}

/**
 * Check authentication status and load library or show sign-in
 */
async function checkAuthAndLoadLibrary() {
    const signInRequired = document.getElementById('librarySignInRequired');
    const playlistsView = document.getElementById('libraryPlaylistsView');
    const tracksView = document.getElementById('libraryTracksView');
    
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();
        
        if (data.authenticated) {
            // User is signed in via wrapper - show library
            signInRequired?.classList.add('d-none');
            playlistsView?.classList.remove('d-none');
            loadLibraryPlaylists();
        } else {
            // Not authenticated - show sign in button
            signInRequired?.classList.remove('d-none');
            playlistsView?.classList.add('d-none');
            tracksView?.classList.add('d-none');
        }
    } catch (error) {
        console.error('Error checking auth status:', error);
        // On error, try to load library anyway (may fail with better error)
        signInRequired?.classList.add('d-none');
        playlistsView?.classList.remove('d-none');
        loadLibraryPlaylists();
    }
}

/**
 * Load the user's recently played tracks.
 */
let recentlyPlayedTracks = [];

async function loadRecentlyPlayed(forceRefresh = false) {
    const rail = document.getElementById('recentlyPlayedRail');
    const refreshButton = document.getElementById('refreshRecentlyPlayedBtn');
    if (!rail) return;

    refreshButton?.setAttribute('disabled', '');
    rail.innerHTML = `
        <div class="recently-played-state text-muted">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading recently played...
        </div>
    `;

    try {
        const suffix = forceRefresh ? `?refresh=1&_=${Date.now()}` : '';
        const response = await fetch(`/api/library/recently-played${suffix}`, {
            cache: forceRefresh ? 'no-store' : 'default'
        });
        const data = await response.json();

        if (!data.success) {
            rail.innerHTML = `
                <div class="recently-played-state text-muted">
                    <i class="bi bi-person-lock me-2"></i>
                    ${escapeHtml(data.error || 'Recently played is unavailable.')}
                    <a href="/settings#wrapper-setup" class="ms-2">Settings</a>
                </div>
            `;
            return;
        }

        recentlyPlayedTracks = data.tracks || [];
        if (recentlyPlayedTracks.length === 0) {
            rail.innerHTML = `
                <div class="recently-played-state text-muted">
                    <i class="bi bi-clock-history me-2"></i>
                    No recently played tracks yet.
                </div>
            `;
            return;
        }

        rail.innerHTML = recentlyPlayedTracks.map((track, index) => `
            <article class="recently-played-item" data-recent-album-index="${index}" tabindex="0" role="button" title="Open ${escapeHtml(track.albumName || track.name)}">
                <div class="recently-played-artwork">
                    ${track.artwork
                        ? `<img src="${escapeHtml(track.artwork)}" alt="${escapeHtml(track.name)} artwork" loading="lazy">`
                        : `<div class="recently-played-placeholder"><i class="bi bi-music-note-beamed"></i></div>`
                    }
                    <button type="button" class="recently-played-download" data-recent-index="${index}" title="Choose tracks from ${escapeHtml(track.name)}" aria-label="Choose tracks from ${escapeHtml(track.name)}">
                        <i class="bi bi-download"></i>
                    </button>
                </div>
                <div class="recently-played-name" title="${escapeHtml(track.name)}">${escapeHtml(track.name)}</div>
                <div class="recently-played-artist" title="${escapeHtml(track.artistName)}">${escapeHtml(track.artistName)}</div>
            </article>
        `).join('');

        rail.querySelectorAll('[data-recent-album-index]').forEach(card => {
            const openAlbum = () => {
                const track = recentlyPlayedTracks[Number(card.dataset.recentAlbumIndex)];
                if (track?.albumId) {
                    loadAlbumFromSearch(track.albumId, track.albumName, track.artistName, false, 'recent');
                } else {
                    showToast('Album Unavailable', 'Could not find the album for this track.', 'warning');
                }
            };
            card.addEventListener('click', openAlbum);
            card.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    openAlbum();
                }
            });
        });

        rail.querySelectorAll('[data-recent-index]').forEach(button => {
            button.addEventListener('click', event => {
                event.stopPropagation();
                const track = recentlyPlayedTracks[Number(button.dataset.recentIndex)];
                if (track?.albumId) {
                    loadAlbumFromSearch(track.albumId, track.albumName, track.artistName, false, 'recent');
                }
            });
        });
    } catch (error) {
        rail.innerHTML = `
            <div class="recently-played-state text-muted">
                <i class="bi bi-wifi-off me-2"></i>
                Could not load recently played tracks.
            </div>
        `;
    } finally {
        refreshButton?.removeAttribute('disabled');
    }
}

/**
 * Load library playlists from user's Apple Music account
 */
let libraryLoaded = false;
let currentPlaylistId = null;
let currentPlaylistName = null;

async function loadLibraryPlaylists(forceRefresh = false) {
    const container = document.getElementById('libraryPlaylists');
    
    // Show loading indicator
    container.innerHTML = `
        <div class="col-12 text-center text-muted py-3">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading library...
        </div>
    `;
    
    try {
        const response = await fetch('/api/library/playlists');
        const data = await response.json();
        
        if (!data.success) {
            container.innerHTML = `
                <div class="col-12 text-center text-muted py-3">
                    <i class="bi bi-exclamation-circle me-2"></i>
                    ${data.error || 'Failed to load library'}
                </div>
            `;
            return;
        }
        
        const playlists = data.playlists || [];
        
        if (playlists.length === 0) {
            container.innerHTML = `
                <div class="col-12 text-center text-muted py-3">
                    No playlists found in your library
                </div>
            `;
            return;
        }
        
        container.innerHTML = playlists.map(playlist => `
            <div class="col-6 col-md-4 col-lg-3 col-xl-2">
                <div class="library-playlist-card" data-playlist-id="${escapeHtml(playlist.id)}" data-playlist-name="${escapeHtml(playlist.name)}" data-artwork="${playlist.artwork || ''}" onclick="openPlaylistModal(this)">
                    <div class="library-playlist-art">
                        ${playlist.artwork 
                            ? `<img src="${playlist.artwork}" alt="${escapeHtml(playlist.name)}" loading="lazy">`
                            : `<div class="library-playlist-placeholder"><i class="bi bi-music-note-list"></i></div>`
                        }
                    </div>
                    <div class="library-playlist-name">${escapeHtml(playlist.name)}</div>
                    <div class="library-playlist-meta library-playlist-count" data-playlist-id="${escapeHtml(playlist.id)}">
                        <span class="spinner-border spinner-border-sm" style="width: 10px; height: 10px;"></span>
                    </div>
                </div>
            </div>
        `).join('');
        
        libraryLoaded = true;
        
        // Load track counts asynchronously
        loadPlaylistTrackCounts(playlists);
        
    } catch (error) {
        container.innerHTML = `
            <div class="col-12 text-center text-muted py-3">
                <i class="bi bi-wifi-off me-2"></i>
                Failed to connect. Is the wrapper running?
            </div>
        `;
    }
}

/**
 * Load track counts for all playlists
 */
const playlistTrackCounts = {};
async function loadPlaylistTrackCounts(playlists) {
    for (const playlist of playlists) {
        if (playlistTrackCounts[playlist.id] !== undefined) {
            // Already loaded
            updatePlaylistCountDisplay(playlist.id, playlistTrackCounts[playlist.id]);
            continue;
        }
        
        try {
            const response = await fetch(`/api/library/playlists/${playlist.id}/tracks`);
            const data = await response.json();
            
            if (data.success) {
                playlistTrackCounts[playlist.id] = data.trackCount;
                updatePlaylistCountDisplay(playlist.id, data.trackCount);
            } else {
                updatePlaylistCountDisplay(playlist.id, '?');
            }
        } catch (e) {
            updatePlaylistCountDisplay(playlist.id, '?');
        }
    }
}

/**
 * Update the track count display for a playlist
 */
function updatePlaylistCountDisplay(playlistId, count) {
    const el = document.querySelector(`.library-playlist-count[data-playlist-id="${playlistId}"]`);
    if (el) {
        el.textContent = `${count} tracks`;
    }
}

/**
 * Open the playlist view to show tracks (inline, not modal)
 */
async function openPlaylistModal(card) {
    const playlistId = card.dataset.playlistId;
    const playlistName = card.dataset.playlistName;
    const artwork = card.dataset.artwork;
    
    currentPlaylistId = playlistId;
    currentPlaylistName = playlistName;
    
    // Update header
    document.getElementById('playlistViewTitle').textContent = playlistName;
    document.getElementById('playlistViewCount').textContent = 'Loading...';
    
    const artImg = document.getElementById('playlistViewArt');
    if (artwork) {
        artImg.src = artwork;
    } else {
        artImg.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50" viewBox="0 0 50 50"><rect fill="%23333" width="50" height="50"/><text x="50%25" y="50%25" fill="%23666" font-size="20" text-anchor="middle" dy=".35em">♪</text></svg>';
    }
    
    // Show loading in tracks list
    document.getElementById('playlistTracksList').innerHTML = `
        <div class="text-center text-muted py-5">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading tracks...
        </div>
    `;
    
    // Switch views
    document.getElementById('libraryPlaylistsView').style.display = 'none';
    document.getElementById('libraryTracksView').classList.remove('d-none');
    
    // Fetch tracks
    try {
        const response = await fetch(`/api/library/playlists/${playlistId}/tracks`);
        const data = await response.json();
        
        if (!data.success) {
            document.getElementById('playlistTracksList').innerHTML = `
                <div class="text-center text-danger py-5">
                    <i class="bi bi-exclamation-circle me-2"></i>
                    ${data.error || 'Failed to load tracks'}
                </div>
            `;
            return;
        }
        
        const tracks = data.tracks || [];
        document.getElementById('playlistViewCount').textContent = `${tracks.length} tracks`;
        
        // Store tracks data for download
        window.currentPlaylistTracks = tracks;
        
        if (tracks.length === 0) {
            document.getElementById('playlistTracksList').innerHTML = `
                <div class="text-center text-muted py-5">
                    This playlist is empty
                </div>
            `;
            return;
        }
        
        document.getElementById('playlistTracksList').innerHTML = tracks.map(track => `
            <div class="playlist-track-item">
                <input type="checkbox" class="form-check-input playlist-track-checkbox" 
                       value="${track.trackNumber}" 
                       data-catalog-id="${track.catalogId || ''}" 
                       checked>
                <span class="playlist-track-number">${track.trackNumber}</span>
                ${track.artwork ? 
                    `<img src="${track.artwork}" alt="" class="playlist-track-art">` : 
                    `<div class="playlist-track-art-placeholder"><i class="bi bi-music-note"></i></div>`
                }
                <div class="playlist-track-info">
                    <div class="playlist-track-name">${escapeHtml(track.name)}</div>
                    <div class="playlist-track-artist">${escapeHtml(track.artistName)}</div>
                </div>
                <span class="playlist-track-duration">${track.duration}</span>
            </div>
        `).join('');
        
    } catch (error) {
        document.getElementById('playlistTracksList').innerHTML = `
            <div class="text-center text-danger py-5">
                <i class="bi bi-wifi-off me-2"></i>
                Failed to connect
            </div>
        `;
    }
}

/**
 * Go back to playlists view
 */
function backToPlaylists() {
    document.getElementById('libraryTracksView').classList.add('d-none');
    document.getElementById('libraryPlaylistsView').style.display = 'block';
}

/**
 * Download selected tracks from the playlist
 */
async function downloadSelectedPlaylistTracks() {
    const checkboxes = document.querySelectorAll('.playlist-track-checkbox:checked');
    const allCheckboxes = document.querySelectorAll('.playlist-track-checkbox');
    
    if (checkboxes.length === 0) {
        showToast('Error', 'Please select at least one track', 'warning');
        return;
    }
    
    // Get catalog IDs and track info from the checked checkboxes
    const tracks = window.currentPlaylistTracks || [];
    const trackInfo = Array.from(checkboxes)
        .map(cb => {
            const catalogId = cb.dataset.catalogId;
            const trackNum = parseInt(cb.value);
            const track = tracks.find(t => t.trackNumber === trackNum);
            return {
                catalogId,
                catalogType: track?.catalogType || '',
                name: track?.name || '',
                artistName: track?.artistName || '',
                artwork: track?.artwork || ''
            };
        })
        .filter(t => t.catalogId);  // Remove tracks without catalog IDs
    
    if (trackInfo.length === 0) {
        showToast('Error', 'Selected tracks are not available in Apple Music catalog', 'danger');
        return;
    }
    
    // Check if downloading all tracks from the playlist
    const isDownloadingAll = checkboxes.length === allCheckboxes.length;
    
    const quality = document.getElementById('playlistQualitySelect').value;
    
    try {
        const response = await fetch('/api/library/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                trackInfo,
                quality,
                playlistName: currentPlaylistName,
                playlistId: currentPlaylistId,
                addToAutoDownload: isDownloadingAll
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            let message = `Queued ${data.download_ids.length} tracks from: ${currentPlaylistName}`;
            if (data.skipped > 0) {
                message += ` (${data.skipped} tracks unavailable)`;
            }
            if (data.addedToAutoDownload) {
                message += ` - Added to auto-download!`;
            }
            showToast('Download Started', message, 'success');
            loadDownloads();
            updateStatus();
            
            // Go back to playlists view
            backToPlaylists();
        } else {
            showToast('Error', data.error || 'Failed to start download', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to connect to server', 'danger');
    }
}

/**
 * Select/deselect all playlist tracks
 */
function selectAllPlaylistTracks() {
    document.querySelectorAll('.playlist-track-checkbox').forEach(cb => cb.checked = true);
}

function deselectAllPlaylistTracks() {
    document.querySelectorAll('.playlist-track-checkbox').forEach(cb => cb.checked = false);
}

/**
 * Load downloaded files
 */
async function loadFiles() {
    const filesList = document.getElementById('filesList');
    
    try {
        const response = await fetch('/api/files');
        downloadedFiles = await response.json();
        
        // Render combined list (downloads + files)
        renderCombinedList();
        
    } catch (error) {
        filesList.innerHTML = '<div class="text-center text-danger py-4">Failed to load files</div>';
    }
}

/**
 * Load artwork thumbnails from audio files via server API
 */
async function loadArtworkThumbnails() {
    const thumbnails = document.querySelectorAll('.file-thumbnail[data-path]');
    
    for (const thumb of thumbnails) {
        const filePath = thumb.dataset.path;
        if (!filePath || filePath.trim() === '') continue;
        
        // Check if already has an image
        if (thumb.querySelector('img')) continue;
        
        // Check cache first
        if (filePath in artworkCache) {
            if (artworkCache[filePath]) {
                applyArtworkToElement(thumb, artworkCache[filePath]);
            }
            continue;
        }
        
        // Fetch artwork from server (extracts from actual file)
        const artworkUrl = `/api/artwork/${encodeURIComponent(filePath)}`;
        
        // Create image and test if artwork exists
        const img = document.createElement('img');
        img.src = artworkUrl;
        img.alt = 'Album artwork';
        img.onerror = () => {
            artworkCache[filePath] = null;  // Mark as no artwork
            img.remove();
        };
        img.onload = () => {
            artworkCache[filePath] = artworkUrl;  // Cache the URL
            // Hide the icon when image loads
            const icon = thumb.querySelector('i');
            if (icon) icon.style.display = 'none';
        };
        thumb.insertBefore(img, thumb.firstChild);
    }
}

/**
 * Apply artwork URL to a thumbnail element
 */
function applyArtworkToElement(thumb, artworkUrl) {
    if (thumb.querySelector('img')) return;
    
    const img = document.createElement('img');
    img.src = artworkUrl;
    img.alt = 'Album artwork';
    img.onerror = () => img.remove();
    img.onload = () => {
        const icon = thumb.querySelector('i');
        if (icon) icon.style.display = 'none';
    };
    thumb.insertBefore(img, thumb.firstChild);
}

/**
 * Apply cached artwork to thumbnail elements (for re-renders)
 */
function applyArtworkToThumbnails() {
    const thumbnails = document.querySelectorAll('.file-thumbnail[data-path]');
    
    for (const thumb of thumbnails) {
        const filePath = thumb.dataset.path;
        const artworkUrl = artworkCache[filePath];
        
        if (artworkUrl) {
            applyArtworkToElement(thumb, artworkUrl);
        }
    }
}

/**
 * Open file in explorer by index
 */
function openFileInExplorer(index) {
    const file = downloadedFiles[index];
    if (file && file.path) {
        openInExplorer(file.path);
    }
}

/**
 * Open file location in Windows Explorer
 */
async function openInExplorer(filePath) {
    try {
        const response = await fetch('/api/open-in-explorer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePath })
        });
        
        if (!response.ok) {
            const data = await response.json();
            showToast('Error', data.error || 'Failed to open file location', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to open file location', 'danger');
    }
}

/**
 * Format file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Show toast notification
 */
function showToast(title, message, type = 'info') {
    if (!toastEl || !toast) return;
    
    document.getElementById('toastTitle').textContent = title;
    document.getElementById('toastBody').textContent = message;
    
    // Update toast styling based on type
    const toastHeader = toastEl.querySelector('.toast-header');
    const icon = toastHeader.querySelector('i');
    
    icon.className = 'bi me-2';
    switch (type) {
        case 'success':
            icon.classList.add('bi-check-circle', 'text-success');
            break;
        case 'danger':
            icon.classList.add('bi-x-circle', 'text-danger');
            break;
        case 'warning':
            icon.classList.add('bi-exclamation-triangle', 'text-warning');
            break;
        default:
            icon.classList.add('bi-info-circle', 'text-info');
    }
    
    toast.show();
}

/**
 * Check wrapper status
 */
async function checkWrapperStatus() {
    const wrapperStat = document.getElementById('stat-wrapper');
    const wrapperAlert = document.getElementById('wrapperAlert');
    const dockerAlert = document.getElementById('dockerAlert');
    
    try {
        const response = await fetch('/api/wrapper-status');
        const data = await response.json();
        
        // Check Docker first
        if (!data.docker_running) {
            wrapperStat.innerHTML = '<span class="text-danger"><i class="bi bi-x-circle"></i></span>';
            if (dockerAlert) dockerAlert.style.display = 'block';
            if (wrapperAlert) wrapperAlert.style.display = 'none';
            return;
        }
        
        // Docker is running, hide that alert
        if (dockerAlert) dockerAlert.style.display = 'none';
        
        if (data.running) {
            wrapperStat.innerHTML = '<span class="text-success"><i class="bi bi-check-circle"></i></span>';
            if (wrapperAlert) wrapperAlert.style.display = 'none';
        } else {
            wrapperStat.innerHTML = '<span class="text-danger"><i class="bi bi-x-circle"></i></span>';
            if (wrapperAlert) wrapperAlert.style.display = 'block';
        }
    } catch (error) {
        wrapperStat.innerHTML = '<span class="text-warning"><i class="bi bi-question-circle"></i></span>';
    }
}

/**
 * Start Docker Desktop
 */
async function startDocker() {
    const startBtn = document.getElementById('startDockerBtn');
    const spinner = document.getElementById('dockerStartingSpinner');
    
    startBtn.disabled = true;
    startBtn.style.display = 'none';
    spinner.style.display = 'inline';
    
    try {
        const response = await fetch('/api/docker-restart', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showToast('Docker Starting', 'Docker Desktop is starting. Please wait...', 'info');
            // Poll for Docker to be ready
            pollDockerStatus();
        } else {
            showToast('Failed to Start Docker', data.error || 'Unknown error', 'danger');
            startBtn.disabled = false;
            startBtn.style.display = 'inline';
            spinner.style.display = 'none';
        }
    } catch (error) {
        showToast('Error', error.message, 'danger');
        startBtn.disabled = false;
        startBtn.style.display = 'inline';
        spinner.style.display = 'none';
    }
}

/**
 * Poll for Docker to be ready
 */
let dockerPollCount = 0;
async function pollDockerStatus() {
    dockerPollCount++;
    
    try {
        const response = await fetch('/api/docker-status');
        const data = await response.json();
        
        if (data.docker_running) {
            showToast('Docker Ready', 'Docker Desktop is now running!', 'success');
            const startBtn = document.getElementById('startDockerBtn');
            const spinner = document.getElementById('dockerStartingSpinner');
            startBtn.disabled = false;
            startBtn.style.display = 'inline';
            spinner.style.display = 'none';
            dockerPollCount = 0;
            checkWrapperStatus();
            return;
        }
    } catch (error) {
        // Ignore errors during polling
    }
    
    // Keep polling for up to 60 seconds (30 polls at 2 second intervals)
    if (dockerPollCount < 30) {
        setTimeout(pollDockerStatus, 2000);
    } else {
        showToast('Docker Timeout', 'Docker did not start in time. Try starting it manually.', 'warning');
        const startBtn = document.getElementById('startDockerBtn');
        const spinner = document.getElementById('dockerStartingSpinner');
        startBtn.disabled = false;
        startBtn.style.display = 'inline';
        spinner.style.display = 'none';
        dockerPollCount = 0;
    }
}

/**
 * Start wrapper service
 */
async function startWrapper() {
    const startBtn = document.getElementById('startWrapperBtn');
    startBtn.disabled = true;
    startBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting...';
    
    try {
        const response = await fetch('/api/wrapper-start', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showToast('Wrapper Started', 'The decryption service is now running.', 'success');
            // Wait a moment then check status
            setTimeout(checkWrapperStatus, 2000);
        } else {
            showToast('Failed to Start', data.error || 'Unknown error', 'danger');
        }
    } catch (error) {
        showToast('Error', error.message, 'danger');
    }
    
    startBtn.disabled = false;
    startBtn.innerHTML = '<i class="bi bi-play-circle"></i> Start Wrapper';
}

// Add event listeners for wrapper buttons
document.addEventListener('DOMContentLoaded', () => {
    const wrapperBtn = document.getElementById('startWrapperBtn');
    const setupBtn = document.getElementById('setupWrapperBtn');
    const dockerBtn = document.getElementById('startDockerBtn');
    
    if (wrapperBtn) {
        wrapperBtn.addEventListener('click', startWrapper);
    }
    
    if (setupBtn) {
        setupBtn.addEventListener('click', () => setupWizard.show());
    }
    
    if (dockerBtn) {
        dockerBtn.addEventListener('click', startDocker);
    }
    
    // Setup wizard form handlers
    const credForm = document.getElementById('setupCredentialsForm');
    if (credForm) {
        credForm.addEventListener('submit', (e) => {
            e.preventDefault();
            setupWizard.login();
        });
    }
    
    const tfaForm = document.getElementById('setup2FAForm');
    if (tfaForm) {
        tfaForm.addEventListener('submit', (e) => {
            e.preventDefault();
            setupWizard.submit2FA();
        });
    }
    
    // Check if first-time setup needed
    checkFirstTimeSetup();
});

/**
 * Check if first-time setup is needed
 */
async function checkFirstTimeSetup() {
    try {
        const response = await fetch('/api/wrapper-setup/check');
        const data = await response.json();
        
        if (data.needs_setup) {
            // Show setup wizard automatically on first visit
            setTimeout(() => {
                setupWizard.show();
            }, 1000);
        }
    } catch (error) {
        console.error('Failed to check setup status:', error);
    }
}

/**
 * Setup Wizard Object
 */
const setupWizard = {
    modal: null,
    currentStep: 1,
    pollInterval: null,
    
    show() {
        if (!this.modal) {
            this.modal = new bootstrap.Modal(document.getElementById('setupWizardModal'));
        }
        this.goToStep(1);
        this.modal.show();
    },
    
    hide() {
        if (this.modal) {
            this.modal.hide();
        }
    },
    
    goToStep(step) {
        // Hide all steps
        document.querySelectorAll('.setup-step').forEach(el => {
            el.style.display = 'none';
        });
        
        // Show requested step
        const stepEl = document.getElementById(`setupStep${step}`);
        if (stepEl) {
            stepEl.style.display = 'block';
            this.currentStep = step;
        }
    },
    
    togglePassword() {
        const input = document.getElementById('setupPassword');
        const icon = document.getElementById('passwordToggleIcon');
        
        if (input.type === 'password') {
            input.type = 'text';
            icon.className = 'bi bi-eye-slash';
        } else {
            input.type = 'password';
            icon.className = 'bi bi-eye';
        }
    },
    
    async login() {
        const email = document.getElementById('setupEmail').value.trim();
        const password = document.getElementById('setupPassword').value;
        const loginBtn = document.getElementById('setupLoginBtn');
        
        if (!email || !password) {
            showToast('Error', 'Please enter email and password', 'danger');
            return;
        }
        
        loginBtn.disabled = true;
        loginBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Signing in...';
        
        try {
            const response = await fetch('/api/wrapper-setup/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            
            const data = await response.json();
            
            if (data.success) {
                if (data.state === 'waiting_2fa') {
                    // Move to 2FA step
                    this.goToStep(3);
                    // Start polling for status
                    this.startPolling();
                } else if (data.state === 'success') {
                    this.onLoginSuccess();
                } else {
                    // Keep polling
                    this.goToStep(3);
                    this.startPolling();
                }
            } else {
                showToast('Login Failed', data.error || 'Unknown error', 'danger');
                document.getElementById('setupErrorMessage').textContent = data.error || 'Login failed';
                this.goToStep(5);
            }
        } catch (error) {
            showToast('Error', error.message, 'danger');
            document.getElementById('setupErrorMessage').textContent = error.message;
            this.goToStep(5);
        } finally {
            loginBtn.disabled = false;
            loginBtn.innerHTML = '<i class="bi bi-box-arrow-in-right me-2"></i>Sign In';
        }
    },
    
    startPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
        
        this.pollInterval = setInterval(async () => {
            try {
                const response = await fetch('/api/wrapper-setup/status');
                const data = await response.json();
                
                if (data.state === 'success') {
                    this.stopPolling();
                    this.onLoginSuccess();
                } else if (data.state === 'error') {
                    this.stopPolling();
                    document.getElementById('setupErrorMessage').textContent = data.message || 'Setup failed';
                    this.goToStep(5);
                }
            } catch (error) {
                console.error('Polling error:', error);
            }
        }, 2000);
    },
    
    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    },
    
    async submit2FA() {
        const code = document.getElementById('setup2FACode').value.trim();
        const btn = document.getElementById('setup2FABtn');
        const progress = document.getElementById('setupProgress');
        
        if (!code || code.length !== 6) {
            showToast('Error', 'Please enter a valid 6-digit code', 'danger');
            return;
        }
        
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Verifying...';
        progress.style.display = 'block';
        document.getElementById('setupProgressText').textContent = 'Verifying code...';
        
        try {
            const response = await fetch('/api/wrapper-setup/2fa', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code })
            });
            
            const data = await response.json();
            
            if (data.success) {
                document.getElementById('setupProgressText').textContent = 'Success! Starting service...';
                this.onLoginSuccess();
            } else {
                showToast('Verification Failed', data.error || 'Invalid code', 'danger');
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-check-circle me-2"></i>Verify Code';
                progress.style.display = 'none';
            }
        } catch (error) {
            showToast('Error', error.message, 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-check-circle me-2"></i>Verify Code';
            progress.style.display = 'none';
        }
    },
    
    async onLoginSuccess() {
        this.stopPolling();
        
        // Sync Media User Token to config
        try {
            await fetch('/api/auth/sync-token', { method: 'POST' });
            console.log('Media User Token synced to config');
        } catch (error) {
            console.error('Failed to sync Media User Token:', error);
        }
        
        // Start the wrapper service
        try {
            const response = await fetch('/api/wrapper-setup/start-service', {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.goToStep(4);
                // Update wrapper status
                setTimeout(checkWrapperStatus, 2000);
            } else {
                // Still show success - tokens are saved
                this.goToStep(4);
                showToast('Note', 'Tokens saved. You may need to start the wrapper manually.', 'warning');
            }
        } catch (error) {
            // Still show success - tokens are saved
            this.goToStep(4);
        }
    },
    
    finish() {
        this.hide();
        checkWrapperStatus();
        showToast('Ready!', 'You can now download music from Apple Music.', 'success');
    }
};

// ========================================
// Search Functionality
// ========================================

// Search state
let searchResults = null;
let currentArtist = null;
let currentSearchTab = 'all';
let currentArtistTab = 'albums';
let albumNavigationSource = null; // 'search', 'artist', or null
let previousSearchQuery = ''; // Store search query for back navigation

/**
 * Setup search-related event listeners
 */
function setupSearchEventListeners() {
    // Close search button
    const closeSearchBtn = document.getElementById('closeSearchBtn');
    if (closeSearchBtn) {
        closeSearchBtn.addEventListener('click', hideSearchResults);
    }
    
    // Back to search button (from artist detail)
    const backToSearchBtn = document.getElementById('backToSearchBtn');
    if (backToSearchBtn) {
        backToSearchBtn.addEventListener('click', () => {
            hideArtistDetail();
            showSearchResults();
        });
    }
    
    // Search tab clicks
    document.querySelectorAll('[data-search-tab]').forEach(tab => {
        tab.addEventListener('click', () => {
            currentSearchTab = tab.getAttribute('data-search-tab');
            updateSearchTabs();
            renderSearchResults();
        });
    });
    
    // Artist tab clicks
    document.querySelectorAll('[data-artist-tab]').forEach(tab => {
        tab.addEventListener('click', () => {
            currentArtistTab = tab.getAttribute('data-artist-tab');
            updateArtistTabs();
            renderArtistContent();
            
            // Update download button text based on tab
            const downloadBtn = document.getElementById('downloadBtn');
            if (currentArtistTab === 'songs') {
                updateSelectedSongCount();
            } else if (downloadBtn) {
                downloadBtn.innerHTML = '<i class="bi bi-download"></i> Start Download';
            }
        });
    });
    
    // Artist song selection buttons
    const selectAllArtistSongs = document.getElementById('selectAllArtistSongs');
    if (selectAllArtistSongs) {
        selectAllArtistSongs.addEventListener('click', () => {
            document.querySelectorAll('.artist-song-checkbox').forEach(cb => cb.checked = true);
            updateSelectedSongCount();
        });
    }
    
    const deselectAllArtistSongs = document.getElementById('deselectAllArtistSongs');
    if (deselectAllArtistSongs) {
        deselectAllArtistSongs.addEventListener('click', () => {
            document.querySelectorAll('.artist-song-checkbox').forEach(cb => cb.checked = false);
            updateSelectedSongCount();
        });
    }
    
    // Back from album button
    const backFromAlbumBtn = document.getElementById('backFromAlbumBtn');
    if (backFromAlbumBtn) {
        backFromAlbumBtn.addEventListener('click', () => {
            // Hide album preview
            document.getElementById('albumPreview').classList.add('d-none');
            document.getElementById('albumPreviewHeader').classList.add('d-none');
            
            // Restore previous search query and hide URL info
            document.getElementById('urlInput').value = previousSearchQuery;
            document.getElementById('urlInfo').classList.add('d-none');
            
            // Navigate back based on source
            if (albumNavigationSource === 'artist') {
                showArtistDetail();
            } else if (albumNavigationSource === 'search') {
                showSearchResults();
            } else if (albumNavigationSource === 'recent') {
                document.querySelector('.recently-played-section')?.scrollIntoView({ behavior: 'smooth' });
            }
            
            // Clear navigation state
            albumNavigationSource = null;
        });
    }
}

/**
 * Perform search
 */
async function performSearch(query) {
    const parseBtn = document.getElementById('parseBtn');
    parseBtn.disabled = true;
    parseBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    
    // Show search results section with loading
    const searchResultsDiv = document.getElementById('searchResults');
    searchResultsDiv.classList.remove('d-none');
    document.getElementById('searchResultsTitle').textContent = `Results for "${query}"`;
    document.getElementById('searchResultsContent').innerHTML = `
        <div class="text-center text-muted py-4">
            <span class="spinner-border spinner-border-sm"></span> Searching for "${escapeHtml(query)}"...
        </div>
    `;
    
    // Hide URL info and album preview
    document.getElementById('urlInfo').classList.add('d-none');
    document.getElementById('albumPreview').classList.add('d-none');
    
    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, type: 'all', limit: 30 })
        });
        
        const data = await response.json();
        
        if (data.success) {
            searchResults = data;
            document.getElementById('searchResultsTitle').textContent = `Results for "${query}" (${data.total})`;
            updateSearchCounts();
            currentSearchTab = 'all';
            updateSearchTabs();
            renderSearchResults();
        } else {
            document.getElementById('searchResultsContent').innerHTML = `
                <div class="search-empty-state">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>Search failed: ${escapeHtml(data.error || 'Unknown error')}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Search error:', error);
        document.getElementById('searchResultsContent').innerHTML = `
            <div class="search-empty-state">
                <i class="bi bi-wifi-off"></i>
                <p>Failed to connect to server</p>
            </div>
        `;
    } finally {
        parseBtn.disabled = false;
        parseBtn.innerHTML = '<i class="bi bi-arrow-right"></i> Go';
    }
}

/**
 * Update search result counts in tabs
 */
function updateSearchCounts() {
    if (!searchResults) return;
    
    const total = searchResults.artists.length + searchResults.albums.length + searchResults.songs.length;
    document.getElementById('searchCountAll').textContent = total;
    document.getElementById('searchCountArtists').textContent = searchResults.artists.length;
    document.getElementById('searchCountAlbums').textContent = searchResults.albums.length;
    document.getElementById('searchCountSongs').textContent = searchResults.songs.length;
}

/**
 * Update active search tab
 */
function updateSearchTabs() {
    document.querySelectorAll('[data-search-tab]').forEach(tab => {
        if (tab.getAttribute('data-search-tab') === currentSearchTab) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
}

/**
 * Render search results based on active tab
 */
function renderSearchResults() {
    if (!searchResults) return;
    
    const content = document.getElementById('searchResultsContent');
    let items = [];
    
    if (currentSearchTab === 'all') {
        // Interleave results: artists first, then albums, then songs
        items = [
            ...searchResults.artists.slice(0, 5),
            ...searchResults.albums.slice(0, 10),
            ...searchResults.songs.slice(0, 15)
        ];
    } else if (currentSearchTab === 'artists') {
        items = searchResults.artists;
    } else if (currentSearchTab === 'albums') {
        items = searchResults.albums;
    } else if (currentSearchTab === 'songs') {
        items = searchResults.songs;
    }
    
    if (items.length === 0) {
        content.innerHTML = `
            <div class="search-empty-state">
                <i class="bi bi-search"></i>
                <p>No results found</p>
            </div>
        `;
        return;
    }
    
    content.innerHTML = items.map(item => renderSearchResultItem(item)).join('');
}

/**
 * Render a single search result item
 */
function renderSearchResultItem(item) {
    const isArtist = item.type === 'artist';
    const isAlbum = item.type === 'album';
    const isSong = item.type === 'song';
    
    let artwork = '';
    if (item.artwork) {
        artwork = `<img src="${item.artwork}" class="search-result-artwork ${isArtist ? 'artist' : ''}" alt="">`;
    } else {
        const icon = isArtist ? 'bi-person' : (isAlbum ? 'bi-disc' : 'bi-music-note');
        artwork = `<div class="search-result-artwork-placeholder ${isArtist ? 'artist' : ''}"><i class="bi ${icon}"></i></div>`;
    }
    
    let meta = '';
    if (isArtist) {
        meta = item.genre || 'Artist';
    } else if (isAlbum) {
        meta = item.artist + (item.trackCount ? ` • ${item.trackCount} tracks` : '');
    } else if (isSong) {
        const duration = formatDuration(Math.floor(item.duration / 1000));
        meta = `${item.artist} • ${item.album || 'Single'} • ${duration}`;
    }
    
    const badgeClass = isArtist ? 'bg-info' : (isAlbum ? 'bg-success' : 'bg-primary');
    
    // Build click handler based on type
    let clickHandler = '';
    if (isArtist) {
        clickHandler = `onclick="loadArtistDetail('${item.id}')"`;
    } else if (isAlbum) {
        clickHandler = `onclick="loadAlbumFromSearch('${item.id}', '${escapeHtml(item.name).replace(/'/g, "\\'")}', '${escapeHtml(item.artist).replace(/'/g, "\\'")}')"`;
    } else if (isSong) {
        clickHandler = `onclick="downloadSongFromSearch('${item.id}', '${escapeHtml(item.name).replace(/'/g, "\\'")}', '${escapeHtml(item.artist).replace(/'/g, "\\'")}')"`;
    }
    
    return `
        <div class="search-result-item" ${clickHandler}>
            ${artwork}
            <div class="search-result-info">
                <div class="search-result-name">${escapeHtml(item.name)}</div>
                <div class="search-result-meta">${escapeHtml(meta)}</div>
            </div>
            <div class="search-result-type">
                <span class="badge ${badgeClass}">${item.type}</span>
            </div>
            <div class="search-result-actions">
                ${isArtist ? `<button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); loadArtistDetail('${item.id}')" title="View Artist"><i class="bi bi-arrow-right"></i></button>` : ''}
                ${isAlbum ? `<button class="btn btn-sm btn-outline-success" onclick="event.stopPropagation(); downloadAlbumDirect('${item.id}')" title="Download Album"><i class="bi bi-download"></i></button>` : ''}
                ${isSong ? `<button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); downloadSongFromSearch('${item.id}', '${escapeHtml(item.name).replace(/'/g, "\\'")}', '${escapeHtml(item.artist).replace(/'/g, "\\'")}')" title="Download Song"><i class="bi bi-download"></i></button>` : ''}
            </div>
        </div>
    `;
}

/**
 * Hide search results
 */
function hideSearchResults() {
    document.getElementById('searchResults').classList.add('d-none');
}

/**
 * Show search results
 */
function showSearchResults() {
    document.getElementById('searchResults').classList.remove('d-none');
}

/**
 * Load artist detail view
 */
async function loadArtistDetail(artistId) {
    hideSearchResults();
    
    // Show the main download form (it will be used for artist songs too)
    document.getElementById('mainDownloadControls')?.classList.remove('d-none');
    
    const artistDetailDiv = document.getElementById('artistDetail');
    artistDetailDiv.classList.remove('d-none');
    
    document.getElementById('artistDetailContent').innerHTML = `
        <div class="text-center text-muted py-4">
            <span class="spinner-border spinner-border-sm"></span> Loading artist...
        </div>
    `;
    
    try {
        const response = await fetch(`/api/artist/${artistId}`);
        const data = await response.json();
        
        if (data.success) {
            currentArtist = data;
            document.getElementById('artistDetailName').textContent = data.artist.name;
            document.getElementById('artistDetailGenre').textContent = data.artist.genre || 'Artist';
            document.getElementById('artistAlbumCount').textContent = data.albums.length;
            document.getElementById('artistSongCount').textContent = data.songs.length;
            
            currentArtistTab = 'albums';
            updateArtistTabs();
            renderArtistContent();
        } else {
            document.getElementById('artistDetailContent').innerHTML = `
                <div class="search-empty-state">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>Failed to load artist: ${escapeHtml(data.error || 'Unknown error')}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Error loading artist:', error);
        document.getElementById('artistDetailContent').innerHTML = `
            <div class="search-empty-state">
                <i class="bi bi-wifi-off"></i>
                <p>Failed to connect to server</p>
            </div>
        `;
    }
}

/**
 * Hide artist detail view
 */
function hideArtistDetail(preserveData = false) {
    document.getElementById('artistDetail').classList.add('d-none');
    document.getElementById('artistSelectionControls').classList.add('d-none');
    // Show the main download form again
    document.getElementById('mainDownloadControls')?.classList.remove('d-none');
    // Reset download button text
    const downloadBtn = document.getElementById('downloadBtn');
    if (downloadBtn) {
        downloadBtn.innerHTML = '<i class="bi bi-download"></i> Start Download';
    }
    if (!preserveData) {
        currentArtist = null;
    }
}

/**
 * Show artist detail view (for back navigation)
 */
function showArtistDetail() {
    document.getElementById('artistDetail').classList.remove('d-none');
    if (currentArtistTab === 'songs') {
        document.getElementById('artistSelectionControls').classList.remove('d-none');
        // Update download button with count
        updateSelectedSongCount();
    }
    // Re-render content in case it was cleared
    renderArtistContent();
}

/**
 * Update active artist tab
 */
function updateArtistTabs() {
    document.querySelectorAll('[data-artist-tab]').forEach(tab => {
        if (tab.getAttribute('data-artist-tab') === currentArtistTab) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
    
    // Show/hide selection controls based on tab
    const selectionControls = document.getElementById('artistSelectionControls');
    if (currentArtistTab === 'songs') {
        selectionControls.classList.remove('d-none');
    } else {
        selectionControls.classList.add('d-none');
    }
}

/**
 * Render artist content based on active tab
 */
function renderArtistContent() {
    if (!currentArtist) return;
    
    const content = document.getElementById('artistDetailContent');
    
    if (currentArtistTab === 'albums') {
        renderArtistAlbums(content);
    } else {
        renderArtistSongs(content);
    }
}

/**
 * Render artist albums grid
 */
function renderArtistAlbums(container) {
    const albums = currentArtist?.albums || [];
    
    if (albums.length === 0) {
        container.innerHTML = `
            <div class="search-empty-state">
                <i class="bi bi-disc"></i>
                <p>No albums found</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = `
        <div class="artist-albums-grid">
            ${albums.map(album => `
                <div class="artist-album-card" onclick="loadAlbumFromSearch('${album.id}', '${escapeHtml(album.name).replace(/'/g, "\\'")}', '${escapeHtml(currentArtist.artist.name).replace(/'/g, "\\'")}', true)" title="${escapeHtml(album.name)}">
                    <img src="${album.artwork || ''}" class="artist-album-artwork" alt="" onerror="this.style.display='none'">
                    <div class="artist-album-info">
                        <div class="artist-album-name">${escapeHtml(album.name)}</div>
                        <div class="artist-album-year">${album.releaseDate ? new Date(album.releaseDate).getFullYear() : ''} • ${album.trackCount || 0} tracks</div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

/**
 * Render artist songs with checkboxes
 */
function renderArtistSongs(container) {
    const songs = currentArtist?.songs || [];
    
    if (songs.length === 0) {
        container.innerHTML = `
            <div class="search-empty-state">
                <i class="bi bi-music-note"></i>
                <p>No songs found</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = songs.map((song, index) => `
        <div class="song-select-item">
            <input type="checkbox" class="form-check-input artist-song-checkbox" value="${song.id}" 
                   data-url="${song.url}" data-name="${escapeHtml(song.name)}" data-album="${escapeHtml(song.album)}" data-artwork="${song.artwork || ''}" id="artist-song-${index}"
                   onchange="updateSelectedSongCount()">
            <img src="${song.artwork || ''}" class="song-select-artwork" alt="" onerror="this.style.display='none'">
            <div class="song-select-info">
                <div class="song-select-name">${escapeHtml(song.name)}</div>
                <div class="song-select-album">${escapeHtml(song.album)}</div>
            </div>
            <div class="song-select-duration">${formatDuration(Math.floor(song.duration / 1000))}</div>
        </div>
    `).join('');
    
    updateSelectedSongCount();
}

/**
 * Update selected song count
 */
function updateSelectedSongCount() {
    const count = document.querySelectorAll('.artist-song-checkbox:checked').length;
    document.getElementById('selectedArtistSongCount').textContent = count;
    
    // Also update main download button when in artist mode
    if (currentArtist && currentArtistTab === 'songs') {
        const downloadBtn = document.getElementById('downloadBtn');
        if (downloadBtn) {
            downloadBtn.innerHTML = `<i class="bi bi-download"></i> Download (${count})`;
        }
    }
}

/**
 * Download selected artist songs
 */
async function downloadSelectedArtistSongs() {
    const checkboxes = document.querySelectorAll('.artist-song-checkbox:checked');
    
    if (checkboxes.length === 0) {
        showToast('No Selection', 'Please select at least one song', 'warning');
        return;
    }
    
    const quality = document.getElementById('qualitySelect').value;
    const config = await fetch('/api/config').then(r => r.json());
    const storefront = config.storefront || 'us';
    
    const downloadBtn = document.getElementById('downloadBtn');
    downloadBtn.disabled = true;
    downloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting...';
    
    let successCount = 0;
    let failCount = 0;
    
    for (const checkbox of checkboxes) {
        const songId = checkbox.value;
        const songName = checkbox.dataset.name;
        const songAlbum = checkbox.dataset.album || '';
        const songArtwork = checkbox.dataset.artwork || '';
        // Build URL from song ID
        const songUrl = `https://music.apple.com/${storefront}/song/${songId}`;
        
        try {
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    url: songUrl, 
                    quality,
                    name: songName,
                    artist: currentArtist?.artist?.name || '',
                    artwork: songArtwork
                })
            });
            
            const data = await response.json();
            if (data.success) {
                successCount++;
            } else {
                failCount++;
            }
        } catch (error) {
            failCount++;
        }
    }
    
    downloadBtn.disabled = false;
    downloadBtn.innerHTML = '<i class="bi bi-download"></i> Start Download';
    
    if (successCount > 0) {
        showToast('Downloads Started', `Added ${successCount} song(s) to queue`, 'success');
        loadDownloads();
        updateStatus();
    }
    if (failCount > 0) {
        showToast('Some Failed', `${failCount} song(s) failed to queue`, 'warning');
    }
    
    // Deselect all after download
    document.querySelectorAll('.artist-song-checkbox').forEach(cb => cb.checked = false);
    updateSelectedSongCount();
}

/**
 * Load album from search result and display in preview
 */
async function loadAlbumFromSearch(albumId, albumName, artistName, fromArtist = false, navigationSource = null) {
    // Track navigation source
    albumNavigationSource = navigationSource || (fromArtist ? 'artist' : 'search');
    
    // Save current search query before replacing with album URL
    previousSearchQuery = document.getElementById('urlInput').value;
    
    // Build URL and put it in the input
    const config = await fetch('/api/config').then(r => r.json());
    const storefront = config.storefront || 'us';
    const albumUrl = `https://music.apple.com/${storefront}/album/${albumId}`;
    
    document.getElementById('urlInput').value = albumUrl;
    
    // Hide search and artist detail (preserve artist data if coming from artist)
    hideSearchResults();
    hideArtistDetail(fromArtist);
    
    // Show back button header
    const albumPreviewHeader = document.getElementById('albumPreviewHeader');
    if (albumPreviewHeader) {
        albumPreviewHeader.classList.remove('d-none');
    }
    const backLabel = document.getElementById('albumPreviewBackLabel');
    if (backLabel) {
        backLabel.textContent = albumNavigationSource === 'recent' ? 'Back to Recently Played' :
            albumNavigationSource === 'artist' ? 'Back to artist' : 'Back to search';
    }
    
    // Parse and fetch metadata
    await parseUrl();
}

/**
 * Download album directly from search
 */
async function downloadAlbumDirect(albumId) {
    const config = await fetch('/api/config').then(r => r.json());
    const storefront = config.storefront || 'us';
    const albumUrl = `https://music.apple.com/${storefront}/album/${albumId}`;
    const quality = document.getElementById('qualitySelect').value;
    
    try {
        const response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: albumUrl, quality })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Download Started', 'Album added to queue', 'success');
            loadDownloads();
            updateStatus();
        } else {
            showToast('Error', data.error || 'Failed to start download', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to connect to server', 'danger');
    }
}

/**
 * Download song from search result
 */
async function downloadSongFromSearch(songId, songName, artistName) {
    const config = await fetch('/api/config').then(r => r.json());
    const storefront = config.storefront || 'us';
    const songUrl = `https://music.apple.com/${storefront}/song/${songId}`;
    const quality = document.getElementById('qualitySelect').value;
    
    try {
        const response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: songUrl, quality })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Download Started', `"${songName}" added to queue`, 'success');
            loadDownloads();
            updateStatus();
            
            // Add to history
            addToHistory({
                url: songUrl,
                title: songName,
                artist: artistName,
                type: 'song'
            });
        } else {
            showToast('Error', data.error || 'Failed to start download', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to connect to server', 'danger');
    }
}


// ========================================
// Theme Toggle
// ========================================

async function initTheme() {
    try {
        const response = await fetch('/api/theme');
        const data = await response.json();
        applyTheme(data.theme || 'dark');
    } catch (error) {
        applyTheme('dark');
    }
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    const icon = document.getElementById('themeIcon');
    if (icon) {
        icon.className = theme === 'dark' ? 'bi bi-moon-stars' : 'bi bi-sun';
    }
}

async function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    applyTheme(newTheme);
    
    try {
        await fetch('/api/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: newTheme })
        });
    } catch (error) {
        console.error('Failed to save theme:', error);
    }
}


// ========================================
// Browser Notifications
// ========================================

let notificationsEnabled = false;

async function initNotifications() {
    try {
        const config = await fetch('/api/config').then(r => r.json());
        notificationsEnabled = config.notifications?.enabled || false;
        updateNotificationIcon();
    } catch (error) {
        console.error('Failed to load notification settings:', error);
    }
}

function updateNotificationIcon() {
    const icon = document.getElementById('notificationIcon');
    if (icon) {
        icon.className = notificationsEnabled ? 'bi bi-bell-fill text-warning' : 'bi bi-bell';
    }
}

async function toggleNotifications() {
    if (!notificationsEnabled) {
        // Request permission
        if ('Notification' in window) {
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                showToast('Notifications', 'Permission denied for notifications', 'warning');
                return;
            }
        }
    }
    
    notificationsEnabled = !notificationsEnabled;
    updateNotificationIcon();
    
    try {
        const config = await fetch('/api/config').then(r => r.json());
        config.notifications = config.notifications || {};
        config.notifications.enabled = notificationsEnabled;
        
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        showToast('Notifications', notificationsEnabled ? 'Notifications enabled' : 'Notifications disabled', 'success');
    } catch (error) {
        console.error('Failed to save notification settings:', error);
    }
}

function showNotification(title, body) {
    if (notificationsEnabled && 'Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {
            body: body,
            icon: '/static/icons/icon-192.png'
        });
    }
}


// ========================================
// Search History
// ========================================

async function loadSearchHistory() {
    try {
        const response = await fetch('/api/search-history');
        const data = await response.json();
        
        const datalist = document.getElementById('searchHistoryList');
        if (datalist && data.searches) {
            datalist.innerHTML = data.searches
                .map(s => `<option value="${escapeHtml(s.query)}">`)
                .join('');
        }
    } catch (error) {
        console.error('Failed to load search history:', error);
    }
}

async function addToSearchHistory(query) {
    if (!query || query.startsWith('http')) return; // Don't save URLs
    
    try {
        await fetch('/api/search-history/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });
        loadSearchHistory();
    } catch (error) {
        console.error('Failed to add to search history:', error);
    }
}


// ========================================
// ========================================
// Favorites
// ========================================

let favoritesModal = null;

function showFavorites() {
    if (!favoritesModal) {
        favoritesModal = new bootstrap.Modal(document.getElementById('favoritesModal'));
    }
    loadFavorites();
    favoritesModal.show();
}

async function loadFavorites() {
    try {
        const response = await fetch('/api/favorites');
        const data = await response.json();
        
        renderFavoritesList('favArtistsList', data.artists || [], 'artists');
        renderFavoritesList('favAlbumsList', data.albums || [], 'albums');
        renderFavoritesList('favPlaylistsList', data.playlists || [], 'playlists');
        renderFavoritesSongsList('favSongsList', data.songs || []);
    } catch (error) {
        console.error('Failed to load favorites:', error);
    }
}

function renderFavoritesList(containerId, items, type) {
    const container = document.getElementById(containerId);
    
    if (items.length === 0) {
        container.innerHTML = '<div class="col-12 text-center text-muted py-4">No favorites yet</div>';
        return;
    }
    
    container.innerHTML = items.map(item => `
        <div class="col-6 col-md-4 col-lg-3">
            <div class="card bg-secondary bg-opacity-25 h-100">
                <img src="${item.artwork || '/static/icons/icon-192.png'}" class="card-img-top" alt="${escapeHtml(item.name)}">
                <div class="card-body p-2">
                    <h6 class="card-title mb-1 text-truncate">${escapeHtml(item.name)}</h6>
                    ${item.artist ? `<small class="text-muted text-truncate d-block">${escapeHtml(item.artist)}</small>` : ''}
                </div>
                <div class="card-footer p-2 d-flex gap-1">
                    ${item.url ? `<button class="btn btn-sm btn-danger flex-grow-1" onclick="downloadFromUrl('${item.url}')"><i class="bi bi-download"></i></button>` : ''}
                    <button class="btn btn-sm btn-outline-danger" onclick="removeFromFavorites('${type}', '${item.id}')"><i class="bi bi-heart-fill"></i></button>
                </div>
            </div>
        </div>
    `).join('');
}

function renderFavoritesSongsList(containerId, songs) {
    const container = document.getElementById(containerId);
    
    if (songs.length === 0) {
        container.innerHTML = '<div class="text-center text-muted py-4">No favorite songs yet</div>';
        return;
    }
    
    container.innerHTML = songs.map(song => `
        <div class="list-group-item list-group-item-action bg-dark d-flex justify-content-between align-items-center">
            <div>
                <strong>${escapeHtml(song.name)}</strong>
                <small class="text-muted d-block">${escapeHtml(song.artist || '')}</small>
            </div>
            <div class="btn-group btn-group-sm">
                ${song.url ? `<button class="btn btn-danger" onclick="downloadFromUrl('${song.url}')"><i class="bi bi-download"></i></button>` : ''}
                <button class="btn btn-outline-danger" onclick="removeFromFavorites('songs', '${song.id}')"><i class="bi bi-heart-fill"></i></button>
            </div>
        </div>
    `).join('');
}

async function addToFavorites(type, item) {
    try {
        await fetch('/api/favorites/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type, ...item })
        });
        showToast('Favorites', `Added to favorites`, 'success');
    } catch (error) {
        showToast('Error', 'Failed to add to favorites', 'danger');
    }
}

async function removeFromFavorites(type, id) {
    try {
        await fetch('/api/favorites/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type, id })
        });
        loadFavorites();
        showToast('Favorites', 'Removed from favorites', 'success');
    } catch (error) {
        showToast('Error', 'Failed to remove from favorites', 'danger');
    }
}

async function checkIfFavorited(type, id) {
    try {
        const response = await fetch(`/api/favorites/check?type=${type}&id=${id}`);
        const data = await response.json();
        return data.favorited;
    } catch (error) {
        return false;
    }
}


// ========================================
// Download History
// ========================================

let historyModal = null;

function showHistory() {
    if (!historyModal) {
        historyModal = new bootstrap.Modal(document.getElementById('historyModal'));
    }
    loadHistory();
    historyModal.show();
}

async function loadHistory() {
    try {
        const response = await fetch('/api/history');
        const data = await response.json();
        
        // Update stats
        document.getElementById('historyTotalDownloads').textContent = data.stats?.total_downloads || 0;
        document.getElementById('historyTotalSize').textContent = formatFileSize(data.stats?.total_size_bytes || 0);
        document.getElementById('historyAlbums').textContent = data.stats?.downloads_by_type?.albums || 0;
        document.getElementById('historySongs').textContent = data.stats?.downloads_by_type?.songs || 0;
        
        // Render history list
        const container = document.getElementById('historyList');
        const downloads = data.downloads || [];
        
        if (downloads.length === 0) {
            container.innerHTML = '<div class="text-center text-muted py-4">No download history yet</div>';
            return;
        }
        
        container.innerHTML = downloads.slice(0, 50).map(item => `
            <div class="list-group-item list-group-item-action bg-dark d-flex align-items-center">
                ${item.artwork ? `<img src="${item.artwork}" class="rounded me-3" style="width: 40px; height: 40px; object-fit: cover;">` : ''}
                <div class="flex-grow-1">
                    <strong>${escapeHtml(item.title || 'Unknown')}</strong>
                    <small class="text-muted d-block">${escapeHtml(item.artist || '')} • ${new Date(item.timestamp).toLocaleDateString()}</small>
                </div>
                ${item.url ? `<button class="btn btn-sm btn-outline-danger" onclick="downloadFromUrl('${item.url}')"><i class="bi bi-arrow-repeat"></i></button>` : ''}
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

async function addToHistory(item) {
    try {
        await fetch('/api/history/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(item)
        });
    } catch (error) {
        console.error('Failed to add to history:', error);
    }
}

async function clearHistory() {
    if (!confirm('Are you sure you want to clear all download history?')) return;
    
    try {
        await fetch('/api/history/clear', { method: 'POST' });
        loadHistory();
        showToast('History', 'Download history cleared', 'success');
    } catch (error) {
        showToast('Error', 'Failed to clear history', 'danger');
    }
}


// ========================================
// Duplicate Detection
// ========================================

async function checkDuplicate(title, artist) {
    try {
        const config = await fetch('/api/config').then(r => r.json());
        if (!config['duplicate-detection']) return null;
        
        const response = await fetch('/api/check-duplicate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, artist })
        });
        
        const data = await response.json();
        return data.has_duplicates ? data.duplicates : null;
    } catch (error) {
        return null;
    }
}


// ========================================
// Metadata Editor
// ========================================

let metadataModal = null;

function openMetadataEditor(filepath) {
    if (!metadataModal) {
        metadataModal = new bootstrap.Modal(document.getElementById('metadataModal'));
    }
    
    loadMetadata(filepath);
    metadataModal.show();
}

async function loadMetadata(filepath) {
    try {
        const response = await fetch(`/api/metadata/${encodeURIComponent(filepath)}`);
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('metadataFilePath').value = filepath;
            document.getElementById('metaTitle').value = data.metadata.title || '';
            document.getElementById('metaArtist').value = data.metadata.artist || '';
            document.getElementById('metaAlbum').value = data.metadata.album || '';
            document.getElementById('metaAlbumArtist').value = data.metadata.album_artist || '';
            document.getElementById('metaYear').value = data.metadata.year || '';
            document.getElementById('metaGenre').value = data.metadata.genre || '';
            document.getElementById('metaTrack').value = data.metadata.track_number || '';
            document.getElementById('metaDisc').value = data.metadata.disc_number || '';
        } else {
            showToast('Error', data.error || 'Failed to load metadata', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to load metadata', 'danger');
    }
}

async function saveMetadata() {
    const filepath = document.getElementById('metadataFilePath').value;
    
    const metadata = {
        title: document.getElementById('metaTitle').value,
        artist: document.getElementById('metaArtist').value,
        album: document.getElementById('metaAlbum').value,
        album_artist: document.getElementById('metaAlbumArtist').value,
        year: document.getElementById('metaYear').value,
        genre: document.getElementById('metaGenre').value,
        track_number: document.getElementById('metaTrack').value,
        disc_number: document.getElementById('metaDisc').value
    };
    
    try {
        const response = await fetch(`/api/metadata/${encodeURIComponent(filepath)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(metadata)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Metadata', 'Metadata saved successfully', 'success');
            metadataModal.hide();
        } else {
            showToast('Error', data.error || 'Failed to save metadata', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to save metadata', 'danger');
    }
}


// ========================================
// Download from URL helper
// ========================================

async function downloadFromUrl(url) {
    const quality = document.getElementById('qualitySelect')?.value || 'best';
    
    try {
        const response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, quality })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Download Started', 'Added to queue', 'success');
            loadDownloads();
        } else {
            showToast('Error', data.error || 'Failed to start download', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to connect to server', 'danger');
    }
}


// ========================================
// Format helpers
// ========================================

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}


// ========================================
// Auto-resize textarea and batch detection
// ========================================

function autoResizeTextarea(textarea) {
    if (!textarea) return;
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 150); // Max 150px
    textarea.style.height = newHeight + 'px';
}

function updateBatchIndicator() {
    const urlInput = document.getElementById('urlInput');
    const helpText = document.getElementById('urlInputHelp');
    if (!urlInput || !helpText) return;
    
    const lines = urlInput.value.split('\n').filter(l => l.trim());
    const urls = lines.filter(l => isAppleMusicUrl(l));
    
    if (urls.length > 1) {
        helpText.innerHTML = `<span class="text-warning"><i class="bi bi-collection"></i> Batch mode: ${urls.length} URLs detected. Press Go to download all.</span>`;
    } else {
        helpText.textContent = 'Paste a URL or type to search. Paste multiple URLs (one per line) for batch download.';
    }
}


// ========================================
// Package Installation System
// ========================================

async function checkAndInstallPackages() {
    try {
        const response = await fetch('/api/packages/status');
        const data = await response.json();
        
        if (data.missing && data.missing.length > 0) {
            console.log('Missing packages:', data.missing);
            showPackageBox();
            
            // Auto-start installation
            startPackageInstall();
        }
    } catch (error) {
        console.error('Error checking packages:', error);
    }
}

function showPackageBox() {
    const box = document.getElementById('packageInstallBox');
    if (box) {
        box.style.display = 'block';
        document.getElementById('packageInstallStatus').style.display = 'block';
        document.getElementById('packageInstallComplete').style.display = 'none';
        document.getElementById('packageInstallFailed').style.display = 'none';
    }
}

function hidePackageBox() {
    const box = document.getElementById('packageInstallBox');
    if (box) {
        box.style.display = 'none';
    }
}

async function startPackageInstall() {
    try {
        const response = await fetch('/api/packages/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        
        if (!data.success && data.error) {
            console.error('Package install error:', data.error);
        }
    } catch (error) {
        console.error('Error starting package install:', error);
    }
}

function updatePackageProgress(data) {
    const progressBar = document.getElementById('packageProgressBar');
    const progressText = document.getElementById('packageProgressText');
    const currentText = document.getElementById('packageCurrentText');
    const spinner = document.getElementById('packageSpinner');
    
    if (progressBar && data.total > 0) {
        const percent = (data.progress / data.total) * 100;
        progressBar.style.width = percent + '%';
    }
    
    if (progressText) {
        progressText.textContent = `${data.progress} / ${data.total} packages`;
    }
    
    if (currentText && data.current) {
        currentText.textContent = `Installing ${data.current}...`;
    }
    
    if (spinner) {
        spinner.style.display = data.running ? 'inline-block' : 'none';
    }
}

function updatePackageProgressItem(data) {
    const progressBar = document.getElementById('packageProgressBar');
    const progressText = document.getElementById('packageProgressText');
    const currentText = document.getElementById('packageCurrentText');
    
    if (progressBar && data.total > 0) {
        const percent = (data.progress / data.total) * 100;
        progressBar.style.width = percent + '%';
    }
    
    if (progressText) {
        progressText.textContent = `${data.progress} / ${data.total} packages`;
    }
    
    if (currentText) {
        if (data.status === 'installing') {
            currentText.textContent = `Installing ${data.package}...`;
        } else if (data.status === 'installed') {
            currentText.textContent = `Installed ${data.package}`;
        } else if (data.status === 'failed') {
            currentText.textContent = `Failed: ${data.package}`;
        }
    }
}

function handlePackageInstallComplete(data) {
    document.getElementById('packageSpinner').style.display = 'none';
    document.getElementById('packageInstallStatus').style.display = 'none';
    
    if (data.success) {
        document.getElementById('packageInstallComplete').style.display = 'block';
        
        if (data.needs_restart) {
            showToast('Packages Installed', 'Click "Restart Server" to apply changes', 'success');
        }
    } else {
        document.getElementById('packageInstallFailed').style.display = 'block';
        const failedList = document.getElementById('failedPackagesList');
        if (failedList && data.still_missing) {
            failedList.textContent = 'Failed: ' + data.still_missing.join(', ');
        }
    }
}

async function restartServer() {
    const btn = document.getElementById('restartServerBtn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Restarting...';
    }
    
    try {
        await fetch('/api/server/restart', { method: 'POST' });
        
        // Show reloading message
        showToast('Server Restarting', 'Page will reload in a moment...', 'info');
        
        // Wait and reload
        setTimeout(() => {
            window.location.reload();
        }, 3000);
    } catch (error) {
        console.error('Error restarting server:', error);
        // Server probably already restarted, try reloading
        setTimeout(() => {
            window.location.reload();
        }, 2000);
    }
}

function retryPackageInstall() {
    document.getElementById('packageInstallFailed').style.display = 'none';
    document.getElementById('packageInstallStatus').style.display = 'block';
    startPackageInstall();
}


// ========================================
// Initialize new features on page load
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize theme
    initTheme();
    
    // Initialize notifications
    initNotifications();
    
    // Load search history
    loadSearchHistory();
});


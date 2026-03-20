/**
 * Apple Music Downloader - Settings JavaScript
 */

const toastEl = document.getElementById('toast');
const toast = new bootstrap.Toast(toastEl);

async function shutdownProgram() {
    if (!confirm('Are you sure you want to shut down the program? You will need to restart it manually.')) return;
    const btn = document.getElementById('shutdownBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Shutting down...';
    try {
        await fetch('/api/shutdown', { method: 'POST' });
        document.body.innerHTML = '<div class="d-flex justify-content-center align-items-center" style="height:100vh"><h3 class="text-muted">Server has been shut down.</h3></div>';
    } catch (e) {
        document.body.innerHTML = '<div class="d-flex justify-content-center align-items-center" style="height:100vh"><h3 class="text-muted">Server has been shut down.</h3></div>';
    }
}

// Auto-download playlists data
let autoDownloadPlaylists = [];
let availablePlaylists = [];

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    checkAuthAndLoadAutoDownload();
    loadStats();
    loadUpdateStatus();
});

// ============================================================
// Update Functions
// ============================================================

const TWO_MONTHS_MS = 60 * 24 * 60 * 60 * 1000; // ~60 days
let pendingExeUrl = null;

async function loadUpdateStatus() {
    try {
        const response = await fetch('/api/update/status');
        const data = await response.json();

        document.getElementById('currentVersionLabel').textContent = 'v' + data.version;

        if (data.last_update_check) {
            const d = new Date(data.last_update_check);
            document.getElementById('lastCheckLabel').textContent = 'Last checked: ' + d.toLocaleDateString();
            if (Date.now() - d.getTime() > TWO_MONTHS_MS) {
                document.getElementById('updateReminderBanner').classList.remove('d-none');
            }
        } else {
            // Never checked — show reminder
            document.getElementById('updateReminderBanner').classList.remove('d-none');
        }
    } catch (e) {
        console.error('Failed to load update status:', e);
    }
}

function dismissUpdateReminder() {
    document.getElementById('updateReminderBanner').classList.add('d-none');
}

async function checkForUpdates() {
    const btn = document.getElementById('checkUpdatesBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Checking...';
    document.getElementById('updateReminderBanner')?.classList.add('d-none');
    document.getElementById('updateResult')?.classList.add('d-none');
    try {
        const response = await fetch('/api/update/check', { method: 'POST' });
        const data = await response.json();
        if (!data.success) {
            showToast('Update Check Failed', data.error, 'danger');
            return;
        }

        document.getElementById('lastCheckLabel').textContent = 'Last checked: ' + new Date().toLocaleDateString();
        const resultEl = document.getElementById('updateResult');
        const availableEl = document.getElementById('updateAvailableInfo');
        const noUpdateEl = document.getElementById('noUpdateInfo');
        resultEl.classList.remove('d-none');

        if (data.updates_available) {
            availableEl.classList.remove('d-none');
            noUpdateEl.classList.add('d-none');
            document.getElementById('updateSummary').textContent =
                `Update available: v${data.current_version} → v${data.remote_version}`;
            const notesEl = document.getElementById('releaseNotesContainer');
            notesEl.innerHTML = data.release_notes
                ? `<div class="text-muted small">${escapeHtml(data.release_notes).replace(/\n/g, '<br>')}</div>`
                : '';
            pendingExeUrl = data.exe_url;
            if (data.message && !data.exe_url) {
                document.getElementById('updateSummary').textContent += ' (' + data.message + ')';
            }
        } else {
            availableEl.classList.add('d-none');
            noUpdateEl.classList.remove('d-none');
            pendingExeUrl = null;
        }
    } catch (e) {
        showToast('Error', e.message, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Check for Updates';
    }
}

async function applyUpdate() {
    if (!pendingExeUrl) { showToast('Error', 'No EXE download available. Make sure the release has an EXE attached.', 'danger'); return; }
    if (!confirm('Download and install the update? The program will restart automatically.')) return;

    const btn = document.getElementById('applyUpdateBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Downloading...';
    document.getElementById('updateProgressSection').classList.remove('d-none');
    document.getElementById('updateProgressLabel').textContent = 'Downloading update EXE...';

    try {
        const response = await fetch('/api/update/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ exe_url: pendingExeUrl })
        });
        const data = await response.json();
        if (data.success) {
            document.getElementById('updateProgressLabel').textContent = 'Update installed! Restarting...';
            document.getElementById('updateAvailableInfo').classList.add('d-none');
            showToast('Updated', data.message, 'success');
            // Wait for the server to restart, then reload
            setTimeout(() => {
                document.getElementById('updateProgressLabel').textContent = 'Reconnecting...';
                waitForRestart();
            }, 3000);
        } else {
            showToast('Update Failed', data.error, 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-download"></i> Download & Install Update';
            document.getElementById('updateProgressSection').classList.add('d-none');
        }
    } catch (e) {
        // Server may have restarted during the request — that's expected
        document.getElementById('updateProgressLabel').textContent = 'Server is restarting...';
        setTimeout(() => waitForRestart(), 3000);
    }
}

function waitForRestart(attempts = 0) {
    if (attempts > 30) {
        document.getElementById('updateProgressLabel').textContent = 'Could not reconnect. Please refresh the page manually.';
        return;
    }
    fetch('/api/update/status').then(r => {
        if (r.ok) location.reload();
        else setTimeout(() => waitForRestart(attempts + 1), 2000);
    }).catch(() => setTimeout(() => waitForRestart(attempts + 1), 2000));
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Settings form submission
    document.getElementById('settingsForm').addEventListener('submit', saveSettings);
    
    // Save button in header
    document.getElementById('saveSettingsBtn').addEventListener('click', () => {
        document.getElementById('settingsForm').dispatchEvent(new Event('submit'));
    });
    
    // Toggle downloader path visibility based on Docker checkbox
    const dockerCheckbox = document.getElementById('useDocker');
    const pathGroup = document.getElementById('downloaderPathGroup');
    
    function updatePathVisibility() {
        if (dockerCheckbox.checked) {
            pathGroup.style.opacity = '0.5';
            document.getElementById('downloaderPath').disabled = true;
        } else {
            pathGroup.style.opacity = '1';
            document.getElementById('downloaderPath').disabled = false;
        }
    }
    
    dockerCheckbox.addEventListener('change', updatePathVisibility);
    updatePathVisibility();
    
    // Auto download add playlist button
    document.getElementById('addPlaylistBtn').addEventListener('click', addPlaylistToAutoDownload);
    
    // Initialize folder toggle states
    initializeFolderToggles();
}

/**
 * Initialize folder toggle states based on current values
 */
function initializeFolderToggles() {
    // Check each folder toggle and set initial state
    const folders = [
        { toggle: 'alacFolderEnabled', input: 'alacFolder', defaultPath: '/downloads' },
        { toggle: 'atmosFolderEnabled', input: 'atmosFolder', defaultPath: '/downloads/atmos' },
        { toggle: 'aacFolderEnabled', input: 'aacFolder', defaultPath: '/downloads/aac' },
        { toggle: 'artistFolderEnabled', input: 'artistFolderFormat', defaultPath: '{ArtistName}' },
        { toggle: 'albumFolderEnabled', input: 'albumFolderFormat', defaultPath: '{AlbumName}' }
    ];
    
    folders.forEach(({ toggle, input }) => {
        const toggleEl = document.getElementById(toggle);
        const inputEl = document.getElementById(input);
        if (toggleEl && inputEl) {
            inputEl.disabled = !toggleEl.checked;
            if (!toggleEl.checked) {
                inputEl.style.opacity = '0.5';
            }
        }
    });
    
    // Initialize playlist folder options
    const playlistFolderEnabled = document.getElementById('playlistFolderEnabled');
    if (playlistFolderEnabled) {
        togglePlaylistFolderOptions(playlistFolderEnabled.checked);
    }
}

/**
 * Toggle folder input enabled/disabled state
 */
function toggleFolderInput(inputId, enabled) {
    const input = document.getElementById(inputId);
    if (input) {
        input.disabled = !enabled;
        input.style.opacity = enabled ? '1' : '0.5';
    }
}

/**
 * Toggle playlist folder options enabled/disabled state
 */
function togglePlaylistFolderOptions(enabled) {
    const input = document.getElementById('playlistFolderFormat');
    const group = document.getElementById('playlistFolderFormatGroup');
    if (input) {
        input.disabled = !enabled;
    }
    if (group) {
        group.style.opacity = enabled ? '1' : '0.5';
    }
}

/**
 * Check authentication status and load auto-download or show sign-in
 */
async function checkAuthAndLoadAutoDownload() {
    const signInRequired = document.getElementById('autoDownloadSignInRequired');
    const content = document.getElementById('autoDownloadContent');
    
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();
        
        if (data.authenticated) {
            // User is signed in via wrapper - show auto download settings
            signInRequired?.classList.add('d-none');
            content?.classList.remove('d-none');
            loadAutoDownloadData();
        } else {
            // Not authenticated - show sign in message
            signInRequired?.classList.remove('d-none');
            content?.classList.add('d-none');
        }
    } catch (error) {
        console.error('Error checking auth status:', error);
        // On error, try to load anyway
        signInRequired?.classList.add('d-none');
        content?.classList.remove('d-none');
        loadAutoDownloadData();
    }
}

/**
 * Scroll to wrapper setup section
 */
function scrollToWrapperSetup() {
    const wrapperSection = document.getElementById('wrapper-setup');
    if (wrapperSection) {
        wrapperSection.scrollIntoView({ behavior: 'smooth' });
        // Expand the collapse if it's closed
        const collapse = document.getElementById('wrapperSettingsCollapse');
        if (collapse && !collapse.classList.contains('show')) {
            bootstrap.Collapse.getOrCreateInstance(collapse).show();
        }
    }
}

/**
 * Load auto-download data (playlists and status)
 */
async function loadAutoDownloadData() {
    try {
        // Load available playlists from library
        const playlistsResp = await fetch('/api/library/playlists');
        if (playlistsResp.ok) {
            const data = await playlistsResp.json();
            availablePlaylists = data.playlists || [];
            updatePlaylistDropdown();
        }
        
        // Load current auto-download settings
        const settingsResp = await fetch('/api/auto-download/settings');
        if (settingsResp.ok) {
            const settings = await settingsResp.json();
            autoDownloadPlaylists = settings.playlists || [];
            renderAutoDownloadPlaylists();
            updateAutoDownloadStatus(settings);
        }
    } catch (error) {
        console.error('Error loading auto-download data:', error);
    }
}

/**
 * Update the playlist dropdown
 */
function updatePlaylistDropdown() {
    const select = document.getElementById('addPlaylistSelect');
    
    if (availablePlaylists.length === 0) {
        select.innerHTML = '<option value="">No playlists found</option>';
        return;
    }
    
    // Filter out already added playlists
    const addedIds = new Set(autoDownloadPlaylists.map(p => p.id));
    const available = availablePlaylists.filter(p => !addedIds.has(p.id));
    
    if (available.length === 0) {
        select.innerHTML = '<option value="">All playlists already added</option>';
        return;
    }
    
    select.innerHTML = '<option value="">Select a playlist...</option>' +
        available.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
}

/**
 * Add a playlist to auto-download
 */
async function addPlaylistToAutoDownload() {
    const select = document.getElementById('addPlaylistSelect');
    const playlistId = select.value;
    
    if (!playlistId) {
        showToast('Error', 'Please select a playlist', 'warning');
        return;
    }
    
    const playlist = availablePlaylists.find(p => p.id === playlistId);
    if (!playlist) return;
    
    try {
        const response = await fetch('/api/auto-download/playlists', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                id: playlist.id, 
                name: playlist.name 
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            autoDownloadPlaylists = data.playlists || [];
            renderAutoDownloadPlaylists();
            updatePlaylistDropdown();
            showToast('Success', `Added "${playlist.name}" to auto-download`, 'success');
        } else {
            showToast('Error', 'Failed to add playlist', 'danger');
        }
    } catch (error) {
        console.error('Error adding playlist:', error);
        showToast('Error', 'Failed to add playlist', 'danger');
    }
}

/**
 * Remove a playlist from auto-download
 */
async function removePlaylistFromAutoDownload(playlistId) {
    try {
        const response = await fetch(`/api/auto-download/playlists/${playlistId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            const data = await response.json();
            autoDownloadPlaylists = data.playlists || [];
            renderAutoDownloadPlaylists();
            updatePlaylistDropdown();
            showToast('Success', 'Playlist removed from auto-download', 'success');
        } else {
            showToast('Error', 'Failed to remove playlist', 'danger');
        }
    } catch (error) {
        console.error('Error removing playlist:', error);
        showToast('Error', 'Failed to remove playlist', 'danger');
    }
}

/**
 * Render auto-download playlists list
 */
function renderAutoDownloadPlaylists() {
    const container = document.getElementById('autoDownloadPlaylists');
    
    if (autoDownloadPlaylists.length === 0) {
        container.innerHTML = `
            <div class="list-group-item bg-dark text-muted text-center">
                <i class="bi bi-music-note-list"></i> No playlists added yet. Add playlists above or download all tracks from a playlist.
            </div>
        `;
        return;
    }
    
    container.innerHTML = autoDownloadPlaylists.map(playlist => `
        <div class="list-group-item bg-dark d-flex justify-content-between align-items-center">
            <div>
                <i class="bi bi-music-note-list text-primary me-2"></i>
                <strong>${escapeHtml(playlist.name)}</strong>
                ${playlist.lastChecked ? `<small class="text-muted ms-2">Last checked: ${formatDate(playlist.lastChecked)}</small>` : ''}
                ${playlist.autoAdded ? '<span class="badge bg-info ms-2">Auto-added</span>' : ''}
            </div>
            <button type="button" class="btn btn-sm btn-outline-danger" onclick="removePlaylistFromAutoDownload('${playlist.id}')" title="Remove">
                <i class="bi bi-trash"></i>
            </button>
        </div>
    `).join('');
}

/**
 * Update auto-download status display
 */
function updateAutoDownloadStatus(settings) {
    const statusEl = document.getElementById('nextCheckTime');
    const enabled = settings.enabled;
    const nextCheck = settings.nextCheck;
    
    if (!enabled) {
        statusEl.innerHTML = 'Disabled';
        statusEl.parentElement.className = 'text-muted';
    } else if (nextCheck) {
        const nextDate = new Date(nextCheck);
        statusEl.innerHTML = `Next check: ${nextDate.toLocaleString()}`;
        statusEl.parentElement.className = 'text-success';
    } else {
        statusEl.innerHTML = 'Waiting for first check...';
        statusEl.parentElement.className = 'text-warning';
    }
}

/**
 * Format date for display
 */
function formatDate(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
}

/**
 * Escape HTML characters
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Save settings
 */
async function saveSettings(e) {
    e.preventDefault();
    
    const saveBtn = document.getElementById('saveSettingsBtn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Saving...';
    
    const config = {
        // Downloader settings
        'use-docker': document.getElementById('useDocker').checked,
        'downloader-path': document.getElementById('downloaderPath').value.trim(),
        'debug-mode': document.getElementById('debugMode').checked,
        // Auth settings
        'media-user-token': document.getElementById('mediaUserToken').value.trim(),
        'authorization-token': document.getElementById('authToken').value.trim(),
        'storefront': document.getElementById('storefront').value,
        'language': document.getElementById('language').value,
        'lrc-type': document.getElementById('lrcType').value,
        'lrc-format': document.getElementById('lrcFormat').value,
        'save-lrc-file': document.getElementById('saveLrcFile').checked,
        'embed-lrc': document.getElementById('embedLrc').checked,
        'cover-size': document.getElementById('coverSize').value,
        'cover-format': document.getElementById('coverFormat').value,
        'embed-cover': document.getElementById('embedCover').checked,
        'alac-max': parseInt(document.getElementById('alacMax').value) || 0,
        'atmos-max': parseInt(document.getElementById('atmosMax').value) || 0,
        'aac-type': document.getElementById('aacType').value,
        // When toggle is OFF, save '/downloads' (parent dir); when ON, save the text value
        'alac-save-folder': document.getElementById('alacFolderEnabled').checked ? document.getElementById('alacFolder').value : '/downloads',
        'alac-folder-enabled': document.getElementById('alacFolderEnabled').checked,
        'atmos-save-folder': document.getElementById('atmosFolderEnabled').checked ? document.getElementById('atmosFolder').value : '/downloads',
        'atmos-folder-enabled': document.getElementById('atmosFolderEnabled').checked,
        'aac-save-folder': document.getElementById('aacFolderEnabled').checked ? document.getElementById('aacFolder').value : '/downloads',
        'aac-folder-enabled': document.getElementById('aacFolderEnabled').checked,
        'artist-folder-format': document.getElementById('artistFolderEnabled').checked ? document.getElementById('artistFolderFormat').value : '',
        'artist-folder-enabled': document.getElementById('artistFolderEnabled').checked,
        'album-folder-format': document.getElementById('albumFolderEnabled').checked ? document.getElementById('albumFolderFormat').value : '',
        'album-folder-enabled': document.getElementById('albumFolderEnabled').checked,
        'song-file-format': document.getElementById('songFileFormat').value,
        // Playlist folder settings
        'playlist-folder-enabled': document.getElementById('playlistFolderEnabled').checked,
        'playlist-folder-format': document.getElementById('playlistFolderFormat').value,
        'get-m3u8-mode': document.getElementById('getM3u8Mode').value,
        'decrypt-m3u8-port': document.getElementById('decryptPort').value,
        'get-m3u8-port': document.getElementById('getM3u8Port').value,
        'max-memory-limit': parseInt(document.getElementById('maxMemoryLimit').value) || 512,
        'downloads-dir': document.getElementById('downloadsDir').value.trim(),
        // Auto-download settings
        'auto-download': {
            'enabled': document.getElementById('autoDownloadEnabled').checked,
            'interval': parseInt(document.getElementById('autoDownloadInterval').value) || 60
        }
    };
    
    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const data = await response.json();
        
        // Also save lyrics settings
        const lyricsConfig = {
            'embed-in-file': document.getElementById('lyricsEmbedInFile')?.checked ?? true,
            'save-lrc-file': document.getElementById('lyricsSaveLrcFile')?.checked ?? true,
            'auto-generate': document.getElementById('autoLyricsEnabled')?.checked ?? false,
            'whisper-model': document.getElementById('whisperModel')?.value ?? 'base'
        };
        
        await fetch('/api/lyrics/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(lyricsConfig)
        });
        
        if (data.success) {
            showToast('Settings Saved', 'Your settings have been saved successfully', 'success');
            // Redirect to main page after a short delay
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        } else {
            showToast('Error', 'Failed to save settings', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Failed to connect to server', 'danger');
        console.error(error);
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="bi bi-save"></i> Save Settings';
    }
}

/**
 * Show toast notification
 */
function showToast(title, message, type = 'info') {
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
 * Load and display statistics
 */
async function loadStats() {
    try {
        // Check wrapper status
        const wrapperEl = document.getElementById('stat-wrapper');
        try {
            const wrapperRes = await fetch('/api/wrapper-status');
            const wrapperData = await wrapperRes.json();
            if (wrapperData.running) {
                wrapperEl.innerHTML = '<i class="bi bi-check-circle text-success"></i> Running';
            } else {
                wrapperEl.innerHTML = '<i class="bi bi-x-circle text-danger"></i> Stopped';
            }
        } catch {
            wrapperEl.innerHTML = '<i class="bi bi-x-circle text-danger"></i> Offline';
        }
        
        // Get download stats
        const statusRes = await fetch('/api/status');
        const statusData = await statusRes.json();
        
        document.getElementById('stat-queue').textContent = statusData.queue_size || 0;
        document.getElementById('stat-completed').textContent = statusData.completed || 0;
        document.getElementById('stat-failed').textContent = statusData.failed || 0;
        
        // Get file stats
        const filesRes = await fetch('/api/files');
        const filesData = await filesRes.json();
        
        document.getElementById('stat-files').textContent = filesData.length || 0;
        
        // Calculate total size
        const totalSize = filesData.reduce((sum, f) => sum + (f.size || 0), 0);
        document.getElementById('stat-size').textContent = formatFileSize(totalSize);
        
        // Count monitored playlists
        document.getElementById('stat-playlists').textContent = autoDownloadPlaylists.length || 0;
        
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

/**
 * Format file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// ===== Folder Browser =====
let currentBrowserPath = '';
let targetInputId = '';
let folderBrowserModal = null;

/**
 * Open folder browser modal
 */
function openFolderBrowser(inputId) {
    targetInputId = inputId;
    const currentValue = document.getElementById(inputId).value || '';
    
    if (!folderBrowserModal) {
        folderBrowserModal = new bootstrap.Modal(document.getElementById('folderBrowserModal'));
        
        // Setup event listeners for modal
        document.getElementById('openExplorerBtn').addEventListener('click', async () => {
            // Open native Windows folder picker
            const path = document.getElementById('currentPathInput').value;
            try {
                const res = await fetch('/api/select-folder', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ path })
                });
                const data = await res.json();
                if (data.success && data.path) {
                    currentBrowserPath = data.path;
                    document.getElementById('currentPathInput').value = data.path;
                    browseFolders(data.path);
                }
            } catch (error) {
                console.error('Error opening folder picker:', error);
            }
        });
        
        document.getElementById('currentPathInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const path = document.getElementById('currentPathInput').value;
                browseFolders(path);
            }
        });
        
        document.getElementById('selectFolderBtn').addEventListener('click', selectCurrentFolder);
    }
    
    folderBrowserModal.show();
    browseFolders(currentValue);
}

/**
 * Browse folders at path
 */
async function browseFolders(path) {
    const folderList = document.getElementById('folderList');
    folderList.innerHTML = `
        <div class="list-group-item bg-dark text-center text-muted">
            <i class="bi bi-hourglass-split"></i> Loading...
        </div>
    `;
    
    try {
        const res = await fetch('/api/browse-folders', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ path })
        });
        
        const data = await res.json();
        currentBrowserPath = data.current || path;
        document.getElementById('currentPathInput').value = currentBrowserPath;
        
        // Show drives on Windows
        const drivesContainer = document.getElementById('drivesContainer');
        const drivesList = document.getElementById('drivesList');
        if (data.drives && data.drives.length > 0) {
            drivesContainer.style.display = 'block';
            drivesList.innerHTML = data.drives.map(drive => `
                <button type="button" class="btn btn-sm btn-outline-secondary" onclick="browseFolders('${drive.path.replace(/\\/g, '\\\\')}')">
                    <i class="bi bi-hdd"></i> ${drive.name}
                </button>
            `).join('');
        } else {
            drivesContainer.style.display = 'none';
        }
        
        // Render folders
        if (data.folders && data.folders.length > 0) {
            folderList.innerHTML = data.folders.map(folder => `
                <button type="button" 
                        class="list-group-item list-group-item-action bg-dark text-light d-flex align-items-center"
                        ondblclick="browseFolders('${folder.path.replace(/\\/g, '\\\\')}')"
                        onclick="this.classList.toggle('active')">
                    <i class="bi ${folder.isParent ? 'bi-arrow-up' : 'bi-folder'} me-2 text-warning"></i>
                    ${folder.name}
                </button>
            `).join('');
        } else {
            folderList.innerHTML = `
                <div class="list-group-item bg-dark text-center text-muted">
                    <i class="bi bi-folder-x"></i> No subfolders
                </div>
            `;
        }
        
        if (data.error) {
            folderList.innerHTML = `
                <div class="list-group-item bg-dark text-center text-danger">
                    <i class="bi bi-exclamation-triangle"></i> ${data.error}
                </div>
            `;
        }
        
    } catch (error) {
        folderList.innerHTML = `
            <div class="list-group-item bg-dark text-center text-danger">
                <i class="bi bi-exclamation-triangle"></i> Error: ${error.message}
            </div>
        `;
    }
}

/**
 * Select current folder
 */
function selectCurrentFolder() {
    if (currentBrowserPath && targetInputId) {
        document.getElementById(targetInputId).value = currentBrowserPath;
        folderBrowserModal.hide();
    }
}


// ========================================
// New Feature Functions
// ========================================

/**
 * Load blacklist data
 */
async function loadBlacklist() {
    try {
        const response = await fetch('/api/blacklist');
        const data = await response.json();
        
        renderBlacklistItems('blacklistArtists', data.artists || [], 'artists');
        renderBlacklistItems('blacklistAlbums', data.albums || [], 'albums');
    } catch (error) {
        console.error('Failed to load blacklist:', error);
    }
}

function renderBlacklistItems(containerId, items, type) {
    const container = document.getElementById(containerId);
    
    if (items.length === 0) {
        container.innerHTML = '<div class="text-muted small py-2">No items blacklisted</div>';
        return;
    }
    
    container.innerHTML = items.map(item => `
        <div class="list-group-item list-group-item-action bg-dark d-flex justify-content-between align-items-center py-2">
            <span>${escapeHtml(item.name)}</span>
            <button class="btn btn-sm btn-outline-danger" onclick="removeFromBlacklist('${type}', '${item.id}')">
                <i class="bi bi-x"></i>
            </button>
        </div>
    `).join('');
}

async function removeFromBlacklist(type, id) {
    try {
        await fetch('/api/blacklist/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type, id })
        });
        loadBlacklist();
        showToast('Blacklist', 'Item removed from blacklist', 'success');
    } catch (error) {
        showToast('Error', 'Failed to remove from blacklist', 'danger');
    }
}


/**
 * Load followed artists
 */
async function loadFollowedArtists() {
    try {
        const response = await fetch('/api/followed-artists');
        const data = await response.json();
        
        const container = document.getElementById('followedArtistsList');
        const artists = data.artists || [];
        
        if (artists.length === 0) {
            container.innerHTML = '<div class="col-12 text-muted text-center py-3">No followed artists yet. Follow artists from search results.</div>';
            return;
        }
        
        container.innerHTML = artists.map(artist => `
            <div class="col-6 col-md-4 col-lg-3">
                <div class="card bg-secondary bg-opacity-25 h-100">
                    ${artist.artwork ? `<img src="${artist.artwork}" class="card-img-top" alt="${escapeHtml(artist.name)}">` : ''}
                    <div class="card-body p-2">
                        <h6 class="card-title mb-0 text-truncate">${escapeHtml(artist.name)}</h6>
                    </div>
                    <div class="card-footer p-2">
                        <button class="btn btn-sm btn-outline-danger w-100" onclick="unfollowArtist('${artist.id}')">
                            <i class="bi bi-person-dash"></i> Unfollow
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load followed artists:', error);
    }
}

async function unfollowArtist(id) {
    try {
        await fetch('/api/followed-artists/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        loadFollowedArtists();
        showToast('Followed Artists', 'Artist unfollowed', 'success');
    } catch (error) {
        showToast('Error', 'Failed to unfollow artist', 'danger');
    }
}

async function checkNewReleases() {
    showToast('Checking', 'Checking for new releases...', 'info');
    
    try {
        const response = await fetch('/api/new-releases');
        const data = await response.json();
        
        if (data.new_releases && data.new_releases.length > 0) {
            showToast('New Releases', `Found ${data.new_releases.length} new releases!`, 'success');
            // Could open a modal to show new releases
        } else {
            showToast('New Releases', 'No new releases found', 'info');
        }
    } catch (error) {
        showToast('Error', 'Failed to check new releases', 'danger');
    }
}


/**
 * Scan for duplicate files
 */
async function scanDuplicates() {
    showToast('Scanning', 'Scanning for duplicate files...', 'info');
    
    try {
        const response = await fetch('/api/scan-duplicates');
        const data = await response.json();
        
        if (data.duplicates && data.duplicates.length > 0) {
            showToast('Duplicates Found', `Found ${data.duplicates.length} potential duplicates`, 'warning');
        } else {
            showToast('No Duplicates', `Scanned ${data.total_files_scanned} files, no duplicates found`, 'success');
        }
    } catch (error) {
        showToast('Error', 'Failed to scan for duplicates', 'danger');
    }
}


/**
 * Import settings from backup
 */
async function importSettings() {
    const fileInput = document.getElementById('importFile');
    
    if (!fileInput.files || !fileInput.files[0]) {
        showToast('Error', 'Please select a backup file first', 'warning');
        return;
    }
    
    const file = fileInput.files[0];
    
    try {
        const content = await file.text();
        const data = JSON.parse(content);
        
        const response = await fetch('/api/settings/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: content
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('Import', 'Settings imported successfully! Reloading...', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast('Error', result.error || 'Failed to import settings', 'danger');
        }
    } catch (error) {
        showToast('Error', 'Invalid backup file', 'danger');
    }
}


/**
 * Helper function to escape HTML
 */
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text || '').replace(/[&<>"']/g, m => map[m]);
}


// Initialize new settings sections on page load
document.addEventListener('DOMContentLoaded', () => {
    loadBlacklist();
    loadFollowedArtists();
});



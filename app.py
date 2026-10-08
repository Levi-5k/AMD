"""
Apple Music Downloader Web Application
A Flask-based web interface for the apple-music-downloader CLI tool
"""

APP_VERSION = '1.0.0'
UPDATE_REPO = 'Levi-5k/AMD' 

import os
import json
import subprocess
import threading
import queue
import uuid
import re
import requests
import time
import logging
import base64
import shutil
import hashlib
import tempfile
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, Response
from flask_socketio import SocketIO, emit
import yaml
import sys
import argparse
import webbrowser

# ========================================
# Subprocess Helper for Hidden Console
# ========================================

def get_subprocess_kwargs():
    """Get subprocess kwargs that hide console windows on Windows when running as EXE"""
    kwargs = {}
    # Hide console window on Windows when running as frozen EXE
    if sys.platform == 'win32' and getattr(sys, 'frozen', False):
        # CREATE_NO_WINDOW flag
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return kwargs

def run_subprocess(cmd, **extra_kwargs):
    """Run subprocess with hidden console window on Windows EXE"""
    kwargs = get_subprocess_kwargs()
    kwargs.update(extra_kwargs)
    return subprocess.run(cmd, **kwargs)

def popen_subprocess(cmd, **extra_kwargs):
    """Popen subprocess with hidden console window on Windows EXE"""
    kwargs = get_subprocess_kwargs()
    kwargs.update(extra_kwargs)
    return subprocess.Popen(cmd, **kwargs)

# ========================================
# Package Management System
# ========================================

# All required packages with their import names
ALL_REQUIREMENTS = {
    'flask': {'import': 'flask', 'required': True},
    'flask-socketio': {'import': 'flask_socketio', 'required': True},
    'pyyaml': {'import': 'yaml', 'required': True},
    'requests': {'import': 'requests', 'required': True},
    'python-socketio': {'import': 'socketio', 'required': False},
    'python-engineio': {'import': 'engineio', 'required': False},
    'eventlet': {'import': 'eventlet', 'required': False},
    'gevent': {'import': 'gevent', 'required': False},
    'gevent-websocket': {'import': 'geventwebsocket', 'required': False},
    'werkzeug': {'import': 'werkzeug', 'required': False},
    'mutagen': {'import': 'mutagen', 'required': False},
    'pyinstaller': {'import': 'PyInstaller', 'required': False},
}

# Track installation state
_installation_state = {
    'running': False,
    'completed': False,
    'packages': {},
    'current': None,
    'progress': 0,
    'total': 0,
    'needs_restart': False,
}

def check_package_installed(package_name, import_name):
    """Check if a package is installed"""
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False

def get_missing_packages():
    """Get list of missing required packages"""
    # When running as frozen EXE, only check truly required packages
    if getattr(sys, 'frozen', False):
        # Only check critical packages when frozen
        critical = ['flask', 'flask-socketio', 'pyyaml', 'requests']
        missing = []
        for pkg in critical:
            if pkg in ALL_REQUIREMENTS:
                info = ALL_REQUIREMENTS[pkg]
                if not check_package_installed(pkg, info['import']):
                    missing.append(pkg)
        return missing
    
    missing = []
    for pkg, info in ALL_REQUIREMENTS.items():
        if not check_package_installed(pkg, info['import']):
            missing.append(pkg)
    return missing

def install_package_pip(package):
    """Install a package using pip"""
    try:
        result = run_subprocess(
            [sys.executable, '-m', 'pip', 'install', '-q', package],
            capture_output=True,
            text=True,
            timeout=120
        )
        return result.returncode == 0
    except Exception:
        # Try with --user flag
        try:
            result = run_subprocess(
                [sys.executable, '-m', 'pip', 'install', '-q', '--user', package],
                capture_output=True,
                text=True,
                timeout=120
            )
            return result.returncode == 0
        except Exception:
            return False

# Import mutagen for audio file metadata (artwork extraction)
try:
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    # Don't print warning - will be installed later

# Configure logging with UTF-8 encoding for Windows
log_file_handler = logging.FileHandler('amd_debug.log', encoding='utf-8')
log_stream_handler = logging.StreamHandler()
# Set UTF-8 encoding for stream handler on Windows
import sys
import argparse
import webbrowser

# Handle noconsole mode where stdout may be None
if sys.stdout is not None and sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass  # Older Python versions don't have reconfigure

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        log_file_handler,
        log_stream_handler
    ]
)
logger = logging.getLogger(__name__)

# Cache for Apple Music token
_apple_music_token = None
_apple_music_token_expires = 0

def get_apple_music_token():
    """Fetch Apple Music API token from Apple's website"""
    global _apple_music_token, _apple_music_token_expires
    
    # Use cached token if not expired
    if _apple_music_token and time.time() < _apple_music_token_expires:
        return _apple_music_token
    
    try:
        # Fetch Apple Music homepage to get the token
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        # Apple embeds the developer token in a hashed web-player JavaScript bundle.
        response = requests.get('https://music.apple.com/us/browse', headers=headers, timeout=10)
        
        if response.status_code == 200:
            import base64
            import re

            script_paths = re.findall(r'<script[^>]+src=["\']([^"\']+)', response.text)
            script_paths = [path for path in script_paths if '/assets/index' in path]

            for script_path in script_paths:
                script_url = requests.compat.urljoin(response.url, script_path)
                script_response = requests.get(script_url, headers=headers, timeout=30)
                if script_response.status_code != 200:
                    continue

                candidates = re.findall(
                    r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
                    script_response.text
                )
                for token in candidates:
                    try:
                        encoded_header = token.split('.', 1)[0]
                        encoded_header += '=' * (-len(encoded_header) % 4)
                        token_header = json.loads(base64.urlsafe_b64decode(encoded_header))
                    except (ValueError, json.JSONDecodeError):
                        continue

                    if token_header.get('kid') == 'WebPlayKid':
                        _apple_music_token = token
                        _apple_music_token_expires = time.time() + 3500
                        logger.info(f"Obtained Apple Music token ({len(token)} chars)")
                        return token
        
        logger.warning("Could not find token in Apple Music pages")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching Apple Music token: {e}")
        return None

# Handle PyInstaller frozen executable for templates/static
if getattr(sys, 'frozen', False):
    # Running as compiled EXE - use _MEIPASS for bundled resources
    BUNDLE_DIR = sys._MEIPASS
    app = Flask(__name__, 
                template_folder=os.path.join(BUNDLE_DIR, 'templates'),
                static_folder=os.path.join(BUNDLE_DIR, 'static'))
else:
    # Running as script
    app = Flask(__name__)
    
app.config['SECRET_KEY'] = os.urandom(24).hex()
# Use threading mode to allow emitting from background threads
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Cache buster for static files
CACHE_VERSION = str(int(time.time()))

# Configuration
# Handle PyInstaller frozen executable
if getattr(sys, 'frozen', False):
    # Running as compiled EXE - use the directory containing the EXE
    BASE_DIR = os.path.dirname(sys.executable)
    print(f"[DEBUG] Running as frozen EXE")
    print(f"[DEBUG] EXE location: {sys.executable}")
    print(f"[DEBUG] BASE_DIR: {BASE_DIR}")
else:
    # Running as script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
CONFIG_FILE = os.path.join(BASE_DIR, 'config.yaml')
DEFAULT_DOWNLOADS_DIR = os.path.join(BASE_DIR, 'downloads')

print(f"[DEBUG] CONFIG_FILE: {CONFIG_FILE}")
print(f"[DEBUG] Config exists: {os.path.exists(CONFIG_FILE)}")

# This will be set from config after load_config()
DOWNLOADS_DIR = DEFAULT_DOWNLOADS_DIR

def _init_downloads_dir():
    """Initialize DOWNLOADS_DIR from config"""
    global DOWNLOADS_DIR
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
            custom_dir = config.get('downloads-dir', '').strip()
            if custom_dir and os.path.isabs(custom_dir):
                DOWNLOADS_DIR = custom_dir
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

_init_downloads_dir()

# Download queue and status tracking
download_queue = queue.Queue()
downloads = {}  # Track all downloads by ID
download_lock = threading.Lock()
active_download_ids = {}  # Request key -> active download ID
download_request_keys = {}  # Download ID -> request key

# Default configuration
DEFAULT_CONFIG = {
    'storefront': 'us',
    'language': 'en-US',
    'media-user-token': '',
    'authorization-token': '',
    'save-lrc-file': True,
    'lrc-type': 'syllable-lyrics',
    'lrc-format': 'lrc',
    'embed-lrc': True,
    'embed-cover': True,
    'cover-size': '1200',
    'cover-format': 'jpg',
    'alac-save-folder': DOWNLOADS_DIR,
    'alac-folder-enabled': True,
    'atmos-save-folder': os.path.join(DOWNLOADS_DIR, 'atmos'),
    'atmos-folder-enabled': True,
    'aac-save-folder': os.path.join(DOWNLOADS_DIR, 'aac'),
    'aac-folder-enabled': True,
    'album-folder-format': '{ArtistName}/{AlbumName}',
    'album-folder-enabled': True,
    'song-file-format': '{TrackNumber}. {SongName}',
    'alac-max': 0,
    'atmos-max': 0,
    'aac-type': 'aac',
    # Downloader settings
    'downloader-path': '',  # Path to apple-music-downloader folder (leave empty for Docker)
    'use-docker': True,  # Use Docker instead of local Go installation
    'get-m3u8-mode': 'api',
    'decrypt-m3u8-port': '127.0.0.1:10020',
    'get-m3u8-port': '127.0.0.1:20020',
    'max-memory-limit': 512,
    'downloads-dir': '',  # Base download directory (empty = default ./downloads)
}


def load_config():
    """Load configuration from YAML file"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def get_downloads_dir():
    """Get the current downloads directory"""
    return DOWNLOADS_DIR


def update_downloads_dir():
    """Update DOWNLOADS_DIR from config (call after config save)"""
    global DOWNLOADS_DIR
    config = load_config()
    custom_dir = config.get('downloads-dir', '').strip()
    if custom_dir and os.path.isabs(custom_dir):
        DOWNLOADS_DIR = custom_dir
    else:
        DOWNLOADS_DIR = DEFAULT_DOWNLOADS_DIR
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    return DOWNLOADS_DIR


def save_config(config):
    """Save configuration to YAML file"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def embed_artwork_in_m4a(m4a_path, artwork_url):
    """Download artwork and embed it into an m4a file."""
    try:
        if not artwork_url or not os.path.exists(m4a_path):
            return False
        
        # Download the artwork
        artwork_response = requests.get(artwork_url, timeout=30)
        if artwork_response.status_code != 200:
            logger.error(f"Failed to download artwork: {artwork_response.status_code}")
            return False

        artwork_data = artwork_response.content
        if artwork_data.startswith(b'\x89PNG\r\n\x1a\n'):
            image_format = MP4Cover.FORMAT_PNG
        elif artwork_data.startswith(b'\xff\xd8\xff'):
            image_format = MP4Cover.FORMAT_JPEG
        else:
            logger.error("Downloaded artwork is not a supported JPEG or PNG image")
            return False

        audio = MP4(m4a_path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags['covr'] = [MP4Cover(artwork_data, imageformat=image_format)]
        audio.save()
        logger.info(f"Embedded artwork in: {os.path.basename(m4a_path)}")
        return True
            
    except Exception as e:
        logger.error(f"Error embedding artwork: {e}")
        return False


def embed_artwork_for_file(m4a_path, fallback_artwork_url=None, fallback_song_id=None):
    """Embed artwork for an m4a file by reading its metadata and fetching artwork from Apple Music API"""
    try:
        if not os.path.exists(m4a_path) or not MUTAGEN_AVAILABLE:
            return False
        
        # Check if already has artwork
        audio = MP4(m4a_path)
        if 'covr' in audio and audio['covr']:
            logger.debug(f"File already has artwork: {os.path.basename(m4a_path)}")
            return True
        
        # Get song ID and album ID from metadata
        song_id = audio.get('atID', [None])[0] if 'atID' in audio else fallback_song_id
        album_id = audio.get('plID', [None])[0] if 'plID' in audio else None
        
        if not song_id and not album_id:
            if fallback_artwork_url:
                logger.info(f"Embedding supplied artwork for: {os.path.basename(m4a_path)}")
                return embed_artwork_in_m4a(m4a_path, fallback_artwork_url)
            logger.warning(f"No song/album ID in metadata for: {os.path.basename(m4a_path)}")
            return False
        
        logger.info(f"Embedding artwork for: {os.path.basename(m4a_path)} (song ID: {song_id}, album ID: {album_id})")
        embedded = embed_artwork_for_song(song_id, m4a_path, album_id=album_id)
        if not embedded and fallback_artwork_url:
            return embed_artwork_in_m4a(m4a_path, fallback_artwork_url)
        return embedded
        
    except Exception as e:
        logger.error(f"Error embedding artwork for file {m4a_path}: {e}")
        return False


def embed_artwork_for_song(song_id, m4a_path, album_id=None):
    """Fetch song info from Apple Music API and embed artwork"""
    try:
        tokens = get_wrapper_tokens(retry_on_timeout=False)
        if not tokens:
            logger.warning("No tokens available for artwork embedding")
            return False
        
        dev_token = tokens.get('dev_token')
        
        headers = {
            'Authorization': f'Bearer {dev_token}',
            'Origin': 'https://music.apple.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        artwork_url = None
        config = load_config()
        cover_size = str(config.get('cover-size', '1200'))
        
        # Try song lookup first
        if song_id:
            response = requests.get(
                f'https://amp-api.music.apple.com/v1/catalog/us/songs/{song_id}',
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                songs = data.get('data', [])
                if songs:
                    artwork = songs[0].get('attributes', {}).get('artwork', {})
                    if artwork and artwork.get('url'):
                        artwork_url = artwork['url'].replace('{w}', cover_size).replace('{h}', cover_size)
        
        # If song lookup failed, try album lookup
        if not artwork_url and album_id:
            logger.info(f"Song lookup failed, trying album ID: {album_id}")
            response = requests.get(
                f'https://amp-api.music.apple.com/v1/catalog/us/albums/{album_id}',
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                albums = data.get('data', [])
                if albums:
                    artwork = albums[0].get('attributes', {}).get('artwork', {})
                    if artwork and artwork.get('url'):
                        artwork_url = artwork['url'].replace('{w}', cover_size).replace('{h}', cover_size)
        
        if artwork_url:
            return embed_artwork_in_m4a(m4a_path, artwork_url)
        
        logger.warning(f"Could not find artwork for song {song_id} or album {album_id}")
        return False
    except Exception as e:
        logger.error(f"Error embedding artwork for song {song_id}: {e}")
        return False


def parse_apple_music_url(url):
    """Parse Apple Music URL to extract type, storefront, and ID"""
    patterns = {
        'album': r'music\.apple\.com/(\w+)/album/[^/]+/(\d+)',
        'album_short': r'music\.apple\.com/(\w+)/album/(\d+)$',
        'song': r'music\.apple\.com/(\w+)/song/[^/]+/(\d+)',
        'song_short': r'music\.apple\.com/(\w+)/song/(\d+)$',
        'song_from_album': r'music\.apple\.com/(\w+)/album/[^/]+/\d+\?i=(\d+)',
        'playlist': r'music\.apple\.com/(\w+)/playlist/[^/]+/(pl\.[a-zA-Z0-9-]+)',
        'library_playlist': r'music\.apple\.com/library/playlist/(p\.[a-zA-Z0-9]+)',
        'artist': r'music\.apple\.com/(\w+)/artist/[^/]+/(\d+)',
        'music-video': r'music\.apple\.com/(\w+)/music-video/[^/]+/(\d+)',
    }
    
    for url_type, pattern in patterns.items():
        match = re.search(pattern, url)
        if match:
            # Library playlists don't have a storefront in the URL
            if url_type == 'library_playlist':
                return {
                    'type': 'playlist',
                    'storefront': 'library',
                    'id': match.group(1)
                }
            # Normalize type by removing suffixes
            normalized_type = url_type.replace('_from_album', '').replace('_short', '')
            return {
                'type': normalized_type,
                'storefront': match.group(1),
                'id': match.group(2)
            }
    return None


ACTIVE_DOWNLOAD_STATUSES = {'queued', 'downloading', 'retrying'}


def get_download_request_key(url):
    """Return a stable key for duplicate detection across Apple Music URL forms."""
    url_info = parse_apple_music_url(url)
    if url_info:
        return f"{url_info['type']}:{url_info['id']}"
    return url.strip().rstrip('/').lower()


def register_download(download):
    """Atomically register a download unless the same item is already active."""
    request_key = get_download_request_key(download['url'])
    with download_lock:
        existing_id = active_download_ids.get(request_key)
        if existing_id:
            existing = downloads.get(existing_id)
            if existing and existing.get('status') in ACTIVE_DOWNLOAD_STATUSES:
                return existing_id, False
            active_download_ids.pop(request_key, None)
            download_request_keys.pop(existing_id, None)

        downloads[download['id']] = download
        active_download_ids[request_key] = download['id']
        download_request_keys[download['id']] = request_key
    return download['id'], True


def release_download_registration_locked(download_id):
    """Release an active request key while download_lock is held."""
    request_key = download_request_keys.pop(download_id, None)
    if request_key and active_download_ids.get(request_key) == download_id:
        active_download_ids.pop(request_key, None)


def move_files_to_playlist_folder(search_dir, playlist_name, recent_time):
    """Move recently downloaded files to a playlist folder"""
    config = load_config()
    
    # Check if playlist folder organization is enabled
    if not config.get('playlist-folder-enabled', False):
        return 0
    
    if not playlist_name:
        return 0
    
    # Get the playlist folder format
    playlist_folder_format = config.get('playlist-folder-format', 'Playlists/{PlaylistName}')
    
    # Sanitize playlist name for filesystem (remove invalid characters)
    safe_playlist_name = re.sub(r'[<>:"/\\|?*]', '_', playlist_name)
    
    # Build the playlist folder path
    playlist_folder = playlist_folder_format.replace('{PlaylistName}', safe_playlist_name)
    playlist_path = os.path.join(DOWNLOADS_DIR, playlist_folder)
    
    # Create the playlist folder if it doesn't exist
    os.makedirs(playlist_path, exist_ok=True)
    
    files_moved = 0
    
    try:
        for root, dirs, files in os.walk(search_dir):
            for f in files:
                if f.endswith('.m4a') or f.endswith('.m4v') or f.endswith('.lrc'):
                    filepath = os.path.join(root, f)
                    if os.path.getmtime(filepath) > recent_time:
                        # Destination path - preserve artist/album folder structure if present
                        rel_path = os.path.relpath(filepath, search_dir)
                        dest_path = os.path.join(playlist_path, rel_path)
                        dest_dir = os.path.dirname(dest_path)
                        
                        # Create destination directory if needed
                        os.makedirs(dest_dir, exist_ok=True)
                        
                        # Move the file
                        try:
                            shutil.move(filepath, dest_path)
                            files_moved += 1
                            logger.info(f"Moved to playlist folder: {rel_path} -> {playlist_folder}")
                        except Exception as e:
                            logger.error(f"Error moving file to playlist folder: {e}")
    except Exception as e:
        logger.error(f"Error moving files to playlist folder: {e}")
    
    return files_moved


def get_download_cmd(url, options):
    """Build the download command based on URL and options"""
    config = load_config()
    use_docker = config.get('use-docker', True)
    downloader_path = config.get('downloader-path', '')
    
    if use_docker:
        # Use Docker
        # Convert Windows paths to Docker volume format
        downloads_vol = DOWNLOADS_DIR.replace('\\', '/')
        config_vol = CONFIG_FILE.replace('\\', '/')
        
        cmd = ['docker', 'run', '--rm', '-i']
        if options.get('_container_name'):
            cmd.extend(['--name', options['_container_name']])
        cmd.extend([
            '--network', 'host',
            '-v', f'{downloads_vol}:/downloads',
            '-v', f'{config_vol}:/app/config.yaml',
            'ghcr.io/zhaarey/apple-music-downloader'
        ])
    else:
        # Use local Go installation
        if downloader_path and os.path.isfile(os.path.join(downloader_path, 'main.go')):
            cmd = ['go', 'run', 'main.go']
            options['downloader_path'] = downloader_path
        else:
            # Check for compiled binary
            binary_name = 'apple-music-downloader.exe' if os.name == 'nt' else 'apple-music-downloader'
            if downloader_path and os.path.isfile(os.path.join(downloader_path, binary_name)):
                cmd = [os.path.join(downloader_path, binary_name)]
            elif downloader_path and os.path.isfile(os.path.join(downloader_path, 'main')):
                cmd = [os.path.join(downloader_path, 'main')]
            else:
                raise FileNotFoundError(
                    f"Downloader not found. Please either:\n"
                    f"1. Enable Docker mode in settings, or\n"
                    f"2. Set the correct path to apple-music-downloader in settings\n"
                    f"   Current path: {downloader_path or '(not set)'}"
                )
    
    # Add quality options
    quality = options.get('quality', 'alac')
    if quality == 'atmos':
        cmd.append('--atmos')
    elif quality == 'aac':
        cmd.append('--aac')
    # For ALAC (lossless), don't add any flag - it's the default
    
    # Add other options
    # Only use --select for albums when we want track selection (not for single songs)
    if options.get('select') and not options.get('song'):
        cmd.append('--select')
    
    # Only add debug flag if explicitly requested (it prevents actual downloads!)
    if options.get('debug'):
        cmd.append('--debug')
    
    # For single song downloads, use --song flag
    if options.get('song'):
        cmd.append('--song')
    
    # Add the URL
    cmd.append(url)
    
    return cmd


def terminate_download_process(process, container_name=None):
    """Stop a downloader process and its specific Docker container."""
    if container_name:
        try:
            run_subprocess(
                ['docker', 'rm', '-f', container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
        except Exception as e:
            logger.warning(f"Failed to remove download container {container_name}: {e}")

    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def restart_wrapper_container():
    """Restart the AMD wrapper container to fix connection issues"""
    logger.info("Attempting to restart wrapper container...")
    try:
        # First try to restart the existing container
        result = run_subprocess(
            ['docker', 'restart', 'amd-wrapper'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30
        )
        
        if result.returncode == 0:
            logger.info("Wrapper container restarted successfully")
            # Wait a bit for the container to be ready
            time.sleep(3)
            return True
        else:
            logger.warning(f"Failed to restart wrapper: {result.stderr}")
            
            # Try to start it if it doesn't exist
            wrapper_data = os.path.join(BASE_DIR, 'wrapper-data')
            os.makedirs(wrapper_data, exist_ok=True)
            
            # Stop any existing container first
            run_subprocess(['docker', 'rm', '-f', 'amd-wrapper'], 
                          capture_output=True, timeout=10)
            
            # Start new container
            result = run_subprocess([
                'docker', 'run', '-d',
                '--name', 'amd-wrapper',
                '--restart', 'no',
                '-v', f'{wrapper_data}:/app/rootfs/data',
                '-p', '10020:10020',
                '-p', '20020:20020', 
                '-p', '30020:30020',
                '-e', 'args=-H 0.0.0.0',
                'amd-wrapper-local'
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            
            if result.returncode == 0:
                logger.info("Wrapper container started successfully")
                time.sleep(3)
                return True
            else:
                logger.error(f"Failed to start wrapper: {result.stderr}")
                return False
                
    except subprocess.TimeoutExpired:
        logger.error("Wrapper restart timed out")
        return False
    except Exception as e:
        logger.error(f"Error restarting wrapper: {e}")
        return False


def wrapper_is_ready():
    """Check the wrapper ports required for account data and decryption."""
    import socket

    for port in (10020, 30020):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                pass
        except OSError:
            return False
    return True


def ensure_wrapper_ready_for_download():
    """Start the wrapper on demand and wait until its services are listening."""
    if wrapper_is_ready():
        return True

    logger.info("Wrapper is not ready; starting it for the queued download")
    if not restart_wrapper_container():
        return False

    deadline = time.time() + 15
    while time.time() < deadline:
        if wrapper_is_ready():
            logger.info("Wrapper is ready for download")
            return True
        time.sleep(1)

    logger.error("Wrapper did not become ready before the download timeout")
    return False


def download_worker():
    """Background worker to process download queue"""
    while True:
        try:
            download_id, url, options = download_queue.get()
            logger.info(f"=== Download Worker: Processing {download_id} ===")
            logger.info(f"URL: {url}")
            
            with download_lock:
                downloads[download_id]['status'] = 'downloading'
                downloads[download_id]['started_at'] = datetime.now().isoformat()
            
            socketio.emit('download_update', downloads[download_id], namespace='/')

            process = None
            container_name = None
            try:
                if not ensure_wrapper_ready_for_download():
                    raise RuntimeError(
                        "Wrapper failed to start. Check Docker and the wrapper service, then try again."
                    )

                worker_options = options.copy()
                safe_download_id = re.sub(r'[^a-zA-Z0-9_.-]', '-', download_id)
                container_name = f"amd-download-{safe_download_id}-{options.get('_retry_count', 0)}"
                worker_options['_container_name'] = container_name
                cmd = get_download_cmd(url, worker_options)
                logger.info(f"Command: {' '.join(cmd)}")
                start_time = time.time()
                
                # Run the download command
                process = popen_subprocess(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    cwd=options.get('downloader_path', BASE_DIR),
                    bufsize=1
                )
                
                # Answer an optional selection prompt, then close stdin so Docker
                # cannot wait indefinitely for more interactive input.
                if process.stdin:
                    try:
                        if options.get('select'):
                            selected_tracks = options.get('selected_tracks') or []
                            process.stdin.write(','.join(str(track) for track in selected_tracks) + '\n')
                            process.stdin.flush()
                    except Exception:
                        pass  # Stdin may already be closed
                    finally:
                        process.stdin.close()
                
                output_lines = []
                completed_count = 0
                total_count = 0
                error_message = None
                no_codec_error = False
                download_seen = False
                critical_error = False  # Track fatal errors that should always fail
                wrapper_connection_error = False  # Track wrapper TCP errors (can retry)
                last_output_time = time.time()
                idle_timeout = 30  # seconds to wait after last output before assuming hung
                stalled_timeout = 120  # no output before completion means the process is stuck
                max_total_time = 600  # 10 minutes max for any download
                
                if process.stdout is None:
                    raise Exception("Failed to capture process output")
                
                import select
                import sys
                
                # Use threading to read stdout with timeout capability
                import threading
                from queue import Queue, Empty
                
                def enqueue_output(out, queue):
                    for line in iter(out.readline, ''):
                        queue.put(line)
                    out.close()
                
                stdout_queue = Queue()
                stdout_thread = threading.Thread(target=enqueue_output, args=(process.stdout, stdout_queue))
                stdout_thread.daemon = True
                stdout_thread.start()
                
                while True:
                    try:
                        # Try to get a line with timeout
                        line = stdout_queue.get(timeout=1.0)
                        last_output_time = time.time()
                        line = line.strip()
                        if not line:
                            continue
                        output_lines.append(line)
                        
                        # Parse progress from output
                        progress_info = parse_progress(line)
                        
                        # Check for completion summary (e.g., "Completed: 5/10")
                        completed_match = re.search(r'Completed:\s*(\d+)/(\d+)', line)
                        if completed_match:
                            completed_count = int(completed_match.group(1))
                            total_count = int(completed_match.group(2))
                            # A 0/0 summary is emitted after some fatal startup failures.
                            download_seen = completed_count > 0
                        
                        # Also check for "Downloaded" as a standalone line (single track completion)
                        line_lower = line.lower().strip()
                        if line_lower == 'downloaded':
                            download_seen = True
                        
                        # Check for specific "no codec found" error (selected format not available)
                        if 'no codec found' in line_lower:
                            no_codec_error = True
                            # Don't set critical_error - we'll retry with AAC
                            selected_quality = options.get('quality', 'alac')
                            if selected_quality in ['alac', 'atmos']:
                                error_message = f"{selected_quality.upper()} not available for this track. Check output for available qualities. Will retry with AAC."
                            else:
                                error_message = "Selected quality not available for this track. Check output for available qualities."
                        # Check for critical errors that mean the download definitely failed
                        elif 'failed to get decryption keys' in line_lower or 'cannot get decryption keys' in line_lower:
                            critical_error = True
                            error_message = "Failed to get decryption keys. Check wrapper service and Apple ID authentication."
                        elif (
                            'unauthorized' in line_lower
                            or re.search(
                                r'(?:authentication|http|status|error).{0,20}\b401\b|'
                                r'\b401\b.{0,20}(?:unauthorized|authentication|status|error)',
                                line_lower
                            )
                        ):
                            critical_error = True
                            error_message = "Authentication failed. Please re-login to your Apple ID."
                        elif 'docker' in line_lower and ('not running' in line_lower or 'not found' in line_lower):
                            critical_error = True
                            error_message = "Docker is not running. Please start Docker Desktop."
                        elif 'connection refused' in line_lower or 'connection error' in line_lower:
                            critical_error = True
                            error_message = "Connection error. Check if wrapper service is running."
                        # Check for wrapper TCP connection errors (can be retried)
                        elif 'decryptfragment' in line_lower and 'read tcp' in line_lower:
                            wrapper_connection_error = True
                            error_message = "Wrapper connection lost. Will restart wrapper and retry."
                        elif 'failed to run v2' in line_lower and 'read tcp' in line_lower:
                            wrapper_connection_error = True
                            error_message = "Wrapper connection lost. Will restart wrapper and retry."
                        # Check for other error messages
                        elif ('error' in line_lower or 'failed' in line_lower) and not error_message:
                            error_message = line
                        
                        with download_lock:
                            downloads[download_id]['output'] = output_lines[-50:]  # Keep last 50 lines
                            if progress_info:
                                downloads[download_id]['progress'] = progress_info
                        
                        socketio.emit('download_progress', {
                            'id': download_id,
                            'line': line,
                            'progress': progress_info
                        }, namespace='/')
                        
                    except Empty:
                        # No output received in timeout period
                        # Check if process has exited
                        if process.poll() is not None:
                            break
                        
                        idle_time = time.time() - last_output_time
                        total_time = time.time() - start_time
                        
                        # Kill if exceeded max total time
                        if total_time > max_total_time:
                            logger.warning(f"Process exceeded max time ({total_time:.1f}s), terminating...")
                            critical_error = True
                            error_message = "Download timed out after 10 minutes."
                            terminate_download_process(process, container_name)
                            break

                        if not download_seen and idle_time > stalled_timeout:
                            logger.warning(f"Process produced no output for {idle_time:.1f}s, terminating...")
                            critical_error = True
                            error_message = "Download stalled with no output for 2 minutes."
                            terminate_download_process(process, container_name)
                            break
                        
                        # If we've seen a download complete and been idle, kill the hung process
                        if download_seen and idle_time > idle_timeout:
                            logger.warning(f"Process appears hung after download (idle {idle_time:.1f}s), terminating...")
                            terminate_download_process(process, container_name)
                            break
                
                return_code = process.poll() if process.poll() is not None else 0
                logger.info(f"Process finished with return code: {return_code}")
                logger.info(f"Output lines: {len(output_lines)}")
                logger.info(f"Completed: {completed_count}/{total_count}, download_seen: {download_seen}, critical_error: {critical_error}, no_codec_error: {no_codec_error}, wrapper_connection_error: {wrapper_connection_error}")
                
                # Handle wrapper connection error - restart wrapper and retry
                if wrapper_connection_error:
                    retry_count = options.get('_retry_count', 0)
                    max_retries = 2
                    
                    if retry_count < max_retries:
                        logger.info(f"Wrapper connection error detected (attempt {retry_count + 1}/{max_retries + 1}). Restarting wrapper and retrying...")
                        
                        # Update status to show retry
                        with download_lock:
                            downloads[download_id]['status'] = 'retrying'
                            downloads[download_id]['error'] = f"Wrapper connection lost. Restarting wrapper (retry {retry_count + 1}/{max_retries})..."
                        
                        socketio.emit('download_update', downloads[download_id], namespace='/')
                        
                        # Restart the wrapper
                        if restart_wrapper_container():
                            # Queue retry with incremented retry count
                            retry_options = options.copy()
                            retry_options['_retry_count'] = retry_count + 1
                            download_queue.put((download_id, url, retry_options))
                            download_queue.task_done()
                            continue  # Skip to next queue item
                        else:
                            logger.error("Failed to restart wrapper, marking download as failed")
                            error_message = "Wrapper connection lost and restart failed. Please manually restart the wrapper."
                            critical_error = True
                    else:
                        logger.error(f"Max retries ({max_retries}) exceeded for wrapper connection error")
                        error_message = f"Wrapper connection lost after {max_retries} retries. Please check your wrapper service."
                        critical_error = True
                
                # Log the actual downloader output for debugging
                if output_lines:
                    logger.info("Downloader output:")
                    for line in output_lines[-20:]:  # Last 20 lines
                        # Sanitize Unicode characters that might cause encoding issues on Windows
                        safe_line = line.encode('ascii', errors='replace').decode('ascii')
                        logger.info(f"  > {safe_line}")
                
                # Determine success:
                # 1. Never succeed if there was a critical error (auth, docker, connection issues)
                # 2. Never succeed if codec not found (selected quality not available)
                # 3. Never succeed if wrapper connection error (already handled above with retry)
                # 4. If we have a track count, at least one must be completed
                # 5. If no track count, we need to see "Downloaded" and have no errors
                # 6. Process must exit cleanly (return_code == 0) unless we terminated a hung process after download
                
                if critical_error or no_codec_error or wrapper_connection_error:
                    # Critical errors, codec errors, and wrapper errors always mean failure
                    is_success = False
                elif total_count > 0:
                    # If we know how many tracks, check if any completed
                    is_success = completed_count > 0
                elif download_seen:
                    # Single track download - saw "Downloaded" message
                    is_success = not error_message or return_code == 0
                else:
                    # No indication of success
                    is_success = return_code == 0 and not error_message
                
                logger.info(f"Final is_success: {is_success}")
                
                # Embed artwork for all downloaded files (albums, playlists, and songs)
                if is_success:
                    try:
                        # Look for recently modified m4a files
                        config = load_config()
                        quality = options.get('quality', 'alac')
                        
                        # Determine search directory based on config
                        if quality == 'aac':
                            aac_folder = config.get('aac-save-folder', '/downloads/aac')
                            # Convert Docker path to local path
                            if aac_folder.startswith('/downloads'):
                                search_dir = aac_folder.replace('/downloads', DOWNLOADS_DIR, 1)
                            else:
                                search_dir = os.path.join(DOWNLOADS_DIR, 'aac')
                        elif quality == 'atmos':
                            atmos_folder = config.get('atmos-save-folder', '/downloads/atmos')
                            if atmos_folder.startswith('/downloads'):
                                search_dir = atmos_folder.replace('/downloads', DOWNLOADS_DIR, 1)
                            else:
                                search_dir = os.path.join(DOWNLOADS_DIR, 'atmos')
                        else:
                            alac_folder = config.get('alac-save-folder', '/downloads')
                            if alac_folder.startswith('/downloads'):
                                search_dir = alac_folder.replace('/downloads', DOWNLOADS_DIR, 1)
                            else:
                                search_dir = DOWNLOADS_DIR
                        
                        logger.info(f"Searching for files to embed artwork in: {search_dir}")
                        
                        # Only process files written by this queue item.
                        recent_time = start_time
                        files_fixed = 0
                        url_info = downloads[download_id].get('url_info', {})
                        fallback_song_id = url_info.get('id') if url_info.get('type') == 'song' else None
                        for root, dirs, files in os.walk(search_dir):
                            for f in files:
                                if f.endswith('.m4a'):
                                    filepath = os.path.join(root, f)
                                    if os.path.getmtime(filepath) > recent_time:
                                        fallback_artwork = url_info.get('artwork')
                                        if embed_artwork_for_file(filepath, fallback_artwork, fallback_song_id):
                                            files_fixed += 1
                        if files_fixed > 0:
                            logger.info(f"Embedded artwork for {files_fixed} file(s)")
                        
                        # Auto-generate lyrics if enabled and no lyrics exist
                        lyrics_config = config.get('lyrics', {})
                        if lyrics_config.get('auto-generate', False):
                            try:
                                files_with_lyrics = 0
                                for root, dirs, files in os.walk(search_dir):
                                    for f in files:
                                        if f.endswith(('.m4a', '.mp3', '.flac')):
                                            filepath = os.path.join(root, f)
                                            if os.path.getmtime(filepath) > recent_time:
                                                if not check_file_has_lyrics(filepath):
                                                    logger.info(f"Generating lyrics for: {f}")
                                                    model_name = lyrics_config.get('whisper-model', 'base')
                                                    result, error = generate_lyrics_with_whisper(filepath, model_name)
                                                    if result and not error:
                                                        if lyrics_config.get('embed-in-file', True):
                                                            embed_lyrics_in_file(filepath, result['plain'], ai_generated=True)
                                                        if lyrics_config.get('save-lrc-file', True):
                                                            lrc_path = os.path.splitext(filepath)[0] + '.lrc'
                                                            with open(lrc_path, 'w', encoding='utf-8') as lf:
                                                                lf.write(result['lrc'])
                                                        files_with_lyrics += 1
                                if files_with_lyrics > 0:
                                    logger.info(f"Generated lyrics for {files_with_lyrics} file(s)")
                            except Exception as e:
                                logger.error(f"Error generating lyrics: {e}")
                        
                        # Move files to playlist folder if enabled and this came from a playlist
                        playlist_name = downloads[download_id].get('playlist_name')
                        if playlist_name:
                            files_moved = move_files_to_playlist_folder(search_dir, playlist_name, recent_time)
                            if files_moved > 0:
                                logger.info(f"Moved {files_moved} file(s) to playlist folder: {playlist_name}")
                    except Exception as e:
                        logger.error(f"Error embedding artwork: {e}")
                
                with download_lock:
                    downloads[download_id]['status'] = 'completed' if is_success else 'failed'
                    downloads[download_id]['completed_at'] = datetime.now().isoformat()
                    downloads[download_id]['return_code'] = return_code
                    downloads[download_id]['completed_count'] = completed_count
                    downloads[download_id]['total_count'] = total_count
                    
                    # Set appropriate error message for failed downloads
                    if not is_success:
                        if error_message:
                            downloads[download_id]['error'] = error_message
                        elif completed_count == 0 and total_count > 0:
                            downloads[download_id]['error'] = f"No tracks downloaded (0/{total_count}). Check wrapper service and Apple ID authentication."
                        elif return_code != 0:
                            downloads[download_id]['error'] = f"Download process failed with exit code {return_code}."
                        else:
                            downloads[download_id]['error'] = "Download failed. Check the output for details."
                    
                    # Track playlist items only after a successful download.
                    if is_success and downloads[download_id].get('playlist_id'):
                        playlist_id = downloads[download_id].get('playlist_id')
                        source_catalog_id = downloads[download_id].get('source_catalog_id')
                        if source_catalog_id:
                            mark_track_downloaded_for_auto_download(source_catalog_id, playlist_id)
                        else:
                            url = downloads[download_id].get('url', '')
                            url_info = parse_apple_music_url(url)
                            if url_info:
                                mark_track_downloaded_for_auto_download(url_info['id'], playlist_id)
                    
                    # Automatic retry with AAC if lossless codec not found
                    if not is_success and no_codec_error:
                        selected_quality = options.get('quality', 'alac')
                        if selected_quality in ['alac', 'atmos']:
                            logger.info(f"Codec not found for {selected_quality.upper()}, automatically retrying with AAC...")
                            # Create new options with AAC quality
                            aac_options = options.copy()
                            aac_options['quality'] = 'aac'
                            downloads[download_id]['status'] = 'retrying'
                            downloads[download_id]['error'] = f"{selected_quality.upper()} not available. Automatically retrying with AAC..."
                            download_queue.put((download_id, url, aac_options))

                    if downloads[download_id]['status'] not in ACTIVE_DOWNLOAD_STATUSES:
                        release_download_registration_locked(download_id)
                
            except Exception as e:
                logger.exception(f"Download error: {e}")
                with download_lock:
                    downloads[download_id]['status'] = 'failed'
                    downloads[download_id]['error'] = str(e)
                    release_download_registration_locked(download_id)
            finally:
                if process and process.poll() is None:
                    terminate_download_process(process, container_name)
            
            socketio.emit('download_update', downloads[download_id], namespace='/')
            download_queue.task_done()
            
        except Exception as e:
            print(f"Download worker error: {e}")


def parse_progress(line):
    """Parse progress information from download output"""
    progress = {}
    
    # Parse track progress (e.g., "Track 1 of 10: Song Name")
    track_match = re.search(r'Track (\d+) of (\d+):?\s*(.*)?', line)
    if track_match:
        progress['current_track'] = int(track_match.group(1))
        progress['total_tracks'] = int(track_match.group(2))
        # Extract song name if present (after the colon)
        if track_match.group(3):
            song_name = track_match.group(3).strip()
            if song_name:
                progress['song_name'] = song_name
        # Don't set percent here - let frontend calculate based on track progress
    
    # Parse download progress percentages from various formats
    # Match: "Downloading... 50%", "50%", "Progress: 50%", "[50%]", etc.
    percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', line)
    if percent_match:
        percent_value = float(percent_match.group(1))
        # Only accept valid percentages (0-100)
        if 0 <= percent_value <= 100:
            progress['download_percent'] = percent_value
    
    # Parse byte progress (e.g., "5.2MB / 10MB" or "5.2/10 MB")
    byte_match = re.search(r'([\d.]+)\s*(?:MB|mb|KB|kb)?\s*/\s*([\d.]+)\s*(?:MB|mb|KB|kb)?', line)
    if byte_match and 'download_percent' not in progress:
        try:
            current = float(byte_match.group(1))
            total = float(byte_match.group(2))
            if total > 0:
                progress['download_percent'] = min(100, (current / total) * 100)
        except (ValueError, ZeroDivisionError):
            pass
    
    # Parse downloaded/decrypted status
    if 'Downloaded' in line:
        progress['phase'] = 'downloaded'
    elif 'Decrypted' in line:
        progress['phase'] = 'decrypted'
    elif 'Downloading' in line:
        progress['phase'] = 'downloading'
    elif 'Decrypting' in line:
        progress['phase'] = 'decrypting'
    elif 'Fetching' in line or 'Getting' in line:
        progress['phase'] = 'fetching'
    
    return progress if progress else None


def wrapper_health_monitor():
    """Background thread to monitor wrapper health and restart if needed"""
    import socket
    import time
    
    logger.info("Wrapper health monitor started")
    consecutive_failures = 0
    check_interval = 60  # Check every 60 seconds
    
    while True:
        try:
            time.sleep(check_interval)
            
            # Try to connect to wrapper port
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex(('127.0.0.1', 30020))
                sock.close()
                
                if result == 0:
                    # Wrapper is responding, reset failure counter
                    if consecutive_failures > 0:
                        logger.info("Wrapper health check: OK (recovered)")
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(f"Wrapper health check failed: port not responding (failures: {consecutive_failures})")
                    
            except Exception as e:
                consecutive_failures += 1
                logger.warning(f"Wrapper health check failed: {e} (failures: {consecutive_failures})")
            
            # A playback-lease rejection intentionally stops the wrapper. Restarting it
            # here would immediately reclaim the Apple Music session from other devices.
            # Download-specific recovery starts the wrapper only when it is actually needed.
            if consecutive_failures == 3:
                logger.warning("Wrapper remains stopped and will restart when a download needs it")
                    
        except Exception as e:
            logger.error(f"Wrapper health monitor error: {e}")


background_workers_started = False


def start_background_workers():
    """Start one set of background workers for the active server instance."""
    global background_workers_started
    if background_workers_started:
        return

    worker_thread = threading.Thread(target=download_worker, daemon=True)
    worker_thread.start()
    logger.info("Download worker thread started")
    
    # Start wrapper health monitor
    health_monitor_thread = threading.Thread(target=wrapper_health_monitor, daemon=True)
    health_monitor_thread.start()
    logger.info("Wrapper health monitor started")
    background_workers_started = True


# Routes
@app.route('/')
def index():
    """Main page"""
    return render_template('index.html', cache_v=CACHE_VERSION)


@app.route('/settings')
def settings_page():
    """Settings page"""
    config = load_config()
    return render_template('settings.html', config=config, cache_v=CACHE_VERSION)


@app.route('/downloads/<path:filename>')
def serve_download(filename):
    """Serve downloaded files"""
    return send_from_directory(DOWNLOADS_DIR, filename)


# API Routes
@app.route('/api/download', methods=['POST'])
def start_download():
    """Start a new download"""
    # Check if Docker is running first
    if not check_docker_status():
        return jsonify({
            'success': False,
            'error': 'Docker is not running. Please start Docker Desktop first.',
            'docker_error': True
        }), 503
    
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Parse URL to validate and get info
    url_info = parse_apple_music_url(url)
    if not url_info:
        return jsonify({'error': 'Invalid Apple Music URL'}), 400
    
    # Get debug mode from config
    config = load_config()
    debug_mode = config.get('debug-mode', False)
    storefront = config.get('storefront', 'us')
    
    # Accept optional name, artist, and artwork from frontend
    item_name = data.get('name') or ''
    item_artist = data.get('artist') or ''
    item_artwork = data.get('artwork') or ''
    
    # If name not provided, try to fetch from iTunes API (quick lookup, non-blocking on failure)
    if not item_name:
        try:
            item_id = url_info['id']
            item_type = url_info['type']
            lookup_url = None
            
            if item_type == 'song':
                lookup_url = f'https://itunes.apple.com/lookup?id={item_id}&country={storefront}'
            elif item_type == 'album':
                lookup_url = f'https://itunes.apple.com/lookup?id={item_id}&entity=album&country={storefront}'
            
            if lookup_url:
                lookup_response = requests.get(lookup_url, timeout=2)
                if lookup_response.status_code == 200:
                    results = lookup_response.json().get('results', [])
                    if results:
                        result = results[0]
                        if item_type == 'song':
                            item_name = result.get('trackName', '')
                            item_artist = result.get('artistName', '')
                            if not item_artwork:
                                item_artwork = result.get('artworkUrl100', '').replace('100x100', '3000x3000')
                        elif item_type == 'album':
                            item_name = result.get('collectionName', '')
                            item_artist = result.get('artistName', '')
                            if not item_artwork:
                                item_artwork = result.get('artworkUrl100', '').replace('100x100', '3000x3000')
        except Exception as e:
            logger.debug(f"Metadata lookup skipped: {e}")
    
    # Add name, artist, and artwork to url_info
    url_info['name'] = item_name or url_info['type'].capitalize()
    url_info['artist'] = item_artist or ''
    url_info['artwork'] = item_artwork or ''

    selected_tracks = data.get('selectedTracks') or []
    try:
        selected_tracks = sorted({int(track) for track in selected_tracks if int(track) > 0})
    except (TypeError, ValueError):
        return jsonify({'error': 'Selected tracks must be positive track numbers'}), 400

    options = {
        'quality': data.get('quality', 'alac'),
        'select': bool(selected_tracks) and url_info['type'] == 'album',
        'selected_tracks': selected_tracks,
        'song': data.get('song', False) or url_info['type'] == 'song',
        'debug': debug_mode,
        'downloader_path': data.get('downloader_path', BASE_DIR)
    }
    
    download_id = str(uuid.uuid4())[:8]
    
    download = {
        'id': download_id,
        'url': url,
        'url_info': url_info,
        'options': options,
        'status': 'queued',
        'created_at': datetime.now().isoformat(),
        'output': [],
        'progress': None
    }
    download_id, was_queued = register_download(download)
    if was_queued:
        download_queue.put((download_id, url, options))
    
    return jsonify({
        'success': True,
        'download_id': download_id,
        'duplicate': not was_queued,
        'message': 'Download added to queue' if was_queued else 'Download is already queued or running'
    })


@app.route('/api/downloads')
def get_downloads():
    """Get all downloads"""
    with download_lock:
        return jsonify(list(downloads.values()))


@app.route('/api/downloads/<download_id>')
def get_download(download_id):
    """Get specific download status"""
    with download_lock:
        if download_id in downloads:
            return jsonify(downloads[download_id])
    return jsonify({'error': 'Download not found'}), 404


@app.route('/api/downloads/<download_id>', methods=['DELETE'])
def remove_download(download_id):
    """Remove download from history"""
    with download_lock:
        if download_id in downloads:
            if downloads[download_id].get('status') in ACTIVE_DOWNLOAD_STATUSES:
                return jsonify({'error': 'Active downloads cannot be removed'}), 409
            release_download_registration_locked(download_id)
            del downloads[download_id]
            return jsonify({'success': True})
    return jsonify({'error': 'Download not found'}), 404


def normalize_catalog_match_text(value):
    """Normalize catalog text for exact title and artist comparisons."""
    return re.sub(r'[^\w]+', '', str(value or '').casefold())


_library_catalog_search_lock = threading.Lock()
_library_catalog_search_last_at = 0.0


def get_available_library_song_ids(tracks, storefront):
    """Return catalog IDs that currently resolve as audio songs in one batch."""
    catalog_ids = list(dict.fromkeys(
        str(track.get('catalogId') or '').strip() for track in tracks if track.get('catalogId')
    ))
    tokens = get_wrapper_tokens(retry_on_timeout=False)
    dev_token = tokens.get('dev_token') if tokens else None
    if not catalog_ids or not dev_token:
        return None

    headers = {
        'Authorization': f'Bearer {dev_token}',
        'Origin': 'https://music.apple.com',
        'Referer': 'https://music.apple.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    available_ids = set()

    try:
        for offset in range(0, len(catalog_ids), 100):
            response = requests.get(
                f'https://amp-api.music.apple.com/v1/catalog/{storefront}/songs',
                headers=headers,
                params={'ids': ','.join(catalog_ids[offset:offset + 100])},
                timeout=15
            )
            if response.status_code != 200:
                logger.warning(f"Batch song lookup failed: HTTP {response.status_code}")
                return None
            available_ids.update(str(item.get('id')) for item in response.json().get('data', []))
        return available_ids
    except requests.RequestException as error:
        logger.warning(f"Batch song lookup failed: {error}")
        return None


def resolve_library_track_song(track, storefront, available_song_ids=None):
    """Resolve a library track to an audio song, returning (track, changed)."""
    global _library_catalog_search_last_at

    catalog_id = str(track.get('catalogId') or '').strip()
    catalog_type = re.sub(r'[^a-z]', '', str(track.get('catalogType') or '').casefold())

    if not catalog_id:
        return None, False
    if available_song_ids is not None and catalog_id in available_song_ids:
        return dict(track), False

    tokens = get_wrapper_tokens(retry_on_timeout=False)
    dev_token = tokens.get('dev_token') if tokens else None
    if not dev_token:
        logger.warning(f"Cannot resolve library catalog item {catalog_id}: no developer token")
        return (dict(track), False) if catalog_type in {'song', 'songs', ''} else (None, False)

    headers = {
        'Authorization': f'Bearer {dev_token}',
        'Origin': 'https://music.apple.com',
        'Referer': 'https://music.apple.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        # Older clients do not send catalogType, so first check whether the ID
        # already identifies an audio song before falling back to search.
        if available_song_ids is None and catalog_type not in {'musicvideo', 'musicvideos'}:
            response = requests.get(
                f'https://amp-api.music.apple.com/v1/catalog/{storefront}/songs/{catalog_id}',
                headers=headers,
                timeout=10
            )
            if response.status_code == 200 and response.json().get('data'):
                resolved_track = dict(track)
                resolved_track['catalogType'] = 'songs'
                return resolved_track, False

        track_name = str(track.get('name') or '').strip()
        artist_name = str(track.get('artistName') or '').strip()
        if not track_name or not artist_name:
            logger.warning(f"Cannot resolve non-song catalog item {catalog_id}: missing title or artist")
            return None, False

        normalized_title = normalize_catalog_match_text(track_name)
        normalized_artist = normalize_catalog_match_text(artist_name)

        def select_match(candidates):
            title_matches = [
                candidate for candidate in candidates
                if normalize_catalog_match_text(candidate.get('attributes', {}).get('name')) == normalized_title
            ]
            exact_match = next((
                candidate for candidate in title_matches
                if normalize_catalog_match_text(candidate.get('attributes', {}).get('artistName')) == normalized_artist
            ), None)
            return exact_match or (title_matches[0] if len(title_matches) == 1 else None)

        response = None
        with _library_catalog_search_lock:
            search_delay = 1.1 - (time.monotonic() - _library_catalog_search_last_at)
            if search_delay > 0:
                time.sleep(search_delay)

            for attempt in range(4):
                response = requests.get(
                    f'https://amp-api.music.apple.com/v1/catalog/{storefront}/search',
                    headers=headers,
                    params={
                        'term': f'{track_name} {artist_name}',
                        'types': 'songs',
                        'limit': 25
                    },
                    timeout=15
                )
                _library_catalog_search_last_at = time.monotonic()
                if response.status_code != 429:
                    break
                if attempt < 3:
                    time.sleep(2 ** (attempt + 1))

        candidates = []
        if response is not None and response.status_code == 200:
            candidates = response.json().get('results', {}).get('songs', {}).get('data', [])
        match = select_match(candidates)

        if not match:
            fallback_response = requests.get(
                'https://itunes.apple.com/search',
                params={
                    'term': f'{track_name} {artist_name}',
                    'country': storefront,
                    'media': 'music',
                    'entity': 'song',
                    'limit': 25
                },
                timeout=15
            )
            if fallback_response.status_code == 200:
                fallback_candidates = [
                    {
                        'id': str(candidate.get('trackId')),
                        'attributes': {
                            'name': candidate.get('trackName'),
                            'artistName': candidate.get('artistName')
                        }
                    }
                    for candidate in fallback_response.json().get('results', [])
                    if candidate.get('trackId')
                ]
                match = select_match(fallback_candidates)

        if not match:
            logger.warning(f"No exact audio song match for {artist_name} - {track_name} ({catalog_id})")
            return None, False

        attributes = match.get('attributes', {})
        resolved_track = dict(track)
        resolved_track.update({
            'catalogId': str(match.get('id')),
            'catalogType': 'songs',
            'name': attributes.get('name') or track_name,
            'artistName': attributes.get('artistName') or artist_name
        })
        artwork = attributes.get('artwork', {})
        if artwork.get('url'):
            resolved_track['artwork'] = artwork['url'].replace('{w}', '100').replace('{h}', '100')

        logger.info(
            f"Resolved library catalog item {catalog_id} to audio song {resolved_track['catalogId']} "
            f"({resolved_track['artistName']} - {resolved_track['name']})"
        )
        return resolved_track, resolved_track['catalogId'] != catalog_id
    except requests.RequestException as error:
        logger.warning(f"Failed to resolve library catalog item {catalog_id}: {error}")
        return None, False


@app.route('/api/library/download', methods=['POST'])
def download_library_tracks():
    """Download tracks from library playlist using catalog IDs"""
    data = request.json
    # Support both old format (catalogIds) and new format (trackInfo)
    track_info = data.get('trackInfo', [])
    catalog_ids = data.get('catalogIds', [])
    quality = data.get('quality', 'aac')
    playlist_name = data.get('playlistName', 'Library Playlist')
    playlist_id = data.get('playlistId')
    add_to_auto_download = data.get('addToAutoDownload', False)
    
    # Convert old format to new format if needed
    if catalog_ids and not track_info:
        track_info = [{'catalogId': cid, 'name': '', 'artistName': ''} for cid in catalog_ids]
    
    if not track_info:
        return jsonify({'error': 'No tracks selected'}), 400
    
    # Filter out tracks without catalog IDs
    valid_tracks = [t for t in track_info if t.get('catalogId')]
    
    if not valid_tracks:
        return jsonify({'error': 'Selected tracks are not available in Apple Music catalog'}), 400
    
    # Get debug mode from config
    config = load_config()
    debug_mode = config.get('debug-mode', False)
    storefront = config.get('storefront', 'us')
    
    # Queue downloads for each track
    download_ids = []
    duplicate_count = 0
    resolved_count = 0
    resolution_failure_count = 0
    available_song_ids = get_available_library_song_ids(valid_tracks, storefront)
    for track in valid_tracks:
        source_catalog_id = str(track['catalogId'])
        track, was_resolved = resolve_library_track_song(track, storefront, available_song_ids)
        if not track:
            resolution_failure_count += 1
            continue
        if was_resolved:
            resolved_count += 1

        catalog_id = track['catalogId']
        track_name = track.get('name', '')
        artist_name = track.get('artistName', '')
        
        # Build song URL from catalog ID
        url = f'https://music.apple.com/{storefront}/song/{catalog_id}'
        
        options = {
            'quality': quality,
            'select': False,
            'song': True,  # Single song download
            'debug': debug_mode,
            'downloader_path': BASE_DIR
        }
        
        download_id = str(uuid.uuid4())[:8]
        
        download = {
            'id': download_id,
            'url': url,
            'url_info': {
                'type': 'song',
                'storefront': storefront,
                'id': catalog_id,
                'name': track_name,
                'artist': artist_name,
                'artwork': track.get('artwork', '')
            },
            'options': options,
            'status': 'queued',
            'created_at': datetime.now().isoformat(),
            'output': [],
            'progress': None,
            'source': f'Library: {playlist_name}',
            'playlist_id': playlist_id,
            'playlist_name': playlist_name,
            'source_catalog_id': source_catalog_id,
            'auto_download': add_to_auto_download
        }
        download_id, was_queued = register_download(download)
        if not was_queued:
            duplicate_count += 1
            continue

        download_queue.put((download_id, url, options))
        download_ids.append(download_id)
    
    # Add playlist to auto-download if downloading all tracks
    added_to_auto_download = False
    if add_to_auto_download and playlist_id and playlist_name:
        add_playlist_to_auto_download_if_complete(playlist_id, playlist_name)
        added_to_auto_download = True
    
    return jsonify({
        'success': True,
        'download_ids': download_ids,
        'message': f'Queued {len(download_ids)} tracks for download',
        'skipped': len(track_info) - len(valid_tracks) + resolution_failure_count,
        'resolved': resolved_count,
        'duplicates': duplicate_count,
        'addedToAutoDownload': added_to_auto_download
    })


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    return jsonify(load_config())


@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration"""
    data = request.json
    config = load_config()
    config.update(data)
    save_config(config)
    
    # Update downloads directory if changed
    update_downloads_dir()
    
    # Update auto-download scheduler if settings changed
    auto_download_settings = data.get('auto-download', {})
    if auto_download_settings:
        update_auto_download_scheduler(auto_download_settings)
    
    return jsonify({'success': True, 'config': config})


# ============================================================
# Auto-Download Settings and Endpoints
# ============================================================

AUTO_DOWNLOAD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auto_download.json')
auto_download_timer = None
auto_download_next_check = None
auto_download_scheduler_generation = 0  # Tracks scheduler updates to prevent duplicate timers

def load_auto_download_settings():
    """Load auto-download settings from file"""
    if os.path.exists(AUTO_DOWNLOAD_FILE):
        try:
            with open(AUTO_DOWNLOAD_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'playlists': [], 'downloaded_tracks': {}}


def save_auto_download_settings(settings):
    """Save auto-download settings to file"""
    with open(AUTO_DOWNLOAD_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


@app.route('/api/auto-download/settings')
def get_auto_download_settings():
    """Get auto-download settings and status"""
    config = load_config()
    auto_config = config.get('auto-download', {})
    settings = load_auto_download_settings()
    
    response = jsonify({
        'enabled': auto_config.get('enabled', False),
        'interval': auto_config.get('interval', 60),
        'playlists': settings.get('playlists', []),
        'nextCheck': auto_download_next_check.isoformat() if auto_download_next_check else None
    })
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/auto-download/playlists', methods=['GET'])
def get_auto_download_playlists():
    """Get list of playlists in auto-download"""
    settings = load_auto_download_settings()
    return jsonify({'playlists': settings.get('playlists', [])})


@app.route('/api/auto-download/playlists', methods=['POST'])
def add_auto_download_playlist():
    """Add a playlist to auto-download"""
    data = request.json
    playlist_id = data.get('id')
    playlist_name = data.get('name')
    
    if not playlist_id or not playlist_name:
        return jsonify({'error': 'Playlist ID and name required'}), 400
    
    settings = load_auto_download_settings()
    playlists = settings.get('playlists', [])
    
    # Check if already exists
    if any(p['id'] == playlist_id for p in playlists):
        return jsonify({'error': 'Playlist already added', 'playlists': playlists}), 400
    
    playlists.append({
        'id': playlist_id,
        'name': playlist_name,
        'addedAt': datetime.now().isoformat(),
        'lastChecked': None,
        'autoAdded': False
    })
    
    settings['playlists'] = playlists
    save_auto_download_settings(settings)
    
    return jsonify({'success': True, 'playlists': playlists})


@app.route('/api/auto-download/playlists/<playlist_id>', methods=['DELETE'])
def remove_auto_download_playlist(playlist_id):
    """Remove a playlist from auto-download"""
    settings = load_auto_download_settings()
    playlists = settings.get('playlists', [])
    
    settings['playlists'] = [p for p in playlists if p['id'] != playlist_id]
    save_auto_download_settings(settings)
    
    return jsonify({'success': True, 'playlists': settings['playlists']})


def add_playlist_to_auto_download_if_complete(playlist_id, playlist_name):
    """Add a playlist to auto-download automatically when all tracks are downloaded"""
    settings = load_auto_download_settings()
    playlists = settings.get('playlists', [])
    
    # Check if already exists
    if any(p['id'] == playlist_id for p in playlists):
        return
    
    playlists.append({
        'id': playlist_id,
        'name': playlist_name,
        'addedAt': datetime.now().isoformat(),
        'lastChecked': datetime.now().isoformat(),
        'autoAdded': True
    })
    
    settings['playlists'] = playlists
    save_auto_download_settings(settings)
    logger.info(f"Auto-added playlist '{playlist_name}' to auto-download")


def update_auto_download_scheduler(settings):
    """Update the auto-download scheduler based on settings"""
    global auto_download_timer, auto_download_next_check, auto_download_scheduler_generation
    
    # Increment generation to invalidate any in-flight check's finally block
    auto_download_scheduler_generation += 1
    
    # Cancel existing timer
    if auto_download_timer:
        auto_download_timer.cancel()
        auto_download_timer = None
    
    enabled = settings.get('enabled', False)
    interval_minutes = settings.get('interval', 60)
    
    if enabled:
        # Schedule next check
        interval_seconds = interval_minutes * 60
        auto_download_next_check = datetime.now() + timedelta(seconds=interval_seconds)
        auto_download_timer = threading.Timer(interval_seconds, run_auto_download_check)
        auto_download_timer.daemon = True
        auto_download_timer.start()
        logger.info(f"Auto-download scheduled: next check in {interval_minutes} minutes")
    else:
        auto_download_next_check = None
        logger.info("Auto-download disabled")


def run_auto_download_check():
    """Run auto-download check for all monitored playlists"""
    global auto_download_timer, auto_download_next_check
    
    # Capture the current scheduler generation to detect if update_auto_download_scheduler
    # was called while this check is running (which would mean it already set up a new timer)
    my_generation = auto_download_scheduler_generation
    
    logger.info("Running auto-download check...")
    
    config = load_config()
    auto_config = config.get('auto-download', {})
    storefront = config.get('storefront', 'us')
    
    if not auto_config.get('enabled', False):
        logger.info("Auto-download is disabled, skipping check")
        return
    
    settings = load_auto_download_settings()
    playlists = settings.get('playlists', [])
    downloaded_tracks = settings.get('downloaded_tracks', {})
    
    try:
        # Get tokens for API access
        tokens = get_wrapper_tokens(retry_on_timeout=False)
        if not tokens:
            logger.warning("No tokens available for auto-download")
            return
        
        dev_token = tokens.get('dev_token')
        music_token = tokens.get('music_token')
        
        headers = {
            'Authorization': f'Bearer {dev_token}',
            'Media-User-Token': music_token,
            'Origin': 'https://music.apple.com',
        }
        
        new_tracks = []
        
        for playlist in playlists:
            playlist_id = playlist['id']
            logger.info(f"Checking playlist: {playlist['name']}")
            
            try:
                # Fetch playlist tracks
                response = requests.get(
                    f'https://amp-api.music.apple.com/v1/me/library/playlists/{playlist_id}/tracks',
                    headers=headers,
                    params={'limit': 100, 'include[library-songs]': 'catalog'},
                    timeout=30
                )
                
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch playlist {playlist_id}: {response.status_code}")
                    continue
                
                tracks = response.json().get('data', [])
                playlist_downloaded = downloaded_tracks.get(playlist_id, set())
                if isinstance(playlist_downloaded, list):
                    playlist_downloaded = set(playlist_downloaded)
                
                for track in tracks:
                    # Get catalog ID
                    attributes = track.get('attributes', {})
                    play_params = attributes.get('playParams', {})
                    catalog_id = play_params.get('catalogId')
                    catalog_type = play_params.get('kind')
                    if not catalog_id:
                        rels = track.get('relationships', {}).get('catalog', {}).get('data', [])
                        if rels:
                            catalog_id = rels[0].get('id')
                            catalog_type = rels[0].get('type') or catalog_type
                    
                    if catalog_id and catalog_id not in playlist_downloaded:
                        new_tracks.append({
                            'catalogId': catalog_id,
                            'catalogType': catalog_type,
                            'name': attributes.get('name', 'Unknown'),
                            'artistName': attributes.get('artistName', 'Unknown'),
                            'playlist_id': playlist_id
                        })
                
                # Update last checked time
                playlist['lastChecked'] = datetime.now().isoformat()
                
            except Exception as e:
                logger.error(f"Error checking playlist {playlist_id}: {e}")
        
        # Save updated settings
        settings['playlists'] = playlists
        save_auto_download_settings(settings)
        
        # Queue new tracks for download
        if new_tracks:
            logger.info(f"Found {len(new_tracks)} new tracks to download")
            available_song_ids = get_available_library_song_ids(new_tracks, storefront)
            for track in new_tracks:
                source_catalog_id = str(track['catalogId'])
                track, was_resolved = resolve_library_track_song(
                    track, storefront, available_song_ids
                )
                if not track:
                    logger.warning(f"Skipping unavailable auto-download track {source_catalog_id}")
                    continue
                if was_resolved:
                    logger.info(f"Auto-download resolved {source_catalog_id} to {track['catalogId']}")

                # Create download URL
                url = f"https://music.apple.com/{storefront}/song/{track['catalogId']}"
                
                # Add to download queue
                download_id = str(uuid.uuid4())
                
                # Default options for auto-download (use AAC for compatibility)
                options = {
                    'quality': 'aac',
                    'song': True,
                    'debug': False
                }
                
                download = {
                    'id': download_id,
                    'url': url,
                    'url_info': {
                        'type': 'song',
                        'storefront': storefront,
                        'id': track['catalogId'],
                        'name': track['name'],
                        'artist': track['artistName'],
                        'artwork': track.get('artwork', '')
                    },
                    'options': options,
                    'status': 'queued',
                    'progress': None,
                    'output': [],
                    'message': f"Auto-download: {track['name']} by {track['artistName']}",
                    'created_at': datetime.now().isoformat(),
                    'type': 'song',
                    'title': track['name'],
                    'subtitle': track['artistName'],
                    'auto_download': True,
                    'playlist_id': track['playlist_id'],
                    'source_catalog_id': source_catalog_id
                }
                download_id, was_queued = register_download(download)
                if was_queued:
                    download_queue.put((download_id, url, options))
                else:
                    logger.info(f"Skipping duplicate active auto-download: {url}")
                
        else:
            logger.info("No new tracks found")
        
    except Exception as e:
        logger.error(f"Auto-download check error: {e}")
    
    finally:
        # Only reschedule if the scheduler wasn't updated externally while we were running.
        # If update_auto_download_scheduler() was called during this check, it already
        # set up a new timer — rescheduling here would create a duplicate.
        if my_generation != auto_download_scheduler_generation:
            logger.info("Auto-download scheduler was updated during check, skipping reschedule")
        else:
            # Re-read config to check if auto-download is still enabled
            current_config = load_config()
            current_auto_config = current_config.get('auto-download', {})
            if not current_auto_config.get('enabled', False):
                logger.info("Auto-download was disabled during check, not rescheduling")
                auto_download_next_check = None
            else:
                interval_minutes = current_auto_config.get('interval', 60)
                interval_seconds = interval_minutes * 60
                auto_download_next_check = datetime.now() + timedelta(seconds=interval_seconds)
                auto_download_timer = threading.Timer(interval_seconds, run_auto_download_check)
                auto_download_timer.daemon = True
                auto_download_timer.start()
                logger.info(f"Auto-download rescheduled: next check in {interval_minutes} minutes")


def mark_track_downloaded_for_auto_download(catalog_id, playlist_id=None):
    """Mark a track as downloaded for auto-download tracking"""
    settings = load_auto_download_settings()
    downloaded_tracks = settings.get('downloaded_tracks', {})
    
    if playlist_id:
        if playlist_id not in downloaded_tracks:
            downloaded_tracks[playlist_id] = []
        if catalog_id not in downloaded_tracks[playlist_id]:
            downloaded_tracks[playlist_id].append(catalog_id)
    
    settings['downloaded_tracks'] = downloaded_tracks
    save_auto_download_settings(settings)


# Import timedelta for scheduling
from datetime import timedelta


@app.route('/api/parse-url', methods=['POST'])
def parse_url():
    """Parse an Apple Music URL"""
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    url_info = parse_apple_music_url(url)
    if url_info:
        return jsonify({'success': True, 'info': url_info})
    return jsonify({'error': 'Invalid Apple Music URL'}), 400


@app.route('/api/fetch-metadata', methods=['POST'])
def fetch_metadata():
    """Fetch metadata from iTunes Search API (no auth required)"""
    logger.info("=== Fetch Metadata Request Started ===")
    data = request.json
    url = data.get('url', '').strip()
    logger.info(f"URL received: {url}")
    
    if not url:
        logger.error("No URL provided")
        return jsonify({'error': 'URL is required'}), 400
    
    url_info = parse_apple_music_url(url)
    if not url_info:
        logger.error(f"Failed to parse URL: {url}")
        return jsonify({'error': 'Invalid Apple Music URL'}), 400
    
    logger.info(f"Parsed URL info: {url_info}")
    
    item_type = url_info['type']
    item_id = url_info['id']
    storefront = url_info['storefront']
    
    # Use iTunes Lookup API - no authentication required!
    # This API returns album info and tracks
    lookup_url = f'https://itunes.apple.com/lookup?id={item_id}&entity=song&country={storefront}'
    
    logger.info(f"iTunes API URL: {lookup_url}")
    
    try:
        response = requests.get(lookup_url, timeout=10)
        logger.info(f"Response status code: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"iTunes API error: {response.status_code}")
            return jsonify({'error': f'iTunes API error: {response.status_code}'}), response.status_code
        
        itunes_data = response.json()
        results = itunes_data.get('results', [])
        
        if not results:
            logger.error("No results from iTunes API")
            return jsonify({'error': 'Album/song not found'}), 404
        
        # First result is the album/collection, rest are songs
        album_info = results[0]
        tracks = [r for r in results[1:] if r.get('wrapperType') == 'track']
        
        # Build response in expected format
        metadata = {
            'id': str(album_info.get('collectionId', item_id)),
            'type': item_type,
            'attributes': {
                'name': album_info.get('collectionName', album_info.get('trackName', 'Unknown')),
                'artistName': album_info.get('artistName', 'Unknown Artist'),
                'artwork': {
                    'url': album_info.get('artworkUrl100', '').replace('100x100', '{w}x{h}')
                },
                'releaseDate': album_info.get('releaseDate', ''),
                'trackCount': album_info.get('trackCount', len(tracks)),
                'genreNames': [album_info.get('primaryGenreName', 'Music')]
            },
            'relationships': {
                'tracks': {
                    'data': [
                        {
                            'id': str(track.get('trackId', '')),
                            'attributes': {
                                'name': track.get('trackName', ''),
                                'artistName': track.get('artistName', ''),
                                'trackNumber': track.get('trackNumber', i + 1),
                                'durationInMillis': track.get('trackTimeMillis', 0),
                                'discNumber': track.get('discNumber', 1)
                            }
                        }
                        for i, track in enumerate(tracks)
                    ]
                }
            }
        }
        
        logger.info(f"Successfully fetched metadata: {metadata['attributes']['name']} by {metadata['attributes']['artistName']}")
        logger.info(f"Found {len(tracks)} tracks")
        
        return jsonify({'success': True, 'data': metadata})
    
    except requests.exceptions.RequestException as e:
        logger.exception(f"Request exception: {str(e)}")
        return jsonify({'error': f'Failed to connect to iTunes API: {str(e)}'}), 500


@app.route('/api/search', methods=['POST'])
def search_apple_music():
    """Search Apple Music for artists, albums, and songs"""
    data = request.json
    query = data.get('query', '').strip()
    search_type = data.get('type', 'all')  # 'all', 'artist', 'song', 'album'
    limit = min(data.get('limit', 25), 50)  # Max 50 results
    
    if not query:
        return jsonify({'error': 'Search query is required'}), 400
    
    config = load_config()
    storefront = config.get('storefront', 'us')
    query_lower = query.lower()
    
    def calculate_artist_relevance(artist_name, query_lower):
        """Calculate how relevant an artist is to the search query"""
        name_lower = artist_name.lower()
        
        if name_lower == query_lower:
            return 100  # Exact match
        elif name_lower.startswith(query_lower):
            return 95  # Name starts with query (e.g., "MoxiFloxi" for "mox")
        else:
            # Check if query matches start of any word in the name
            words = name_lower.replace('-', ' ').replace('_', ' ').split()
            for word in words:
                if word.startswith(query_lower):
                    return 90  # Word in name starts with query (e.g., "DJ Mox" for "mox")
            
            if query_lower in name_lower:
                return 80  # Name contains query somewhere
            else:
                return 50  # Fuzzy/partial match from iTunes
    
    try:
        # First, do a dedicated artist search to find matching artists (increased limit)
        artist_search_url = f'https://itunes.apple.com/search?term={requests.utils.quote(query)}&entity=musicArtist&limit=25&country={storefront}'
        logger.info(f"Artist Search URL: {artist_search_url}")
        
        artist_response = requests.get(artist_search_url, timeout=10)
        dedicated_artists = []
        
        if artist_response.status_code == 200:
            artist_data = artist_response.json()
            for item in artist_data.get('results', []):
                if item.get('wrapperType') == 'artist':
                    artist_name = item.get('artistName', 'Unknown Artist')
                    artist_id = str(item.get('artistId', ''))
                    relevance = calculate_artist_relevance(artist_name, query_lower)
                    
                    dedicated_artists.append({
                        'id': artist_id,
                        'name': artist_name,
                        'genre': item.get('primaryGenreName', ''),
                        'url': item.get('artistLinkUrl', ''),
                        'artwork': '',  # Will be filled later
                        'type': 'artist',
                        'relevance': relevance
                    })
        
        # Now do the regular combined search
        entity_map = {
            'all': 'musicArtist,album,song',
            'artist': 'musicArtist',
            'song': 'song',
            'album': 'album'
        }
        entity = entity_map.get(search_type, 'musicArtist,album,song')
        
        search_url = f'https://itunes.apple.com/search?term={requests.utils.quote(query)}&entity={entity}&limit={limit}&country={storefront}'
        logger.info(f"Search URL: {search_url}")
        
        response = requests.get(search_url, timeout=10)
        
        if response.status_code != 200:
            return jsonify({'error': f'iTunes API error: {response.status_code}'}), response.status_code
        
        itunes_data = response.json()
        results = itunes_data.get('results', [])
        
        # Organize results by type
        albums = []
        songs = []
        artist_artwork_cache = {}  # Cache artist artwork from albums/songs
        seen_artist_ids = set()  # Track artists we've already added
        
        # Add dedicated artists to seen set
        for artist in dedicated_artists:
            seen_artist_ids.add(artist['id'])
        
        # First pass: collect albums and songs, build artist artwork cache
        for item in results:
            wrapper_type = item.get('wrapperType', '')
            artist_id = str(item.get('artistId', ''))
            
            if wrapper_type == 'collection' or item.get('collectionType') == 'Album':
                artwork = item.get('artworkUrl100', '').replace('100x100', '300x300')
                if artist_id and artwork and artist_id not in artist_artwork_cache:
                    artist_artwork_cache[artist_id] = artwork
                albums.append({
                    'id': str(item.get('collectionId', '')),
                    'name': item.get('collectionName', 'Unknown Album'),
                    'artist': item.get('artistName', 'Unknown Artist'),
                    'artistId': artist_id,
                    'artwork': artwork,
                    'releaseDate': item.get('releaseDate', ''),
                    'trackCount': item.get('trackCount', 0),
                    'genre': item.get('primaryGenreName', ''),
                    'url': item.get('collectionViewUrl', ''),
                    'type': 'album'
                })
            elif wrapper_type == 'track':
                artwork = item.get('artworkUrl100', '').replace('100x100', '300x300')
                if artist_id and artwork and artist_id not in artist_artwork_cache:
                    artist_artwork_cache[artist_id] = artwork
                songs.append({
                    'id': str(item.get('trackId', '')),
                    'name': item.get('trackName', 'Unknown Song'),
                    'artist': item.get('artistName', 'Unknown Artist'),
                    'artistId': str(item.get('artistId', '')),
                    'album': item.get('collectionName', ''),
                    'albumId': str(item.get('collectionId', '')),
                    'artwork': item.get('artworkUrl100', '').replace('100x100', '300x300'),
                    'duration': item.get('trackTimeMillis', 0),
                    'trackNumber': item.get('trackNumber', 0),
                    'url': item.get('trackViewUrl', ''),
                    'previewUrl': item.get('previewUrl', ''),
                    'type': 'song'
                })
        
        # Second pass: collect additional artists from combined search (not already in dedicated artists)
        for item in results:
            wrapper_type = item.get('wrapperType', '')
            
            if wrapper_type == 'artist':
                artist_id = str(item.get('artistId', ''))
                if artist_id not in seen_artist_ids:
                    seen_artist_ids.add(artist_id)
                    artist_name = item.get('artistName', 'Unknown Artist')
                    relevance = calculate_artist_relevance(artist_name, query_lower)
                    
                    dedicated_artists.append({
                        'id': artist_id,
                        'name': artist_name,
                        'genre': item.get('primaryGenreName', ''),
                        'url': item.get('artistLinkUrl', ''),
                        'artwork': artist_artwork_cache.get(artist_id, ''),
                        'type': 'artist',
                        'relevance': relevance
                    })
        
        # Sort artists: highest relevance first, then alphabetically
        dedicated_artists.sort(key=lambda x: (-x.get('relevance', 0), x.get('name', '').lower()))
        
        # Fetch artwork for artists that don't have it (limit to first 5 to avoid too many API calls)
        artists_needing_artwork = [a for a in dedicated_artists if not a.get('artwork')][:5]
        for artist in artists_needing_artwork:
            if artist.get('id'):
                # First check if we have it in cache from albums/songs
                if artist['id'] in artist_artwork_cache:
                    artist['artwork'] = artist_artwork_cache[artist['id']]
                else:
                    try:
                        # Fetch one album to get artwork
                        lookup_url = f'https://itunes.apple.com/lookup?id={artist["id"]}&entity=album&limit=1&country={storefront}'
                        lookup_resp = requests.get(lookup_url, timeout=3)
                        if lookup_resp.status_code == 200:
                            lookup_data = lookup_resp.json()
                            lookup_results = lookup_data.get('results', [])
                            for lr in lookup_results:
                                if lr.get('wrapperType') == 'collection':
                                    artist['artwork'] = lr.get('artworkUrl100', '').replace('100x100', '300x300')
                                    break
                    except Exception:
                        pass  # If we can't get artwork, just continue without it
        
        # Remove relevance field before returning (internal use only)
        artists = [{k: v for k, v in a.items() if k != 'relevance'} for a in dedicated_artists]
        
        return jsonify({
            'success': True,
            'query': query,
            'artists': artists,
            'albums': albums,
            'songs': songs,
            'total': len(artists) + len(albums) + len(songs)
        })
        
    except requests.exceptions.RequestException as e:
        logger.exception(f"Search request exception: {str(e)}")
        return jsonify({'error': f'Failed to search: {str(e)}'}), 500


@app.route('/api/artist/<artist_id>', methods=['GET'])
def get_artist_details(artist_id):
    """Get artist details including their albums and top songs"""
    config = load_config()
    storefront = config.get('storefront', 'us')
    
    try:
        # Get artist albums
        albums_url = f'https://itunes.apple.com/lookup?id={artist_id}&entity=album&limit=200&country={storefront}'
        response = requests.get(albums_url, timeout=10)
        
        if response.status_code != 200:
            return jsonify({'error': f'iTunes API error: {response.status_code}'}), response.status_code
        
        data = response.json()
        results = data.get('results', [])
        
        if not results:
            return jsonify({'error': 'Artist not found'}), 404
        
        # First result is artist info
        artist_info = results[0]
        albums = []
        
        for item in results[1:]:
            if item.get('wrapperType') == 'collection' and item.get('collectionType') == 'Album':
                albums.append({
                    'id': str(item.get('collectionId', '')),
                    'name': item.get('collectionName', 'Unknown Album'),
                    'artwork': item.get('artworkUrl100', '').replace('100x100', '300x300'),
                    'releaseDate': item.get('releaseDate', ''),
                    'trackCount': item.get('trackCount', 0),
                    'genre': item.get('primaryGenreName', ''),
                    'url': item.get('collectionViewUrl', ''),
                    'type': 'album'
                })
        
        # Sort albums by release date (newest first)
        albums.sort(key=lambda x: x.get('releaseDate', ''), reverse=True)
        
        # Get top songs for artist
        songs_url = f'https://itunes.apple.com/lookup?id={artist_id}&entity=song&limit=50&country={storefront}'
        songs_response = requests.get(songs_url, timeout=10)
        
        songs = []
        if songs_response.status_code == 200:
            songs_data = songs_response.json()
            songs_results = songs_data.get('results', [])[1:]  # Skip artist info
            
            for item in songs_results:
                if item.get('wrapperType') == 'track':
                    songs.append({
                        'id': str(item.get('trackId', '')),
                        'name': item.get('trackName', 'Unknown Song'),
                        'album': item.get('collectionName', ''),
                        'albumId': str(item.get('collectionId', '')),
                        'artwork': item.get('artworkUrl100', '').replace('100x100', '300x300'),
                        'duration': item.get('trackTimeMillis', 0),
                        'trackNumber': item.get('trackNumber', 0),
                        'url': item.get('trackViewUrl', ''),
                        'type': 'song'
                    })
        
        # Get artist artwork from first album
        artist_artwork = ''
        if albums:
            artist_artwork = albums[0].get('artwork', '')
        
        return jsonify({
            'success': True,
            'artist': {
                'id': str(artist_info.get('artistId', artist_id)),
                'name': artist_info.get('artistName', 'Unknown Artist'),
                'genre': artist_info.get('primaryGenreName', ''),
                'url': artist_info.get('artistLinkUrl', ''),
                'artwork': artist_artwork
            },
            'albums': albums,
            'songs': songs
        })
        
    except requests.exceptions.RequestException as e:
        logger.exception(f"Artist lookup exception: {str(e)}")
        return jsonify({'error': f'Failed to get artist details: {str(e)}'}), 500


@app.route('/api/album/<album_id>', methods=['GET'])
def get_album_details(album_id):
    """Get album details with all tracks"""
    config = load_config()
    storefront = config.get('storefront', 'us')
    
    try:
        lookup_url = f'https://itunes.apple.com/lookup?id={album_id}&entity=song&country={storefront}'
        response = requests.get(lookup_url, timeout=10)
        
        if response.status_code != 200:
            return jsonify({'error': f'iTunes API error: {response.status_code}'}), response.status_code
        
        data = response.json()
        results = data.get('results', [])
        
        if not results:
            return jsonify({'error': 'Album not found'}), 404
        
        album_info = results[0]
        tracks = []
        
        for item in results[1:]:
            if item.get('wrapperType') == 'track':
                tracks.append({
                    'id': str(item.get('trackId', '')),
                    'name': item.get('trackName', 'Unknown Song'),
                    'artist': item.get('artistName', ''),
                    'duration': item.get('trackTimeMillis', 0),
                    'trackNumber': item.get('trackNumber', 0),
                    'discNumber': item.get('discNumber', 1),
                    'url': item.get('trackViewUrl', ''),
                    'type': 'song'
                })
        
        # Sort by disc and track number
        tracks.sort(key=lambda x: (x.get('discNumber', 1), x.get('trackNumber', 0)))
        
        return jsonify({
            'success': True,
            'album': {
                'id': str(album_info.get('collectionId', album_id)),
                'name': album_info.get('collectionName', 'Unknown Album'),
                'artist': album_info.get('artistName', 'Unknown Artist'),
                'artistId': str(album_info.get('artistId', '')),
                'artwork': album_info.get('artworkUrl100', '').replace('100x100', '600x600'),
                'releaseDate': album_info.get('releaseDate', ''),
                'trackCount': album_info.get('trackCount', len(tracks)),
                'genre': album_info.get('primaryGenreName', ''),
                'url': album_info.get('collectionViewUrl', '')
            },
            'tracks': tracks
        })
        
    except requests.exceptions.RequestException as e:
        logger.exception(f"Album lookup exception: {str(e)}")
        return jsonify({'error': f'Failed to get album details: {str(e)}'}), 500


@app.route('/api/status')
def get_status():
    """Get system status"""
    status = {
        'queue_size': download_queue.qsize(),
        'active_downloads': sum(1 for d in downloads.values() if d['status'] == 'downloading'),
        'completed_downloads': sum(1 for d in downloads.values() if d['status'] == 'completed'),
        'failed_downloads': sum(1 for d in downloads.values() if d['status'] == 'failed'),
    }
    return jsonify(status)


# ========================================
# Package Installation API
# ========================================

@app.route('/api/packages/status')
def get_packages_status():
    """Get status of all packages and installation progress"""
    missing = get_missing_packages()
    installed = [pkg for pkg in ALL_REQUIREMENTS.keys() if pkg not in missing]
    
    return jsonify({
        'installed': installed,
        'missing': missing,
        'all_installed': len(missing) == 0,
        'installation': _installation_state,
        'mutagen_available': MUTAGEN_AVAILABLE,
    })


@app.route('/api/packages/install', methods=['POST'])
def install_missing_packages():
    """Start background installation of missing packages"""
    global _installation_state
    
    if _installation_state['running']:
        return jsonify({'success': False, 'error': 'Installation already in progress'})
    
    missing = get_missing_packages()
    if not missing:
        return jsonify({'success': True, 'message': 'All packages already installed'})
    
    # Start background installation
    def install_thread():
        global _installation_state, MUTAGEN_AVAILABLE
        
        _installation_state = {
            'running': True,
            'completed': False,
            'packages': {pkg: 'pending' for pkg in missing},
            'current': None,
            'progress': 0,
            'total': len(missing),
            'needs_restart': False,
        }
        
        # Emit initial state
        socketio.emit('package_install_start', _installation_state)
        
        for i, pkg in enumerate(missing):
            _installation_state['current'] = pkg
            _installation_state['progress'] = i
            _installation_state['packages'][pkg] = 'installing'
            
            socketio.emit('package_install_progress', {
                'package': pkg,
                'status': 'installing',
                'progress': i,
                'total': len(missing),
            })
            
            success = install_package_pip(pkg)
            
            if success:
                _installation_state['packages'][pkg] = 'installed'
                socketio.emit('package_install_progress', {
                    'package': pkg,
                    'status': 'installed',
                    'progress': i + 1,
                    'total': len(missing),
                })
            else:
                _installation_state['packages'][pkg] = 'failed'
                socketio.emit('package_install_progress', {
                    'package': pkg,
                    'status': 'failed',
                    'progress': i + 1,
                    'total': len(missing),
                })
        
        _installation_state['running'] = False
        _installation_state['completed'] = True
        _installation_state['current'] = None
        _installation_state['progress'] = len(missing)
        
        # Check if we now have mutagen
        if 'mutagen' in missing and _installation_state['packages'].get('mutagen') == 'installed':
            _installation_state['needs_restart'] = True
        
        # Check remaining missing
        still_missing = get_missing_packages()
        _installation_state['all_installed'] = len(still_missing) == 0
        
        socketio.emit('package_install_complete', {
            'success': len(still_missing) == 0,
            'still_missing': still_missing,
            'needs_restart': _installation_state['needs_restart'],
        })
    
    thread = threading.Thread(target=install_thread, daemon=True)
    thread.start()
    
    return jsonify({'success': True, 'message': f'Installing {len(missing)} packages...'})


@app.route('/api/server/restart', methods=['POST'])
def restart_server():
    """Restart the server (for after package installation)"""
    def do_restart():
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    
    threading.Thread(target=do_restart, daemon=True).start()
    return jsonify({'success': True, 'message': 'Server restarting...'})


@app.route('/api/files')
def list_files():
    """List downloaded files with artist/album info from metadata"""
    files = []
    for root, dirs, filenames in os.walk(DOWNLOADS_DIR):
        for filename in filenames:
            if filename.endswith(('.m4a', '.mp4', '.flac', '.mp3')):
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, DOWNLOADS_DIR)
                
                # Default values from path structure
                path_parts = rel_path.replace('\\', '/').split('/')
                artist = path_parts[0] if len(path_parts) > 0 else ''
                album_folder = path_parts[1] if len(path_parts) > 1 else ''
                album = album_folder.split('_', 1)[1] if '_' in album_folder else album_folder
                
                # Try to read title from metadata
                title = None
                if MUTAGEN_AVAILABLE and filename.endswith('.m4a'):
                    try:
                        audio = MP4(filepath)
                        # ©nam is the title tag
                        if '©nam' in audio:
                            title = audio['©nam'][0]
                        # ©ART is the artist tag
                        if '©ART' in audio:
                            artist = audio['©ART'][0]
                        # ©alb is the album tag
                        if '©alb' in audio:
                            album = audio['©alb'][0]
                    except Exception:
                        pass
                
                files.append({
                    'name': re.sub(r'\.(?:m4a|mp4|flac|mp3)$', '', title or filename, flags=re.IGNORECASE),
                    'path': rel_path,
                    'size': os.path.getsize(filepath),
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                    'artist': artist,
                    'album': album
                })
    
    # Sort by modified time (newest first)
    files.sort(key=lambda x: x['modified'], reverse=True)
    return jsonify(files)


@app.route('/api/browse-folders', methods=['POST'])
def browse_folders():
    """Browse folders for path selection"""
    data = request.json
    current_path = data.get('path', '')
    
    # Default to common locations if no path provided
    if not current_path:
        current_path = os.path.expanduser('~')
    
    # Normalize the path
    current_path = os.path.normpath(current_path)
    
    # Check if path exists
    if not os.path.exists(current_path):
        # Try parent directory
        current_path = os.path.dirname(current_path)
        if not os.path.exists(current_path):
            current_path = os.path.expanduser('~')
    
    # If it's a file, get parent directory
    if os.path.isfile(current_path):
        current_path = os.path.dirname(current_path)
    
    folders = []
    try:
        # Add parent directory option
        parent = os.path.dirname(current_path)
        if parent != current_path:  # Not at root
            folders.append({'name': '..', 'path': parent, 'isParent': True})
        
        # List directories
        for item in os.listdir(current_path):
            item_path = os.path.join(current_path, item)
            if os.path.isdir(item_path):
                try:
                    # Check if accessible
                    os.listdir(item_path)
                    folders.append({'name': item, 'path': item_path, 'isParent': False})
                except PermissionError:
                    pass  # Skip inaccessible folders
        
        # Sort folders alphabetically (but keep .. at top)
        folders.sort(key=lambda x: (not x.get('isParent', False), x['name'].lower()))
        
    except PermissionError:
        return jsonify({'error': 'Permission denied', 'current': current_path, 'folders': []}), 200
    except Exception as e:
        return jsonify({'error': str(e), 'current': current_path, 'folders': []}), 200
    
    # Get drive list for Windows
    drives = []
    if os.name == 'nt':
        import ctypes
        # Use GetLogicalDrives which returns a bitmask of available drives
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                letter = chr(ord('A') + i)
                drive = f"{letter}:\\"
                drives.append({'name': f"{letter}:", 'path': drive})
    
    return jsonify({
        'current': current_path,
        'folders': folders,
        'drives': drives
    })


@app.route('/api/select-folder', methods=['POST'])
def select_folder_dialog():
    """Open native Windows folder picker dialog"""
    data = request.json
    initial_path = data.get('path', '')
    
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # Create hidden root window
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)  # Bring dialog to front
        
        # Open folder picker
        folder = filedialog.askdirectory(
            initialdir=initial_path if initial_path and os.path.exists(initial_path) else os.path.expanduser('~'),
            title='Select Download Folder'
        )
        
        root.destroy()
        
        if folder:
            return jsonify({'success': True, 'path': folder})
        else:
            return jsonify({'success': False, 'cancelled': True})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/open-in-explorer', methods=['POST'])
def open_in_explorer():
    """Open file location in Windows Explorer"""
    data = request.json
    file_path = data.get('path', '')
    
    if not file_path:
        return jsonify({'error': 'No path provided'}), 400
    
    # Build full path
    full_path = os.path.join(DOWNLOADS_DIR, file_path)
    full_path = os.path.normpath(full_path)
    
    # Security check - make sure path is within downloads directory
    if not full_path.startswith(os.path.normpath(DOWNLOADS_DIR)):
        return jsonify({'error': 'Invalid path'}), 400
    
    if not os.path.exists(full_path):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Open Explorer and select the file
        run_subprocess(['explorer', '/select,', full_path], check=False)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/embed-artwork', methods=['POST'])
def embed_artwork_bulk():
    """Embed artwork for all files missing artwork"""
    try:
        fixed_count = 0
        skipped_count = 0
        failed_count = 0
        
        for root, dirs, files in os.walk(DOWNLOADS_DIR):
            for f in files:
                if f.endswith('.m4a'):
                    filepath = os.path.join(root, f)
                    try:
                        # Check if file has artwork
                        audio = MP4(filepath)
                        if 'covr' in audio and audio['covr']:
                            skipped_count += 1
                            continue
                        
                        # Try to embed artwork
                        if embed_artwork_for_file(filepath):
                            fixed_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        logger.error(f"Error processing {f}: {e}")
                        failed_count += 1
        
        return jsonify({
            'success': True,
            'fixed': fixed_count,
            'skipped': skipped_count,
            'failed': failed_count,
            'total': fixed_count + skipped_count + failed_count
        })
    except Exception as e:
        logger.error(f"Error in bulk artwork embedding: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/artwork/<path:file_path>')
def get_artwork(file_path):
    """Extract and serve artwork from an audio file"""
    if not MUTAGEN_AVAILABLE:
        return jsonify({'error': 'mutagen not installed'}), 500
    
    # Build full path
    full_path = os.path.join(DOWNLOADS_DIR, file_path)
    full_path = os.path.normpath(full_path)
    
    # Security check - make sure path is within downloads directory
    if not full_path.startswith(os.path.normpath(DOWNLOADS_DIR)):
        return jsonify({'error': 'Invalid path'}), 400
    
    if not os.path.exists(full_path):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        artwork_data = None
        mime_type = 'image/jpeg'  # Default
        
        if full_path.endswith('.m4a') or full_path.endswith('.mp4'):
            audio = MP4(full_path)
            if 'covr' in audio:
                artwork_data = bytes(audio['covr'][0])
                # Check format from MP4Cover type
                cover = audio['covr'][0]
                if hasattr(cover, 'imageformat'):
                    if cover.imageformat == 13:  # JPEG
                        mime_type = 'image/jpeg'
                    elif cover.imageformat == 14:  # PNG
                        mime_type = 'image/png'
        
        elif full_path.endswith('.flac'):
            audio = FLAC(full_path)
            if audio.pictures:
                artwork_data = audio.pictures[0].data
                mime_type = audio.pictures[0].mime or 'image/jpeg'
        
        elif full_path.endswith('.mp3'):
            audio = ID3(full_path)
            for key in audio.keys():
                if key.startswith('APIC'):
                    artwork_data = audio[key].data
                    mime_type = audio[key].mime or 'image/jpeg'
                    break
        
        if artwork_data:
            return Response(artwork_data, mimetype=mime_type)
        else:
            return jsonify({'error': 'No artwork found'}), 404
            
    except Exception as e:
        logger.error(f"Error extracting artwork from {file_path}: {e}")
        return jsonify({'error': str(e)}), 500


# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    emit('connected', {'status': 'connected'})


@socketio.on('subscribe')
def handle_subscribe(data):
    """Subscribe to download updates"""
    download_id = data.get('download_id')
    if download_id and download_id in downloads:
        emit('download_update', downloads[download_id])


@app.route('/api/test-download')
def test_download():
    """Test download with a sample link - use this to verify Docker is working"""
    test_url = "https://music.apple.com/us/album/baostep-feat-bao-the-whale-single/1859215153"
    
    # Get download command - but bypass select mode for testing
    config = load_config()
    use_docker = config.get('use-docker', True)
    
    if use_docker:
        # Build command without --select for automatic download
        downloads_vol = DOWNLOADS_DIR.replace('\\', '/')
        config_vol = CONFIG_FILE.replace('\\', '/')
        
        cmd = [
            'docker', 'run', '--rm', '--network', 'host',
            '-v', f'{downloads_vol}:/downloads',
            '-v', f'{config_vol}:/app/config.yaml',
            'ghcr.io/zhaarey/apple-music-downloader',
            '--debug',  # Show quality info
            test_url
        ]
        cmd_str = ' '.join(cmd)
    else:
        return jsonify({'error': 'Test only works in Docker mode'}), 400
    
    try:
        # Run the command and capture output
        result = run_subprocess(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
            cwd=BASE_DIR
        )
        
        # Check downloads folder for new files
        downloaded_files = []
        for root, dirs, files in os.walk(DOWNLOADS_DIR):
            for f in files:
                filepath = os.path.join(root, f)
                rel_path = os.path.relpath(filepath, DOWNLOADS_DIR)
                downloaded_files.append({
                    'path': rel_path,
                    'size': os.path.getsize(filepath)
                })
        
        return jsonify({
            'success': result.returncode == 0,
            'command': cmd_str,
            'return_code': result.returncode,
            'output': result.stdout,
            'files': downloaded_files
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Download timed out after 60 seconds',
            'command': cmd_str
        }), 408
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/logs')
def get_logs():
    """Get recent log entries from amd_debug.log"""
    log_file = os.path.join(BASE_DIR, 'amd_debug.log')
    lines = []
    try:
        with open(log_file, 'r') as f:
            # Get last 100 lines
            all_lines = f.readlines()
            lines = all_lines[-100:]
    except FileNotFoundError:
        pass
    return jsonify({'logs': lines})


def restart_wrapper_container():
    """Restart the wrapper container when it becomes unresponsive"""
    global _wrapper_tokens_cache, _wrapper_tokens_cache_time
    try:
        logger.info("Attempting to restart wrapper container...")
        result = run_subprocess(
            ['docker', 'restart', 'amd-wrapper'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=30
        )
        if result.returncode == 0:
            logger.info("Wrapper container restarted successfully")
            # Clear token cache since wrapper restarted
            _wrapper_tokens_cache = None
            _wrapper_tokens_cache_time = 0
            # Wait for container to be ready
            import time
            time.sleep(5)
            return True
        else:
            logger.error(f"Failed to restart wrapper: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error restarting wrapper container: {e}")
        return False


# Cache for wrapper tokens to reduce API calls to port 30020
_wrapper_tokens_cache = None
_wrapper_tokens_cache_time = 0
WRAPPER_TOKENS_CACHE_TTL = 300  # 5 minutes - tokens don't change often


def get_wrapper_tokens(retry_on_timeout=True, force_refresh=False):
    """Get authentication tokens from the wrapper service with caching"""
    global _wrapper_tokens_cache, _wrapper_tokens_cache_time
    
    # Return cached tokens if still valid and not forcing refresh
    if not force_refresh and _wrapper_tokens_cache and (time.time() - _wrapper_tokens_cache_time) < WRAPPER_TOKENS_CACHE_TTL:
        return _wrapper_tokens_cache
    
    try:
        response = requests.get('http://127.0.0.1:30020/', timeout=5)
        if response.status_code == 200:
            _wrapper_tokens_cache = response.json()
            _wrapper_tokens_cache_time = time.time()
            return _wrapper_tokens_cache
    except requests.exceptions.Timeout:
        logger.error("Wrapper token request timed out")
        if retry_on_timeout:
            logger.info("Wrapper appears stuck, attempting automatic restart...")
            if restart_wrapper_container():
                # Try once more after restart
                return get_wrapper_tokens(retry_on_timeout=False)
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Wrapper connection error: {e}")
        if retry_on_timeout:
            logger.info("Wrapper connection failed, attempting automatic restart...")
            if restart_wrapper_container():
                # Try once more after restart
                return get_wrapper_tokens(retry_on_timeout=False)
    except Exception as e:
        logger.error(f"Failed to get wrapper tokens: {e}")
        if retry_on_timeout and "RemoteDisconnected" in str(e):
            logger.info("Wrapper disconnected, attempting automatic restart...")
            if restart_wrapper_container():
                # Try once more after restart
                return get_wrapper_tokens(retry_on_timeout=False)
    return None


# Cache for library playlists to reduce Apple Music API calls
_library_playlists_cache = None
_library_playlists_cache_time = 0
LIBRARY_PLAYLISTS_CACHE_TTL = 300  # 5 minutes

_recently_played_cache = None
_recently_played_cache_time = 0
RECENTLY_PLAYED_CACHE_TTL = 300


@app.route('/api/library/recently-played')
def get_recently_played():
    """Fetch the user's cross-device Recently Played album shelf."""
    global _recently_played_cache, _recently_played_cache_time

    force_refresh = request.args.get('refresh') == '1'
    if (not force_refresh and _recently_played_cache is not None and
            (time.time() - _recently_played_cache_time) < RECENTLY_PLAYED_CACHE_TTL):
        return jsonify({'success': True, 'tracks': _recently_played_cache, 'cached': True})

    config = load_config()
    dev_token = (config.get('authorization-token') or '').strip()
    music_token = (config.get('media-user-token') or '').strip()

    if not dev_token:
        dev_token = get_apple_music_token()

    if not music_token:
        tokens = get_wrapper_tokens(retry_on_timeout=False)
        if tokens:
            dev_token = dev_token or tokens.get('dev_token')
            music_token = tokens.get('music_token')

    if not dev_token or not music_token:
        return jsonify({
            'success': False,
            'error': 'Sign in to Apple Music in Settings to view recently played tracks.'
        }), 401

    try:
        response = requests.get(
            'https://amp-api.music.apple.com/v1/me/recent/played',
            headers={
                'Authorization': f'Bearer {dev_token}',
                'Media-User-Token': music_token,
                'Cache-Control': 'no-cache' if force_refresh else 'max-age=60',
                'Pragma': 'no-cache' if force_refresh else '',
                'Origin': 'https://music.apple.com',
                'Referer': 'https://music.apple.com/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            params={'limit': 10, 'types': 'albums'},
            timeout=15
        )

        if response.status_code in (401, 403):
            return jsonify({'success': False, 'error': 'Apple Music authentication expired.'}), 401
        if response.status_code != 200:
            return jsonify({'success': False, 'error': f'Apple Music API error: {response.status_code}'}), 502

        tracks = []
        for item in response.json().get('data', []):
            attrs = item.get('attributes', {})
            artwork = attrs.get('artwork') or {}
            artwork_url = artwork.get('url')
            if artwork_url:
                artwork_url = artwork_url.replace('{w}', '320').replace('{h}', '320')

            album_id = item.get('id')
            tracks.append({
                'id': album_id,
                'albumId': album_id,
                'name': attrs.get('name', 'Unknown'),
                'artistName': attrs.get('artistName', 'Unknown Artist'),
                'albumName': attrs.get('name', 'Unknown'),
                'artwork': artwork_url,
                'url': attrs.get('url', ''),
                'resourceType': 'album'
            })

        _recently_played_cache = tracks
        _recently_played_cache_time = time.time()
        return jsonify({'success': True, 'tracks': tracks})
    except requests.Timeout:
        return jsonify({'success': False, 'error': 'Apple Music request timed out.'}), 504
    except Exception as e:
        logger.error(f"Failed to fetch recently played tracks: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/library/playlists')
def get_library_playlists():
    """Fetch user's Apple Music library playlists (with caching)"""
    global _library_playlists_cache, _library_playlists_cache_time
    
    # Check cache first
    if _library_playlists_cache and (time.time() - _library_playlists_cache_time) < LIBRARY_PLAYLISTS_CACHE_TTL:
        return jsonify({'success': True, 'playlists': _library_playlists_cache, 'cached': True})
    
    tokens = get_wrapper_tokens()
    
    if not tokens:
        return jsonify({'success': False, 'error': 'Not authenticated. Please ensure the wrapper is running.'}), 401
    
    dev_token = tokens.get('dev_token')
    music_token = tokens.get('music_token')
    storefront = tokens.get('storefront_id', '').split(',')[0]  # e.g., "143441-1,31" -> "143441"
    
    if not dev_token or not music_token:
        return jsonify({'success': False, 'error': 'Missing authentication tokens'}), 401
    
    try:
        headers = {
            'Authorization': f'Bearer {dev_token}',
            'Media-User-Token': music_token,
            'Origin': 'https://music.apple.com',
            'Referer': 'https://music.apple.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Fetch library playlists
        response = requests.get(
            'https://amp-api.music.apple.com/v1/me/library/playlists',
            headers=headers,
            params={'limit': 100},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            playlists = []
            
            for item in data.get('data', []):
                attrs = item.get('attributes', {})
                artwork = attrs.get('artwork', {})
                artwork_url = None
                if artwork and artwork.get('url'):
                    artwork_url = artwork['url'].replace('{w}', '200').replace('{h}', '200')
                
                playlists.append({
                    'id': item.get('id'),
                    'name': attrs.get('name', 'Unknown'),
                    'description': attrs.get('description', {}).get('standard', ''),
                    'trackCount': attrs.get('trackCount', 0),
                    'artwork': artwork_url,
                    'canEdit': attrs.get('canEdit', False),
                    'isPublic': attrs.get('isPublic', False),
                    'url': f"https://music.apple.com/library/playlist/{item.get('id')}"
                })
            
            # Cache the results
            _library_playlists_cache = playlists
            _library_playlists_cache_time = time.time()
            
            return jsonify({'success': True, 'playlists': playlists})
        
        elif response.status_code == 401:
            return jsonify({'success': False, 'error': 'Authentication expired. Please restart the wrapper.'}), 401
        else:
            return jsonify({'success': False, 'error': f'API error: {response.status_code}'}), response.status_code
            
    except requests.Timeout:
        return jsonify({'success': False, 'error': 'Request timed out'}), 504
    except Exception as e:
        logger.error(f"Failed to fetch library playlists: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# Cache for playlist tracks to reduce Apple Music API calls
_playlist_tracks_cache = {}  # Dict of playlist_id -> (tracks, timestamp)
PLAYLIST_TRACKS_CACHE_TTL = 300  # 5 minutes


@app.route('/api/library/playlists/<playlist_id>/tracks')
def get_library_playlist_tracks(playlist_id):
    """Fetch tracks from a library playlist (with caching)"""
    global _playlist_tracks_cache
    
    # Check cache first
    if playlist_id in _playlist_tracks_cache:
        cached_data, cache_time = _playlist_tracks_cache[playlist_id]
        if (time.time() - cache_time) < PLAYLIST_TRACKS_CACHE_TTL:
            return jsonify({
                'success': True, 
                'tracks': cached_data['tracks'], 
                'trackCount': cached_data['trackCount'],
                'cached': True
            })
    
    tokens = get_wrapper_tokens()
    
    if not tokens:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    dev_token = tokens.get('dev_token')
    music_token = tokens.get('music_token')
    
    if not dev_token or not music_token:
        return jsonify({'success': False, 'error': 'Missing authentication tokens'}), 401
    
    try:
        headers = {
            'Authorization': f'Bearer {dev_token}',
            'Media-User-Token': music_token,
            'Origin': 'https://music.apple.com',
            'Referer': 'https://music.apple.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Fetch playlist with tracks - include catalog relationship for artwork
        response = requests.get(
            f'https://amp-api.music.apple.com/v1/me/library/playlists/{playlist_id}/tracks',
            headers=headers,
            params={
                'limit': 100, 
                'include[library-songs]': 'catalog',
                'fields[catalog]': 'artwork,name,artistName,albumName',
                'extend': 'artwork'
            },
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            tracks = []
            
            for idx, item in enumerate(data.get('data', []), 1):
                attrs = item.get('attributes', {})
                
                # Get catalog ID first from playParams
                catalog_id = None
                catalog_type = None
                play_params = attrs.get('playParams', {})
                if play_params and play_params.get('catalogId'):
                    catalog_id = play_params.get('catalogId')
                    catalog_type = play_params.get('kind')
                
                # Check catalog relationship for ID and artwork
                artwork_url = None
                if 'relationships' in item:
                    catalog_rel = item.get('relationships', {}).get('catalog', {}).get('data', [])
                    if catalog_rel:
                        catalog_data = catalog_rel[0]
                        catalog_type = catalog_data.get('type') or catalog_type
                        if not catalog_id:
                            catalog_id = catalog_data.get('id')
                        # Get artwork from catalog
                        cat_attrs = catalog_data.get('attributes', {})
                        cat_artwork = cat_attrs.get('artwork', {})
                        if cat_artwork and cat_artwork.get('url'):
                            artwork_url = cat_artwork['url'].replace('{w}', '100').replace('{h}', '100')
                
                # Fallback: try library item artwork if no catalog artwork
                if not artwork_url:
                    artwork = attrs.get('artwork', {})
                    if artwork and artwork.get('url'):
                        artwork_url = artwork['url'].replace('{w}', '100').replace('{h}', '100')
                
                # Get duration in mm:ss format
                duration_ms = attrs.get('durationInMillis', 0)
                duration_s = duration_ms // 1000
                duration_str = f"{duration_s // 60}:{duration_s % 60:02d}"
                
                tracks.append({
                    'id': item.get('id'),
                    'catalogId': catalog_id,
                    'catalogType': catalog_type,
                    'trackNumber': idx,
                    'name': attrs.get('name', 'Unknown'),
                    'artistName': attrs.get('artistName', 'Unknown Artist'),
                    'albumName': attrs.get('albumName', ''),
                    'duration': duration_str,
                    'artwork': artwork_url
                })
            
            # Cache the results
            _playlist_tracks_cache[playlist_id] = ({'tracks': tracks, 'trackCount': len(tracks)}, time.time())
            
            return jsonify({'success': True, 'tracks': tracks, 'trackCount': len(tracks)})
        
        elif response.status_code == 401:
            return jsonify({'success': False, 'error': 'Authentication expired'}), 401
        else:
            return jsonify({'success': False, 'error': f'API error: {response.status_code}'}), response.status_code
            
    except requests.Timeout:
        return jsonify({'success': False, 'error': 'Request timed out'}), 504
    except Exception as e:
        logger.error(f"Failed to fetch playlist tracks: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def check_docker_status():
    """Check if Docker is running and accessible"""
    try:
        result = run_subprocess(
            ['docker', 'info'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


@app.route('/api/docker-status')
def get_docker_status():
    """Check Docker status"""
    docker_running = check_docker_status()
    
    wrapper_running = False
    if docker_running:
        try:
            result = run_subprocess(
                ['docker', 'ps', '--filter', 'name=amd-wrapper', '--format', '{{.Status}}'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            wrapper_running = bool(result.stdout.strip())
        except Exception:
            pass
    
    return jsonify({
        'docker_running': docker_running,
        'wrapper_running': wrapper_running
    })


@app.route('/api/docker-restart', methods=['POST'])
def restart_docker():
    """Attempt to restart Docker Desktop (Windows)"""
    import platform
    
    if platform.system() != 'Windows':
        return jsonify({'success': False, 'error': 'Docker restart is only supported on Windows'}), 400
    
    try:
        # Start Docker Desktop
        popen_subprocess(
            ['C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        return jsonify({
            'success': True,
            'message': 'Docker Desktop is starting. Please wait up to 60 seconds for it to be ready.'
        })
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Docker Desktop not found at default location'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/wrapper-status')
def get_wrapper_status():
    """Check if the wrapper decryption service is running"""
    import socket
    
    docker_running = check_docker_status()
    
    ports = {
        'decrypt': 10020,
        'm3u8': 20020,
        'account': 30020
    }
    
    status = {
        'running': False,
        'docker_running': docker_running,
        'ports': {},
        'docker_status': None
    }
    
    # Check if ports are listening
    for name, port in ports.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            status['ports'][name] = result == 0
            sock.close()
        except Exception:
            status['ports'][name] = False
    
    # If decrypt port is open, wrapper is likely running
    status['running'] = status['ports'].get('decrypt', False)
    
    # Try to get Docker container status
    try:
        result = run_subprocess(
            ['docker', 'ps', '--filter', 'name=amd-wrapper', '--format', '{{.Status}}'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5
        )
        if result.stdout.strip():
            status['docker_status'] = result.stdout.strip()
    except Exception:
        pass
    
    return jsonify(status)


@app.route('/api/wrapper-start', methods=['POST'])
def start_wrapper():
    """Attempt to start the wrapper Docker container"""
    wrapper_data = os.path.join(BASE_DIR, 'wrapper-data')
    
    # Create wrapper-data directory if needed
    os.makedirs(wrapper_data, exist_ok=True)
    
    try:
        # Stop any existing container
        run_subprocess(['docker', 'rm', '-f', 'amd-wrapper'], 
                      capture_output=True, timeout=10)
        
        # Start new container (use local built image)
        result = run_subprocess([
            'docker', 'run', '-d',
            '--name', 'amd-wrapper',
            '--restart', 'no',
            '-v', f'{wrapper_data}:/app/rootfs/data',
            '-p', '10020:10020',
            '-p', '20020:20020', 
            '-p', '30020:30020',
            '-e', 'args=-H 0.0.0.0',
            'amd-wrapper-local'
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Wrapper started successfully',
                'container_id': result.stdout.strip()[:12]
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr or 'Failed to start wrapper. Have you built it with option 6 in start-wrapper.bat?'
            }), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Setup wizard state (in-memory, for current session)
setup_session = {
    'process': None,
    'state': 'idle',  # idle, waiting_2fa, success, error
    'message': '',
    'token_hash': None
}


def get_wrapper_media_token_path():
    return os.path.join(
        BASE_DIR, 'wrapper-data', 'data', 'com.apple.android.music', 'files', 'MUSIC_TOKEN'
    )


def get_wrapper_media_token_hash():
    token_path = get_wrapper_media_token_path()
    if not os.path.isfile(token_path):
        return None
    try:
        with open(token_path, 'rb') as token_file:
            return hashlib.sha256(token_file.read().strip()).hexdigest()
    except OSError:
        return None


def save_wrapper_media_token(previous_hash=None):
    """Copy the media token generated by wrapper login into app configuration."""
    token_path = get_wrapper_media_token_path()
    if not os.path.isfile(token_path):
        return False

    try:
        with open(token_path, 'rb') as token_file:
            token_bytes = token_file.read().strip()
        if previous_hash and hashlib.sha256(token_bytes).hexdigest() == previous_hash:
            return False
        music_token = token_bytes.decode('utf-8')
        if len(music_token) < 50:
            return False

        config = load_config()
        config['media-user-token'] = music_token
        save_config(config)
        return True
    except Exception as e:
        logger.error(f"Failed to save wrapper media token: {e}")
        return False


def stop_wrapper_login_process(process):
    if not process:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def finish_wrapper_login(process):
    """Save the login token and stop the temporary wrapper process."""
    token_saved = save_wrapper_media_token(setup_session.get('token_hash'))
    setup_session['state'] = 'success' if token_saved else 'error'
    setup_session['message'] = (
        'Media token saved successfully.' if token_saved
        else 'Login succeeded, but no media token was generated.'
    )

    stop_wrapper_login_process(process)
    setup_session['process'] = None
    return token_saved

@app.route('/api/wrapper-setup/check')
def check_wrapper_setup():
    """Check if wrapper is set up (has auth tokens)"""
    wrapper_data = os.path.join(BASE_DIR, 'wrapper-data')
    
    # Check for auth token files - the wrapper stores data in nested structure
    # Could be wrapper-data/data/com.apple.android.music/ or wrapper-data/device.bin
    has_tokens = False
    
    # Check various possible locations for auth data
    possible_paths = [
        os.path.join(wrapper_data, 'data', 'com.apple.android.music'),
        os.path.join(wrapper_data, 'device.bin'),
        os.path.join(wrapper_data, 'data'),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            # If it's a directory, check if it has files
            if os.path.isdir(path):
                if os.listdir(path):
                    has_tokens = True
                    break
            else:
                has_tokens = True
                break
    
    has_wrapper_image = False
    
    # Check if Docker image exists
    try:
        result = run_subprocess(
            ['docker', 'images', '-q', 'amd-wrapper-local'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5
        )
        has_wrapper_image = bool(result.stdout.strip())
    except Exception:
        pass
    
    return jsonify({
        'has_tokens': has_tokens,
        'has_wrapper_image': has_wrapper_image,
        'needs_setup': not has_tokens or not has_wrapper_image
    })


@app.route('/api/wrapper-setup/login', methods=['POST'])
def wrapper_setup_login():
    """Start the wrapper login process"""
    import threading
    
    data = request.json
    email = data.get('email', '')
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400
    
    wrapper_data = os.path.join(BASE_DIR, 'wrapper-data')
    os.makedirs(wrapper_data, exist_ok=True)
    
    # Check if Docker image exists
    try:
        result = run_subprocess(
            ['docker', 'images', '-q', 'amd-wrapper-local'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5
        )
        if not result.stdout.strip():
            return jsonify({
                'success': False, 
                'error': 'Docker image not found. Please run start-wrapper.bat and choose option 6 to build first.'
            }), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f'Docker check failed: {e}'}), 500

    # Avoid two authenticated wrapper sessions sharing the same account data.
    run_subprocess(['docker', 'stop', 'amd-wrapper'], capture_output=True, timeout=10)
    
    # Start the login process
    setup_session['state'] = 'logging_in'
    setup_session['message'] = ''
    setup_session['token_hash'] = get_wrapper_media_token_hash()
    
    def run_login():
        process = None
        credentials_dir = None
        try:
            credentials_dir = tempfile.mkdtemp(prefix='amd-login-')
            credentials_path = os.path.join(credentials_dir, 'apple_credentials')
            with open(credentials_path, 'w', encoding='utf-8', newline='') as credentials_file:
                credentials_file.write(f'{email}:{password}')

            # Keep credentials out of Docker and OS process metadata. The wrapper
            # reads them from a short-lived, read-only bind-mounted file instead.
            cmd = [
                'docker', 'run', '-i', '--rm',
                '-v', f'{wrapper_data}:/app/rootfs/data',
                '-v', f'{credentials_path}:/run/secrets/apple_credentials:ro',
                'amd-wrapper-local',
                'bash', '-c',
                '/app/wrapper -L "$(cat /run/secrets/apple_credentials)" -H 0.0.0.0'
            ]
            
            process = popen_subprocess(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1
            )
            
            setup_session['process'] = process
            output_lines = []
            
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                output_lines.append(line)
                logger.info(f"Wrapper login output: {line}")
                
                # Check for 2FA prompt
                if '2FA: true' in line or '2fa code:' in line.lower():
                    setup_session['state'] = 'waiting_2fa'
                    setup_session['message'] = 'Enter the 2FA code sent to your device'
                    continue
                
                # Check for success
                if 'account info cached successfully' in line.lower():
                    finish_wrapper_login(process)
                    break
                
                # Check for failure
                if 'login failed' in line.lower():
                    setup_session['state'] = 'error'
                    setup_session['message'] = 'Login failed. Check your credentials and try again.'
                    break
                    
                if 'Check the account information' in line:
                    setup_session['state'] = 'error'
                    setup_session['message'] = 'Invalid credentials. Please check your email and password.'
                    break
            
            if setup_session['state'] in ('logging_in', 'waiting_2fa', 'verifying'):
                setup_session['state'] = 'error'
                setup_session['message'] = 'Login process ended unexpectedly'
                
        except Exception as e:
            setup_session['state'] = 'error'
            setup_session['message'] = str(e)
        finally:
            if setup_session['state'] not in ('waiting_2fa', 'success'):
                stop_wrapper_login_process(process)
                setup_session['process'] = None
            if credentials_dir:
                shutil.rmtree(credentials_dir, ignore_errors=True)
    
    thread = threading.Thread(target=run_login, daemon=True)
    thread.start()
    
    # Wait a bit for initial response
    import time
    time.sleep(3)
    
    return jsonify({
        'success': True,
        'state': setup_session['state'],
        'message': setup_session['message']
    })


@app.route('/api/wrapper-setup/2fa', methods=['POST'])
def wrapper_setup_2fa():
    """Submit 2FA code"""
    data = request.json
    code = data.get('code', '')
    
    if not code or len(code) != 6:
        return jsonify({'success': False, 'error': 'Invalid 2FA code'}), 400
    
    if setup_session['state'] != 'waiting_2fa':
        return jsonify({'success': False, 'error': 'Not waiting for 2FA'}), 400
    
    process = setup_session.get('process')
    if not process:
        return jsonify({'success': False, 'error': 'No active login process'}), 400
    
    try:
        # Send 2FA code to the process
        process.stdin.write(code + '\n')
        process.stdin.flush()
        setup_session['state'] = 'verifying'
        setup_session['message'] = 'Verifying code...'
        
        # The background login thread continues reading process output.
        import time
        timeout = 30
        start = time.time()
        
        while time.time() - start < timeout:
            if setup_session['state'] in ('success', 'error'):
                break
            time.sleep(0.5)
        
        if setup_session['state'] == 'success':
            return jsonify({
                'success': True,
                'state': 'success',
                'message': setup_session['message']
            })
        else:
            if setup_session['state'] == 'verifying':
                setup_session['state'] = 'error'
                setup_session['message'] = 'Verification timed out.'
            stop_wrapper_login_process(process)
            setup_session['process'] = None
            return jsonify({
                'success': False, 
                'error': setup_session.get('message', 'Verification failed')
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/wrapper-setup/status')
def wrapper_setup_status():
    """Get current setup status"""
    return jsonify({
        'state': setup_session['state'],
        'message': setup_session['message']
    })


@app.route('/api/wrapper-setup/start-service', methods=['POST'])
def wrapper_start_service():
    """Start the wrapper service after successful login"""
    wrapper_data = os.path.join(BASE_DIR, 'wrapper-data')
    
    try:
        # Stop any existing container
        run_subprocess(['docker', 'rm', '-f', 'amd-wrapper'], 
                      capture_output=True, timeout=10)
        
        # Start wrapper service
        result = run_subprocess([
            'docker', 'run', '-d',
            '--name', 'amd-wrapper',
            '--restart', 'no',
            '-v', f'{wrapper_data}:/app/rootfs/data',
            '-p', '10020:10020',
            '-p', '20020:20020',
            '-p', '30020:30020',
            '-e', 'args=-H 0.0.0.0',
            'amd-wrapper-local'
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        
        if result.returncode == 0:
            return jsonify({'success': True, 'message': 'Wrapper service started'})
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/auth/status')
def get_auth_status():
    """Check authentication status - whether wrapper is signed in or token in config"""
    # First check config for media-user-token (works without wrapper)
    config = load_config()
    media_token = config.get('media-user-token', '')
    
    # If we have a media token in config, consider authenticated for most features
    if media_token and len(media_token) > 50:
        return jsonify({
            'authenticated': True,
            'has_media_token': True,
            'music_token': media_token,
            'source': 'config'
        })
    
    # Otherwise check wrapper tokens
    tokens = get_wrapper_tokens(retry_on_timeout=False)
    
    if tokens and tokens.get('music_token'):
        return jsonify({
            'authenticated': True,
            'has_media_token': True,
            'music_token': tokens.get('music_token'),
            'source': 'wrapper'
        })
    else:
        return jsonify({
            'authenticated': False,
            'has_media_token': bool(media_token),
            'music_token': None
        })


@app.route('/api/auth/sync-token', methods=['POST'])
def sync_media_token():
    """Sync the media user token from wrapper to config"""
    tokens = get_wrapper_tokens(retry_on_timeout=False)
    
    if not tokens or not tokens.get('music_token'):
        return jsonify({'success': False, 'error': 'Not authenticated with wrapper'}), 401
    
    music_token = tokens.get('music_token')
    
    # Update the config with the media user token
    config = load_config()
    config['media-user-token'] = music_token
    
    try:
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        
        return jsonify({
            'success': True,
            'message': 'Media user token synced to config',
            'token_preview': music_token[:20] + '...' if len(music_token) > 20 else music_token
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def initialize_auto_download():
    """Initialize auto-download scheduler on startup"""
    config = load_config()
    auto_config = config.get('auto-download', {})
    if auto_config.get('enabled', False):
        update_auto_download_scheduler(auto_config)
        logger.info("Auto-download scheduler initialized")


def startup_docker_and_wrapper():
    """Start Docker Desktop while leaving the playback wrapper demand-driven."""
    import platform
    
    print("\n[Startup] Checking Docker status...")
    
    # Check if Docker is already running
    docker_running = check_docker_status()
    
    if not docker_running:
        print("[Startup] Docker is not running. Attempting to start Docker Desktop...")
        
        if platform.system() == 'Windows':
            try:
                # Try common Docker Desktop paths
                docker_paths = [
                    'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe',
                    os.path.expandvars('%PROGRAMFILES%\\Docker\\Docker\\Docker Desktop.exe'),
                    os.path.expandvars('%LOCALAPPDATA%\\Docker\\Docker Desktop.exe')
                ]
                
                docker_started = False
                for docker_path in docker_paths:
                    if os.path.exists(docker_path):
                        popen_subprocess(
                            [docker_path],
                            shell=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        print(f"[Startup] Started Docker Desktop from: {docker_path}")
                        docker_started = True
                        break
                
                if not docker_started:
                    print("[Startup] WARNING: Could not find Docker Desktop executable")
                    return False
                
                # Wait for Docker to be ready (up to 60 seconds)
                print("[Startup] Waiting for Docker to be ready (this may take up to 60 seconds)...")
                for i in range(60):
                    time.sleep(1)
                    if check_docker_status():
                        print(f"[Startup] Docker is ready after {i+1} seconds")
                        docker_running = True
                        break
                    if i % 10 == 9:
                        print(f"[Startup] Still waiting for Docker... ({i+1}s)")
                
                if not docker_running:
                    print("[Startup] WARNING: Docker did not become ready within 60 seconds")
                    return False
                    
            except Exception as e:
                print(f"[Startup] ERROR starting Docker: {e}")
                return False
        else:
            print("[Startup] WARNING: Auto-start Docker is only supported on Windows")
            return False
    else:
        print("[Startup] Docker is already running")
    
    print("[Startup] Wrapper remains stopped until a download or explicit start needs it")
    return True


# ========================================
# Data Storage Helpers
# ========================================

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

def load_json_data(filename):
    """Load data from a JSON file in the data directory"""
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
    return None

def save_json_data(filename, data):
    """Save data to a JSON file in the data directory"""
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving {filename}: {e}")
        return False


# ========================================
# Download History API
# ========================================

@app.route('/api/history', methods=['GET'])
def get_download_history():
    """Get download history and stats"""
    history = load_json_data('history.json')
    if not history:
        history = {
            "downloads": [],
            "stats": {
                "total_downloads": 0,
                "total_size_bytes": 0,
                "downloads_by_type": {"albums": 0, "songs": 0, "playlists": 0},
                "first_download": None,
                "last_download": None
            }
        }
    return jsonify(history)

@app.route('/api/history/add', methods=['POST'])
def add_to_history():
    """Add a download to history"""
    data = request.json
    history = load_json_data('history.json') or {
        "downloads": [],
        "stats": {
            "total_downloads": 0,
            "total_size_bytes": 0,
            "downloads_by_type": {"albums": 0, "songs": 0, "playlists": 0},
            "first_download": None,
            "last_download": None
        }
    }
    
    entry = {
        "id": str(uuid.uuid4()),
        "url": data.get('url'),
        "title": data.get('title'),
        "artist": data.get('artist'),
        "type": data.get('type', 'song'),
        "size_bytes": data.get('size_bytes', 0),
        "timestamp": datetime.now().isoformat(),
        "artwork": data.get('artwork')
    }
    
    history['downloads'].insert(0, entry)
    # Keep only last 500 entries
    history['downloads'] = history['downloads'][:500]
    
    # Update stats
    history['stats']['total_downloads'] += 1
    history['stats']['total_size_bytes'] += entry['size_bytes']
    history['stats']['last_download'] = entry['timestamp']
    if not history['stats']['first_download']:
        history['stats']['first_download'] = entry['timestamp']
    
    type_key = entry['type'] + 's' if entry['type'] in ['album', 'song', 'playlist'] else 'songs'
    if type_key in history['stats']['downloads_by_type']:
        history['stats']['downloads_by_type'][type_key] += 1
    
    save_json_data('history.json', history)
    return jsonify({"success": True})

@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    """Clear download history"""
    history = {
        "downloads": [],
        "stats": {
            "total_downloads": 0,
            "total_size_bytes": 0,
            "downloads_by_type": {"albums": 0, "songs": 0, "playlists": 0},
            "first_download": None,
            "last_download": None
        }
    }
    save_json_data('history.json', history)
    return jsonify({"success": True})


# ========================================
# Search History API
# ========================================

@app.route('/api/search-history', methods=['GET'])
def get_search_history():
    """Get search history"""
    history = load_json_data('search_history.json') or {"searches": [], "max_history": 50}
    return jsonify(history)

@app.route('/api/search-history/add', methods=['POST'])
def add_to_search_history():
    """Add a search to history"""
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"success": False, "error": "Empty query"})
    
    history = load_json_data('search_history.json') or {"searches": [], "max_history": 50}
    
    # Remove duplicate if exists
    history['searches'] = [s for s in history['searches'] if s.get('query', '').lower() != query.lower()]
    
    # Add new entry at the beginning
    history['searches'].insert(0, {
        "query": query,
        "timestamp": datetime.now().isoformat()
    })
    
    # Keep only max_history entries
    history['searches'] = history['searches'][:history['max_history']]
    
    save_json_data('search_history.json', history)
    return jsonify({"success": True})

@app.route('/api/search-history/clear', methods=['POST'])
def clear_search_history():
    """Clear search history"""
    save_json_data('search_history.json', {"searches": [], "max_history": 50})
    return jsonify({"success": True})


# ========================================
# Favorites API
# ========================================

@app.route('/api/favorites', methods=['GET'])
def get_favorites():
    """Get all favorites"""
    favorites = load_json_data('favorites.json') or {
        "artists": [], "albums": [], "playlists": [], "songs": []
    }
    return jsonify(favorites)

@app.route('/api/favorites/add', methods=['POST'])
def add_to_favorites():
    """Add item to favorites"""
    data = request.json
    item_type = data.get('type')  # artists, albums, playlists, songs
    
    if item_type not in ['artists', 'albums', 'playlists', 'songs']:
        return jsonify({"success": False, "error": "Invalid type"})
    
    favorites = load_json_data('favorites.json') or {
        "artists": [], "albums": [], "playlists": [], "songs": []
    }
    
    item = {
        "id": data.get('id'),
        "name": data.get('name'),
        "artist": data.get('artist'),
        "artwork": data.get('artwork'),
        "url": data.get('url'),
        "added": datetime.now().isoformat()
    }
    
    # Check for duplicates
    existing_ids = [i.get('id') for i in favorites[item_type]]
    if item['id'] not in existing_ids:
        favorites[item_type].insert(0, item)
        save_json_data('favorites.json', favorites)
    
    return jsonify({"success": True})

@app.route('/api/favorites/remove', methods=['POST'])
def remove_from_favorites():
    """Remove item from favorites"""
    data = request.json
    item_type = data.get('type')
    item_id = data.get('id')
    
    if item_type not in ['artists', 'albums', 'playlists', 'songs']:
        return jsonify({"success": False, "error": "Invalid type"})
    
    favorites = load_json_data('favorites.json') or {
        "artists": [], "albums": [], "playlists": [], "songs": []
    }
    
    favorites[item_type] = [i for i in favorites[item_type] if i.get('id') != item_id]
    save_json_data('favorites.json', favorites)
    
    return jsonify({"success": True})

@app.route('/api/favorites/check', methods=['GET'])
def check_favorite():
    """Check if an item is favorited"""
    item_type = request.args.get('type')
    item_id = request.args.get('id')
    
    if item_type not in ['artists', 'albums', 'playlists', 'songs']:
        return jsonify({"favorited": False})
    
    favorites = load_json_data('favorites.json') or {
        "artists": [], "albums": [], "playlists": [], "songs": []
    }
    
    is_favorited = any(i.get('id') == item_id for i in favorites[item_type])
    return jsonify({"favorited": is_favorited})


# ========================================
# Followed Artists & New Releases API
# ========================================

@app.route('/api/followed-artists', methods=['GET'])
def get_followed_artists():
    """Get followed artists"""
    data = load_json_data('followed_artists.json') or {"artists": [], "last_check": None}
    return jsonify(data)

@app.route('/api/followed-artists/add', methods=['POST'])
def add_followed_artist():
    """Add artist to followed list"""
    req_data = request.json
    data = load_json_data('followed_artists.json') or {"artists": [], "last_check": None}
    
    artist = {
        "id": req_data.get('id'),
        "name": req_data.get('name'),
        "artwork": req_data.get('artwork'),
        "last_known_album": req_data.get('last_album'),
        "added": datetime.now().isoformat()
    }
    
    # Check for duplicates
    existing_ids = [a.get('id') for a in data['artists']]
    if artist['id'] not in existing_ids:
        data['artists'].append(artist)
        save_json_data('followed_artists.json', data)
    
    return jsonify({"success": True})

@app.route('/api/followed-artists/remove', methods=['POST'])
def remove_followed_artist():
    """Remove artist from followed list"""
    req_data = request.json
    artist_id = req_data.get('id')
    
    data = load_json_data('followed_artists.json') or {"artists": [], "last_check": None}
    data['artists'] = [a for a in data['artists'] if a.get('id') != artist_id]
    save_json_data('followed_artists.json', data)
    
    return jsonify({"success": True})

@app.route('/api/new-releases', methods=['GET'])
def check_new_releases():
    """Check for new releases from followed artists"""
    data = load_json_data('followed_artists.json') or {"artists": [], "last_check": None}
    new_releases = []
    
    for artist in data['artists']:
        try:
            # Fetch artist's albums from Apple Music API
            token = get_apple_music_token()
            if not token:
                continue
            
            config = load_config()
            storefront = config.get('storefront', 'us')
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Origin': 'https://music.apple.com'
            }
            
            response = requests.get(
                f"https://api.music.apple.com/v1/catalog/{storefront}/artists/{artist['id']}/albums",
                headers=headers,
                params={'limit': 5},
                timeout=10
            )
            
            if response.status_code == 200:
                albums = response.json().get('data', [])
                if albums:
                    latest = albums[0]
                    latest_id = latest.get('id')
                    
                    # Check if this is new
                    if artist.get('last_known_album') != latest_id:
                        new_releases.append({
                            "artist": artist['name'],
                            "artist_id": artist['id'],
                            "album": latest.get('attributes', {}).get('name'),
                            "album_id": latest_id,
                            "artwork": latest.get('attributes', {}).get('artwork', {}).get('url', '').replace('{w}', '300').replace('{h}', '300'),
                            "release_date": latest.get('attributes', {}).get('releaseDate')
                        })
        except Exception as e:
            logger.error(f"Error checking new releases for {artist.get('name')}: {e}")
    
    # Update last check time
    data['last_check'] = datetime.now().isoformat()
    save_json_data('followed_artists.json', data)
    
    return jsonify({"success": True, "new_releases": new_releases})


# ========================================
# Duplicate Detection API
# ========================================

@app.route('/api/check-duplicate', methods=['POST'])
def check_duplicate():
    """Check if a file might already exist in downloads"""
    data = request.json
    title = data.get('title', '').lower()
    artist = data.get('artist', '').lower()
    
    downloads_dir = get_downloads_dir()
    duplicates = []
    
    try:
        for root, dirs, files in os.walk(downloads_dir):
            for file in files:
                if file.endswith(('.m4a', '.flac', '.mp3', '.alac')):
                    file_lower = file.lower()
                    # Check if title appears in filename
                    if title and title in file_lower:
                        duplicates.append({
                            "file": file,
                            "path": os.path.join(root, file),
                            "match_type": "title"
                        })
                    elif artist and artist in file_lower:
                        duplicates.append({
                            "file": file,
                            "path": os.path.join(root, file),
                            "match_type": "artist"
                        })
    except Exception as e:
        logger.error(f"Error checking duplicates: {e}")
    
    return jsonify({
        "has_duplicates": len(duplicates) > 0,
        "duplicates": duplicates[:10]  # Limit to 10 results
    })


# ========================================
# Duplicate File Scanner API
# ========================================

@app.route('/api/scan-duplicates', methods=['GET'])
def scan_duplicates():
    """Scan downloads folder for duplicate files"""
    import hashlib
    
    downloads_dir = get_downloads_dir()
    file_hashes = {}
    duplicates = []
    
    try:
        for root, dirs, files in os.walk(downloads_dir):
            for file in files:
                if file.endswith(('.m4a', '.flac', '.mp3', '.alac')):
                    filepath = os.path.join(root, file)
                    try:
                        # Use file size + first 1KB for quick hash
                        file_size = os.path.getsize(filepath)
                        with open(filepath, 'rb') as f:
                            first_kb = f.read(1024)
                        
                        quick_hash = hashlib.md5(f"{file_size}{first_kb}".encode()).hexdigest()
                        
                        if quick_hash in file_hashes:
                            duplicates.append({
                                "original": file_hashes[quick_hash],
                                "duplicate": filepath,
                                "size": file_size
                            })
                        else:
                            file_hashes[quick_hash] = filepath
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"Error scanning duplicates: {e}")
    
    return jsonify({
        "success": True,
        "duplicates": duplicates,
        "total_files_scanned": len(file_hashes) + len(duplicates)
    })


# ========================================
# Metadata Editor API
# ========================================

@app.route('/api/metadata/<path:filepath>', methods=['GET'])
def get_file_metadata(filepath):
    """Get metadata for an audio file"""
    if not MUTAGEN_AVAILABLE:
        return jsonify({"success": False, "error": "Mutagen not installed"})
    
    downloads_dir = get_downloads_dir()
    full_path = os.path.join(downloads_dir, filepath)
    
    if not os.path.exists(full_path):
        return jsonify({"success": False, "error": "File not found"})
    
    try:
        metadata = {}
        
        if full_path.endswith('.m4a'):
            audio = MP4(full_path)
            metadata = {
                "title": audio.get('\xa9nam', [''])[0],
                "artist": audio.get('\xa9ART', [''])[0],
                "album": audio.get('\xa9alb', [''])[0],
                "album_artist": audio.get('aART', [''])[0],
                "year": audio.get('\xa9day', [''])[0],
                "genre": audio.get('\xa9gen', [''])[0],
                "track_number": str(audio.get('trkn', [(0, 0)])[0][0]),
                "disc_number": str(audio.get('disk', [(0, 0)])[0][0]),
            }
        elif full_path.endswith('.flac'):
            audio = FLAC(full_path)
            metadata = {
                "title": audio.get('title', [''])[0],
                "artist": audio.get('artist', [''])[0],
                "album": audio.get('album', [''])[0],
                "album_artist": audio.get('albumartist', [''])[0],
                "year": audio.get('date', [''])[0],
                "genre": audio.get('genre', [''])[0],
                "track_number": audio.get('tracknumber', [''])[0],
                "disc_number": audio.get('discnumber', [''])[0],
            }
        elif full_path.endswith('.mp3'):
            audio = ID3(full_path)
            metadata = {
                "title": str(audio.get('TIT2', '')),
                "artist": str(audio.get('TPE1', '')),
                "album": str(audio.get('TALB', '')),
                "album_artist": str(audio.get('TPE2', '')),
                "year": str(audio.get('TDRC', '')),
                "genre": str(audio.get('TCON', '')),
                "track_number": str(audio.get('TRCK', '')),
                "disc_number": str(audio.get('TPOS', '')),
            }
        
        return jsonify({"success": True, "metadata": metadata, "filepath": filepath})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/metadata/<path:filepath>', methods=['POST'])
def update_file_metadata(filepath):
    """Update metadata for an audio file"""
    if not MUTAGEN_AVAILABLE:
        return jsonify({"success": False, "error": "Mutagen not installed"})
    
    downloads_dir = get_downloads_dir()
    full_path = os.path.join(downloads_dir, filepath)
    
    if not os.path.exists(full_path):
        return jsonify({"success": False, "error": "File not found"})
    
    data = request.json
    
    try:
        if full_path.endswith('.m4a'):
            audio = MP4(full_path)
            if 'title' in data: audio['\xa9nam'] = [data['title']]
            if 'artist' in data: audio['\xa9ART'] = [data['artist']]
            if 'album' in data: audio['\xa9alb'] = [data['album']]
            if 'album_artist' in data: audio['aART'] = [data['album_artist']]
            if 'year' in data: audio['\xa9day'] = [data['year']]
            if 'genre' in data: audio['\xa9gen'] = [data['genre']]
            audio.save()
        elif full_path.endswith('.flac'):
            audio = FLAC(full_path)
            if 'title' in data: audio['title'] = data['title']
            if 'artist' in data: audio['artist'] = data['artist']
            if 'album' in data: audio['album'] = data['album']
            if 'album_artist' in data: audio['albumartist'] = data['album_artist']
            if 'year' in data: audio['date'] = data['year']
            if 'genre' in data: audio['genre'] = data['genre']
            if 'track_number' in data: audio['tracknumber'] = data['track_number']
            if 'disc_number' in data: audio['discnumber'] = data['disc_number']
            audio.save()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ========================================
# Batch URL Import API
# ========================================

@app.route('/api/batch-download', methods=['POST'])
def batch_download():
    """Queue multiple URLs for download"""
    data = request.json
    urls = data.get('urls', [])
    
    if isinstance(urls, str):
        urls = [u.strip() for u in urls.split('\n') if u.strip()]
    
    queued = []
    errors = []
    duplicates = []
    
    for url in urls:
        try:
            # Validate URL
            if 'music.apple.com' not in url and not url.startswith('http'):
                errors.append({"url": url, "error": "Invalid URL"})
                continue
            
            url_info = parse_apple_music_url(url)
            if not url_info:
                errors.append({"url": url, "error": "Invalid Apple Music URL"})
                continue

            options = {
                'quality': data.get('quality', 'alac'),
                'song': url_info['type'] == 'song'
            }
            download_id = str(uuid.uuid4())
            download_info = {
                'id': download_id,
                'url': url,
                'url_info': url_info,
                'options': options,
                'status': 'queued',
                'progress': None,
                'output': [],
                'message': 'Queued for download',
                'title': url,
                'from_batch': True,
                'created_at': datetime.now().isoformat()
            }

            download_id, was_queued = register_download(download_info)
            if was_queued:
                download_queue.put((download_id, url, options))
                queued.append({"url": url, "id": download_id})
            else:
                duplicates.append({"url": url, "id": download_id})
            
        except Exception as e:
            errors.append({"url": url, "error": str(e)})
    
    return jsonify({
        "success": True,
        "queued": len(queued),
        "duplicates": len(duplicates),
        "errors": len(errors),
        "details": {"queued": queued, "duplicates": duplicates, "errors": errors}
    })


# ========================================
# Blacklist API
# ========================================

@app.route('/api/blacklist', methods=['GET'])
def get_blacklist():
    """Get auto-download blacklist"""
    config = load_config()
    blacklist = config.get('auto-download', {}).get('blacklist', {"artists": [], "albums": []})
    return jsonify(blacklist)

@app.route('/api/blacklist/add', methods=['POST'])
def add_to_blacklist():
    """Add item to blacklist"""
    data = request.json
    item_type = data.get('type')  # 'artists' or 'albums'
    
    if item_type not in ['artists', 'albums']:
        return jsonify({"success": False, "error": "Invalid type"})
    
    config = load_config()
    if 'auto-download' not in config:
        config['auto-download'] = {}
    if 'blacklist' not in config['auto-download']:
        config['auto-download']['blacklist'] = {"artists": [], "albums": []}
    
    item = {
        "id": data.get('id'),
        "name": data.get('name')
    }
    
    # Check for duplicates
    existing_ids = [i.get('id') for i in config['auto-download']['blacklist'][item_type]]
    if item['id'] not in existing_ids:
        config['auto-download']['blacklist'][item_type].append(item)
        save_config(config)
    
    return jsonify({"success": True})

@app.route('/api/blacklist/remove', methods=['POST'])
def remove_from_blacklist():
    """Remove item from blacklist"""
    data = request.json
    item_type = data.get('type')
    item_id = data.get('id')
    
    config = load_config()
    if 'auto-download' in config and 'blacklist' in config['auto-download']:
        config['auto-download']['blacklist'][item_type] = [
            i for i in config['auto-download']['blacklist'].get(item_type, [])
            if i.get('id') != item_id
        ]
        save_config(config)
    
    return jsonify({"success": True})


# ========================================
# Smart Rules API
# ========================================

@app.route('/api/smart-rules', methods=['GET'])
def get_smart_rules():
    """Get smart download rules"""
    config = load_config()
    rules = config.get('auto-download', {}).get('smart-rules', [])
    return jsonify({"rules": rules})

@app.route('/api/smart-rules', methods=['POST'])
def save_smart_rules():
    """Save smart download rules"""
    data = request.json
    rules = data.get('rules', [])
    
    config = load_config()
    if 'auto-download' not in config:
        config['auto-download'] = {}
    config['auto-download']['smart-rules'] = rules
    save_config(config)
    
    return jsonify({"success": True})


# ========================================
# Settings Export/Import API
# ========================================

@app.route('/api/settings/export', methods=['GET'])
def export_settings():
    """Export all settings as JSON"""
    config = load_config()
    favorites = load_json_data('favorites.json')
    followed = load_json_data('followed_artists.json')
    
    export_data = {
        "config": config,
        "favorites": favorites,
        "followed_artists": followed,
        "exported_at": datetime.now().isoformat(),
        "version": "1.0"
    }
    
    return Response(
        json.dumps(export_data, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=amd-settings-backup.json'}
    )

@app.route('/api/settings/import', methods=['POST'])
def import_settings():
    """Import settings from JSON"""
    try:
        data = request.json
        
        if 'config' in data:
            save_config(data['config'])
        
        if 'favorites' in data:
            save_json_data('favorites.json', data['favorites'])
        
        if 'followed_artists' in data:
            save_json_data('followed_artists.json', data['followed_artists'])
        
        return jsonify({"success": True, "message": "Settings imported successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ========================================
# Theme API
# ========================================

@app.route('/api/theme', methods=['GET'])
def get_theme():
    """Get current theme"""
    config = load_config()
    return jsonify({"theme": config.get('theme', 'dark')})

@app.route('/api/theme', methods=['POST'])
def set_theme():
    """Set theme"""
    data = request.json
    theme = data.get('theme', 'dark')
    
    config = load_config()
    config['theme'] = theme
    save_config(config)
    
    return jsonify({"success": True, "theme": theme})


# ========================================
# Scheduling API
# ========================================

scheduled_jobs = {}

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    """Get auto-download schedule"""
    config = load_config()
    schedule_config = {
        "enabled": config.get('auto-download', {}).get('schedule-enabled', False),
        "times": config.get('auto-download', {}).get('schedule-times', [])
    }
    return jsonify(schedule_config)

@app.route('/api/schedule', methods=['POST'])
def set_schedule():
    """Set auto-download schedule"""
    data = request.json
    
    config = load_config()
    if 'auto-download' not in config:
        config['auto-download'] = {}
    
    config['auto-download']['schedule-enabled'] = data.get('enabled', False)
    config['auto-download']['schedule-times'] = data.get('times', [])
    save_config(config)
    
    # Restart scheduler with new times
    restart_scheduler()
    
    return jsonify({"success": True})

def restart_scheduler():
    """Restart the auto-download scheduler with current settings"""
    # This would integrate with the existing auto-download scheduler
    pass


# ========================================
# Lyrics API
# ========================================

@app.route('/api/lyrics/settings', methods=['GET'])
def get_lyrics_settings():
    """Get lyrics settings"""
    config = load_config()
    lyrics_config = config.get('lyrics', {
        "embed-in-file": True,
        "save-lrc-file": True,
        "fetch-provider": "apple",
        "auto-generate": False,
        "whisper-model": "base"
    })
    return jsonify(lyrics_config)

@app.route('/api/lyrics/settings', methods=['POST'])
def set_lyrics_settings():
    """Set lyrics settings"""
    data = request.json
    
    config = load_config()
    config['lyrics'] = {
        "embed-in-file": data.get('embed-in-file', True),
        "save-lrc-file": data.get('save-lrc-file', True),
        "fetch-provider": data.get('fetch-provider', 'apple'),
        "auto-generate": data.get('auto-generate', False),
        "whisper-model": data.get('whisper-model', 'base')
    }
    save_config(config)
    
    return jsonify({"success": True})


# ========================================
# Auto Lyrics Generation (Whisper AI)
# ========================================

def check_whisper_installed():
    """Check if whisper is installed"""
    try:
        import whisper
        return True
    except ImportError:
        return False

def get_whisper_model(model_name="base"):
    """Load or get cached whisper model"""
    global _whisper_model, _whisper_model_name
    
    if not hasattr(get_whisper_model, '_model') or get_whisper_model._model_name != model_name:
        try:
            import whisper
            print(f"Loading Whisper model: {model_name}")
            get_whisper_model._model = whisper.load_model(model_name)
            get_whisper_model._model_name = model_name
        except Exception as e:
            print(f"Error loading Whisper model: {e}")
            return None
    
    return get_whisper_model._model

def generate_lyrics_with_whisper(audio_path, model_name="base"):
    """Generate lyrics from audio file using Whisper AI"""
    try:
        import whisper
        
        model = get_whisper_model(model_name)
        if model is None:
            return None, "Failed to load Whisper model"
        
        print(f"Transcribing: {audio_path}")
        result = model.transcribe(audio_path, verbose=False)
        
        # Build LRC format with timestamps
        lrc_lines = []
        for segment in result.get('segments', []):
            start_time = segment['start']
            text = segment['text'].strip()
            
            # Convert to LRC timestamp format [mm:ss.xx]
            minutes = int(start_time // 60)
            seconds = start_time % 60
            timestamp = f"[{minutes:02d}:{seconds:05.2f}]"
            lrc_lines.append(f"{timestamp}{text}")
        
        lrc_content = "\n".join(lrc_lines)
        plain_text = result.get('text', '').strip()
        
        return {
            'lrc': lrc_content,
            'plain': plain_text,
            'language': result.get('language', 'unknown')
        }, None
        
    except ImportError:
        return None, "Whisper not installed. Install with: pip install openai-whisper"
    except Exception as e:
        return None, f"Transcription error: {str(e)}"

def embed_lyrics_in_file(audio_path, lyrics_text, ai_generated=False):
    """Embed lyrics into audio file metadata"""
    try:
        from mutagen import File
        from mutagen.id3 import ID3, USLT, COMM
        from mutagen.mp4 import MP4
        
        audio = File(audio_path)
        if audio is None:
            return False, "Unknown audio format"
        
        if isinstance(audio, MP4):
            # M4A/AAC files
            audio['\xa9lyr'] = [lyrics_text]
            if ai_generated:
                # Add comment indicating AI-generated lyrics
                audio['\xa9cmt'] = ['Lyrics generated by Whisper AI']
            audio.save()
        elif hasattr(audio, 'tags') and audio.tags is not None:
            # MP3 files with ID3
            if not isinstance(audio.tags, ID3):
                audio.add_tags()
            audio.tags.add(USLT(encoding=3, lang='eng', desc='Lyrics', text=lyrics_text))
            if ai_generated:
                # Add comment indicating AI-generated lyrics
                audio.tags.add(COMM(encoding=3, lang='eng', desc='Lyrics Source', text='Lyrics generated by Whisper AI'))
            audio.save()
        else:
            return False, "Unsupported audio format for lyrics"
        
        return True, None
    except Exception as e:
        return False, str(e)

def check_file_has_lyrics(audio_path):
    """Check if audio file already has embedded lyrics"""
    try:
        from mutagen import File
        from mutagen.mp4 import MP4
        
        audio = File(audio_path)
        if audio is None:
            return False
        
        if isinstance(audio, MP4):
            return '\xa9lyr' in audio and audio['\xa9lyr']
        elif hasattr(audio, 'tags') and audio.tags is not None:
            # Check for USLT (unsynchronized lyrics) tag
            for key in audio.tags.keys():
                if key.startswith('USLT'):
                    return True
        return False
    except:
        return False

@app.route('/api/lyrics/generate', methods=['POST'])
def api_generate_lyrics():
    """Generate lyrics for an audio file using Whisper"""
    data = request.json
    audio_path = data.get('path')
    
    if not audio_path or not os.path.exists(audio_path):
        return jsonify({"success": False, "error": "File not found"})
    
    config = load_config()
    lyrics_config = config.get('lyrics', {})
    model_name = lyrics_config.get('whisper-model', 'base')
    
    # Check if whisper is installed
    if not check_whisper_installed():
        return jsonify({
            "success": False, 
            "error": "Whisper not installed. Install with: pip install openai-whisper"
        })
    
    result, error = generate_lyrics_with_whisper(audio_path, model_name)
    
    if error:
        return jsonify({"success": False, "error": error})
    
    # Optionally embed lyrics
    if data.get('embed', True) and lyrics_config.get('embed-in-file', True):
        embed_success, embed_error = embed_lyrics_in_file(audio_path, result['plain'], ai_generated=True)
        if not embed_success:
            print(f"Failed to embed lyrics: {embed_error}")
    
    # Optionally save LRC file
    if data.get('save_lrc', True) and lyrics_config.get('save-lrc-file', True):
        lrc_path = os.path.splitext(audio_path)[0] + '.lrc'
        try:
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(result['lrc'])
        except Exception as e:
            print(f"Failed to save LRC file: {e}")
    
    return jsonify({
        "success": True,
        "lyrics": result['plain'],
        "lrc": result['lrc'],
        "language": result['language']
    })

@app.route('/api/lyrics/check-whisper', methods=['GET'])
def api_check_whisper():
    """Check if Whisper is installed and available"""
    installed = check_whisper_installed()
    return jsonify({
        "installed": installed,
        "install_command": "pip install openai-whisper" if not installed else None
    })


# ============================================================
# Update Endpoints
# ============================================================


@app.route('/api/update/check', methods=['POST'])
def check_for_updates():
    """Check GitHub releases for a newer version with an EXE asset"""
    config = load_config()
    config['last-update-check'] = datetime.now().isoformat()
    save_config(config)

    try:
        api_url = f'https://api.github.com/repos/{UPDATE_REPO}/releases/latest'
        resp = requests.get(api_url, timeout=15, headers={'Accept': 'application/vnd.github.v3+json'})

        if resp.status_code == 404:
            return jsonify({'success': True, 'updates_available': False,
                            'current_version': APP_VERSION,
                            'message': 'No releases found yet.'})

        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'GitHub API returned {resp.status_code}'}), 502

        release = resp.json()
        remote_tag = release.get('tag_name', '').lstrip('v')
        body = release.get('body', '') or ''
        published = release.get('published_at', '')

        # Find the .exe asset in the release
        exe_url = None
        exe_name = None
        for asset in release.get('assets', []):
            name = asset.get('name', '')
            if name.lower().endswith('.exe'):
                exe_url = asset.get('browser_download_url', '')
                exe_name = name
                break

        updates_available = remote_tag and remote_tag != APP_VERSION and exe_url is not None

        result = {
            'success': True,
            'current_version': APP_VERSION,
            'remote_version': remote_tag,
            'updates_available': updates_available,
            'release_notes': body,
            'published_at': published,
            'exe_url': exe_url,
            'exe_name': exe_name,
        }
        if remote_tag and remote_tag != APP_VERSION and not exe_url:
            result['message'] = 'A new version exists but no EXE asset was found in the release.'

        return jsonify(result)
    except requests.exceptions.RequestException as e:
        logger.error(f'Update check network error: {e}')
        return jsonify({'success': False, 'error': f'Network error: {e}'}), 502
    except Exception as e:
        logger.error(f'Update check error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/update/apply', methods=['POST'])
def apply_update():
    """Download the EXE from the release, replace the current executable, and restart"""
    data = request.json or {}
    exe_url = data.get('exe_url', '')

    if not exe_url:
        return jsonify({'success': False, 'error': 'No download URL provided.'}), 400

    try:
        logger.info(f'Downloading update EXE from {exe_url}')
        resp = requests.get(exe_url, timeout=300, stream=True)
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'Download failed ({resp.status_code})'}), 502

        if getattr(sys, 'frozen', False):
            current_exe = sys.executable
        else:
            # Running from source — save the EXE next to app.py
            current_exe = os.path.join(BASE_DIR, 'AppleMusicDownloader.exe')

        # Save the downloaded EXE next to the current one with a temp name
        new_exe = current_exe + '.update'
        old_exe = current_exe + '.old'

        with open(new_exe, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        logger.info(f'Downloaded update EXE ({os.path.getsize(new_exe)} bytes)')

        # Swap: current → .old, new → current
        if os.path.exists(old_exe):
            os.remove(old_exe)
        if os.path.exists(current_exe):
            os.rename(current_exe, old_exe)
        os.rename(new_exe, current_exe)

        logger.info('EXE replaced successfully, scheduling restart')

        # Restart using the new EXE
        def do_restart():
            time.sleep(1)
            # Clean up old backup
            try:
                if os.path.exists(old_exe):
                    os.remove(old_exe)
            except Exception:
                pass  # May be locked; will be cleaned up next time
            os.execv(current_exe, [current_exe] + sys.argv[1:])

        threading.Thread(target=do_restart, daemon=True).start()

        return jsonify({
            'success': True,
            'message': 'Update installed! The program is restarting now...'
        })
    except Exception as e:
        logger.error(f'Update apply error: {e}')
        # Clean up failed download
        new_exe = (sys.executable if getattr(sys, 'frozen', False) else os.path.join(BASE_DIR, 'AppleMusicDownloader.exe')) + '.update'
        if os.path.exists(new_exe):
            try:
                os.remove(new_exe)
            except Exception:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/update/status')
def update_status():
    """Get current version and last update check time"""
    config = load_config()
    return jsonify({
        'version': APP_VERSION,
        'repo': UPDATE_REPO,
        'last_update_check': config.get('last-update-check', None)
    })


@app.route('/api/shutdown', methods=['POST'])
def shutdown_server():
    """Shutdown the application"""
    logger.info("Shutdown requested via settings page")
    # Cancel auto-download timer if running
    global auto_download_timer
    if auto_download_timer:
        auto_download_timer.cancel()
        auto_download_timer = None
    # Use os._exit in a background thread to allow the response to be sent first
    def do_shutdown():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=do_shutdown, daemon=True).start()
    return jsonify({'success': True, 'message': 'Server shutting down...'})


def open_browser(port):
    """Open browser after a short delay to ensure server is running"""
    time.sleep(1.5)
    webbrowser.open(f'http://127.0.0.1:{port}')


def server_is_running(host, port):
    """Return whether another local server already owns the requested port."""
    import socket

    connect_host = '127.0.0.1' if host in ('0.0.0.0', '::') else host
    try:
        with socket.create_connection((connect_host, port), timeout=0.5):
            return True
    except OSError:
        return False


instance_mutex = None


def acquire_single_instance():
    """Atomically claim this application instance on Windows."""
    global instance_mutex
    if os.name != 'nt':
        return True

    import ctypes

    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, 'Local\\AppleMusicDownloader')
    if not mutex:
        return False
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        return False

    instance_mutex = mutex
    return True


if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Apple Music Downloader Web Interface')
    parser.add_argument('--headless', '-H', action='store_true', 
                        help='Run in headless mode (no browser auto-open)')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='Port to run the server on (default: 5000)')
    parser.add_argument('--host', default='127.0.0.1',
                        help='Host to bind to (default: 127.0.0.1)')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Enable debug mode')
    args = parser.parse_args()

    if not acquire_single_instance() or server_is_running(args.host, args.port):
        print(f"Apple Music Downloader is already running at http://127.0.0.1:{args.port}")
        if not args.headless:
            webbrowser.open(f'http://127.0.0.1:{args.port}')
        sys.exit(0)
    
    print("=" * 60)
    print("Apple Music Downloader Web Interface")
    print("=" * 60)
    print(f"Downloads folder: {get_downloads_dir()}")
    print(f"Config file: {CONFIG_FILE}")
    print(f"Mode: {'Headless' if args.headless else 'Normal'}")
    
    # Start Docker and wrapper on startup
    startup_docker_and_wrapper()

    # Start workers only after this process has won the single-instance check.
    start_background_workers()
    
    # Initialize auto-download scheduler
    initialize_auto_download()
    
    print("\n" + "=" * 60)
    print(f"Starting server at http://{args.host}:{args.port}")
    print("=" * 60)
    
    # Open browser if not headless
    if not args.headless:
        browser_thread = threading.Thread(target=open_browser, args=(args.port,), daemon=True)
        browser_thread.start()
    
    socketio.run(app, host=args.host, port=args.port, debug=args.debug, use_reloader=False, allow_unsafe_werkzeug=True)

# Apple Music Downloader Web App

A modern Python Flask web interface for the [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) CLI tool.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- 🎵 **Easy URL Input**: Paste Apple Music URLs for albums, songs, playlists, artists, and music videos
- 🎧 **Quality Selection**: Choose between ALAC (lossless), Dolby Atmos, or AAC
- 📊 **Real-time Progress**: WebSocket-based live updates for download status
- 📁 **Download Queue**: Manage multiple downloads simultaneously
- ⚙️ **Settings Management**: Configure all options through a web interface
- 📱 **Responsive Design**: Works on desktop and mobile browsers
- 🌙 **Dark/Light Theme**: Toggle between themes with persistence
- 📦 **Batch Import**: Paste multiple URLs at once for bulk downloading
- 📜 **Download History**: Track all your downloads with stats
- ⭐ **Favorites**: Save artists, albums, playlists for quick access
- 🆕 **New Releases**: Follow artists and get notified of new music
- 🔔 **Notifications**: Browser notifications for download completion
- 📲 **PWA Support**: Install as a standalone app on desktop/mobile
- 🖥️ **Standalone EXE**: Build as a portable Windows application

## Prerequisites

Before using this web app, you need:

1. **Python 3.10+** installed
2. **apple-music-downloader** (Go CLI tool) - [Installation Guide](https://github.com/zhaarey/apple-music-downloader)
3. **MP4Box** (GPAC) - [Download](https://gpac.io/downloads/gpac-nightly-builds/)
4. **wrapper** (Decryption program) - [GitHub](https://github.com/WorldObservationLog/wrapper)
5. **mp4decrypt** (for MV downloads) - [Download](https://www.bento4.com/downloads/)
6. **Valid Apple Music subscription** and `media-user-token`

## Installation

### 1. Clone or download this project

```bash
cd "d:\VS projects\AMD"
```

### 2. Run the app (auto-installs dependencies!)

The app now self-bootstraps. Just run it and it will install what it needs:

```bash
# Using the batch file (recommended)
run.bat

# Or directly with Python
python start.py

# Or the traditional way
python app.py
```

**First Run**: The app will:
1. Install minimal packages needed to start the web interface
2. Open your browser automatically
3. Show a progress box in the corner while installing remaining packages
4. Offer a "Restart Server" button when installation completes

### 3. (Optional) Manual dependency installation

If you prefer to install everything upfront:

```bash
pip install -r requirements.txt
```

### 4. (Optional) Virtual environment

For isolation, you can use a virtual environment:

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 5. Set up apple-music-downloader

Make sure the Go CLI tool is available. Either:

**Option A**: Clone the apple-music-downloader repo in the same directory:
```bash
git clone https://github.com/zhaarey/apple-music-downloader.git
```

**Option B**: Use Docker (recommended - already configured in `app.py`):
```bash
# The app uses Docker by default. Just make sure Docker Desktop is running.
# Downloads go to the ./downloads folder
```

### 6. Set up the Wrapper Decryption Service

⚠️ **IMPORTANT**: The wrapper service is REQUIRED for downloads to work. Without it, you'll see "no codec found" errors.

The wrapper must be **built locally** - there is no public Docker image available.

#### Quick Start (Windows)

```batch
# Run the included setup script
start-wrapper.bat

# Choose option 6 (Build) first - this clones and builds the wrapper
# Then option 2 (Login) to authenticate with Apple ID
# Then option 1 (Start) to run the service
```

#### Manual Docker Setup

**Step 1: Clone and build the wrapper:**
```bash
# Clone the wrapper repository
git clone https://github.com/WorldObservationLog/wrapper

# Build the Docker image
cd wrapper
docker build --tag amd-wrapper-local .
cd ..
```

**Step 2: Login with your Apple ID (creates authentication tokens):**
```bash
# Create a directory for wrapper data
mkdir wrapper-data

# Login with your Apple ID (interactive - you'll enter 2FA codes here)
docker run -it --rm ^
  -v ./wrapper-data:/app/rootfs/data ^
  -e args="-L your-apple-id@email.com:your-password -H 0.0.0.0" ^
  amd-wrapper-local
```

**Step 3: Start the wrapper service (run this every time):**
```bash
docker run -d --name amd-wrapper --restart unless-stopped ^
  -v ./wrapper-data:/app/rootfs/data ^
  -p 10020:10020 -p 20020:20020 -p 30020:30020 ^
  -e args="-H 0.0.0.0" ^
  amd-wrapper-local
```

**Check if wrapper is running:**
```bash
docker ps --filter name=amd-wrapper
```

### 7. Run the web app

**Easy way (starts wrapper + app):**
```batch
start-all.bat
```

**Or use the self-bootstrapping launcher:**
```bash
python start.py
```

**Or directly:**
```bash
python app.py
```

**Headless mode (no browser auto-open):**
```bash
python app.py --headless
```

**Custom port:**
```bash
python app.py --port 8080
```

The app will start at `http://127.0.0.1:5000`

## Building a Standalone EXE

You can build a standalone Windows executable that doesn't require Python:

### Quick Build

```batch
# Build without console window (recommended)
build.bat

# Build with console window (for debugging)
build_console.bat
```

The executable will be created in `dist\AMD\AMD.exe`

### Running the EXE

```batch
# Normal mode (opens browser automatically)
dist\AMD\AMD.exe

# Headless mode (no browser)
dist\AMD\AMD.exe --headless

# Or use the batch files
dist\AMD\run.bat
dist\AMD\run_headless.bat
```

### What's Included

The build creates a portable folder with:
- `AMD.exe` - The main application
- `templates/` - HTML templates
- `static/` - CSS, JS, icons
- `config.yaml` - Configuration
- `downloads/` - Downloaded music (created on first run)
- `data/` - History, favorites, etc.

## Configuration

### Getting the media-user-token

1. Open [Apple Music](https://music.apple.com) in your browser and log in
2. Open Developer Tools (F12)
3. Go to **Application** → **Storage** → **Cookies** → `https://music.apple.com`
4. Find the cookie named `media-user-token`
5. Copy its value
6. Paste it in the Settings page of this web app

### Settings Overview

| Setting | Description |
|---------|-------------|
| **Storefront** | Your Apple Music region (us, gb, jp, etc.) |
| **Language** | Metadata language (en-US, ja-JP, etc.) |
| **Quality** | ALAC (lossless), Dolby Atmos, or AAC |
| **Cover Size** | Album artwork resolution (600-3000px) |
| **Lyrics** | LRC format, embed in file, etc. |
| **Save Folders** | Where to save downloaded files |

## Usage

### Download an Album

1. Go to Apple Music and copy an album URL
2. Paste the URL in the web app
3. Select your preferred quality
4. Click "Start Download"

### Supported URL Types

- **Albums**: `https://music.apple.com/us/album/album-name/1234567890`
- **Songs**: `https://music.apple.com/us/song/song-name/1234567890`
- **Playlists**: `https://music.apple.com/us/playlist/name/pl.abc123`
- **Artists**: `https://music.apple.com/us/artist/artist-name/1234567890`
- **Music Videos**: `https://music.apple.com/us/music-video/name/1234567890`

## Project Structure

```
AMD/
├── app.py                 # Flask application
├── start.py              # Bootstrap launcher (auto-installs deps)
├── requirements.txt       # Python dependencies
├── config.yaml           # Configuration file (auto-generated)
├── start-all.bat         # Start wrapper + web app
├── start-wrapper.bat     # Manage wrapper service
├── run.bat               # Run app (opens browser) 🌈
├── run_headless.bat      # Run app without browser 🌈
├── build.bat             # Build standalone EXE 🌈
├── build_console.bat     # Build EXE with console (debug) 🌈
├── install.bat           # Initial setup script 🌈
├── downloads/            # Downloaded files
├── data/                 # History, favorites, settings
├── wrapper-data/         # Wrapper auth tokens (created after login)
├── dist/                 # Built EXE output (after build)
├── templates/
│   ├── index.html        # Main download page
│   └── settings.html     # Settings page
└── static/
    ├── css/
    │   └── style.css     # Custom styles
    ├── icons/            # App icons for PWA
    ├── manifest.json     # PWA manifest
    ├── sw.js             # Service worker
    └── js/
        ├── app.js        # Main page JavaScript
        └── settings.js   # Settings page JavaScript
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/download` | POST | Start a new download |
| `/api/downloads` | GET | List all downloads |
| `/api/downloads/<id>` | GET | Get download status |
| `/api/downloads/<id>` | DELETE | Remove download |
| `/api/config` | GET | Get configuration |
| `/api/config` | POST | Update configuration |
| `/api/parse-url` | POST | Parse Apple Music URL |
| `/api/status` | GET | Get system status |
| `/api/wrapper-status` | GET | Check if wrapper is running |
| `/api/wrapper-start` | POST | Start wrapper service |
| `/api/files` | GET | List downloaded files |
| `/api/test-download` | GET | Test download with sample link |

## Troubleshooting

### "Failed to extract info from manifest: no codec found"
This means the wrapper service isn't running or isn't authenticated.
1. Run `start-wrapper.bat` and choose option 4 to check status
2. If not running, choose option 2 to login (first time) then option 1 to start
3. Make sure ports 10020, 20020, 30020 are not blocked

### "Wrapper not running" warning in UI
- The web app shows this when it can't connect to the wrapper on port 10020
- Click "Start Wrapper" in the UI, or run `start-wrapper.bat`
- The wrapper must stay running while downloading

### "Failed to get token"
- Make sure you have internet access
- The authorization token may need to be set manually in settings

### "MP4Box not found"
- Install GPAC and add MP4Box to your system PATH
- Or use Docker mode which includes MP4Box

### Downloads complete but folder is empty
- The wrapper service must be running and authenticated
- Check the Debug Console at the bottom of the page for detailed errors
- Try clicking "Test Download" to see the full command output

## License

This project is for educational purposes only. Please respect copyright laws and Apple's Terms of Service.

## Credits

- [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) by zhaarey
- [wrapper](https://github.com/WorldObservationLog/wrapper) by WorldObservationLog
- [Flask](https://flask.palletsprojects.com/) web framework
- [Bootstrap 5](https://getbootstrap.com/) for UI components


#!/usr/bin/env python3
"""
Apple Music Downloader - Bootstrap Launcher
This script bootstraps the application by installing minimal requirements
then starting the web app which handles the rest.
"""

import subprocess
import sys
import os

# Minimal packages needed to start the web interface
MINIMAL_REQUIREMENTS = [
    'flask',
    'flask-socketio', 
    'pyyaml',
    'requests',
]

def check_package(package):
    """Check if a package is installed"""
    package_name = package.lower().replace('-', '_').replace('>=', '').split('[')[0]
    try:
        __import__(package_name)
        return True
    except ImportError:
        # Try alternate names
        alt_names = {
            'flask_socketio': 'flask_socketio',
            'pyyaml': 'yaml',
        }
        if package_name in alt_names:
            try:
                __import__(alt_names[package_name])
                return True
            except ImportError:
                pass
        return False

def install_package(package):
    """Install a package using pip"""
    print(f"  Installing {package}...")
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '-q', package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        # Try with --user flag
        try:
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', '-q', '--user', package],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except subprocess.CalledProcessError:
            return False

def main():
    print("=" * 60)
    print("  Apple Music Downloader - Starting...")
    print("=" * 60)
    print()
    
    # Check and install minimal requirements
    missing = []
    for pkg in MINIMAL_REQUIREMENTS:
        if not check_package(pkg):
            missing.append(pkg)
    
    if missing:
        print("Installing minimal requirements to start web interface...")
        print()
        for pkg in missing:
            if install_package(pkg):
                print(f"  ✓ {pkg} installed")
            else:
                print(f"  ✗ Failed to install {pkg}")
                print()
                print("Please run: pip install -r requirements.txt")
                input("Press Enter to exit...")
                sys.exit(1)
        print()
        print("Minimal requirements installed!")
        print()
    
    # Change to script directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Import and run the app
    print("Starting web application...")
    print()
    
    # Pass through command line arguments
    sys.argv[0] = 'app.py'  # Pretend we're running app.py directly
    
    try:
        import app
        # The app will handle the rest when imported
    except ImportError as e:
        print(f"Error importing app: {e}")
        print("Try running: pip install -r requirements.txt")
        input("Press Enter to exit...")
        sys.exit(1)

if __name__ == '__main__':
    main()

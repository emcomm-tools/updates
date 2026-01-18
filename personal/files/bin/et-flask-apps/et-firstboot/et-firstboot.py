#!/usr/bin/env python3
"""
EmComm-Tools First Boot Wizard
Author: Claude for Sylvain Deguire (VA2OPS)
Date: January 2026
Version: 1.0.56 - 2026-01-18 - Fix: Use minimal window frame for touch compatibility
                              - Dark title bar matching app background (#1a1a1a)
                              - Window adapts to screen size (avoids bottom panel)
                              - Buttons always visible at bottom
                              - Scrollable content areas

Flow:
1. Welcome + Language selection
2. User setup (callsign, grid, Winlink password)
3. Radio selection + show settings
4. Drive selection (local or USB) - BEFORE downloads
5. Download tiles (US, Canada, World - ALL automatic)
6. Download OSM maps (Canada provinces list)
7. Download Wikipedia ZIM files (EN + FR)
8. Create symlinks if USB selected
9. Complete
"""

import os
import sys
import json
import subprocess
import threading
import time
import re
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session

app = Flask(__name__)
app.secret_key = 'emcomm-tools-firstboot-va2ops'

# =============================================================================
# CONFIGURATION
# =============================================================================

# Paths - relative to script location
# Script location: /opt/emcomm-tools/bin/et-flask-apps/et-firstboot/et-firstboot.py
# Radios location: /opt/emcomm-tools/conf/radios.d/
# Relative path:   ../../../conf/radios.d/

# Try __file__ first, fallback to current directory
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path('.').resolve()

# Go up 3 levels: et-firstboot -> et-flask-apps -> bin -> emcomm-tools
ET_BASE = SCRIPT_DIR.parent.parent.parent  # /opt/emcomm-tools

# Verify the path makes sense - if conf/radios.d doesn't exist, try current dir approach
if not (ET_BASE / "conf" / "radios.d").exists():
    SCRIPT_DIR = Path('.').resolve()
    ET_BASE = SCRIPT_DIR.parent.parent.parent
    
# Still not found? Try going up from current working directory
if not (ET_BASE / "conf" / "radios.d").exists():
    cwd = Path.cwd()
    for _ in range(6):
        if (cwd / "conf" / "radios.d").exists():
            ET_BASE = cwd
            break
        cwd = cwd.parent

USER_CONF = Path.home() / ".config" / "emcomm-tools" / "user.json"
RADIOS_DIR = ET_BASE / "conf" / "radios.d"
ACTIVE_RADIO_LINK = RADIOS_DIR / "active-radio.json"
TILESET_DIR = Path.home() / ".local/share/emcomm-tools/mbtileserver/tilesets"
PBF_MAP_DIR = Path.home() / "my-maps"
NAVIT_MAP_DIR = Path.home() / ".navit/maps"
ZIM_DIR = Path.home() / "wikipedia"

print(f"ET_BASE resolved to: {ET_BASE}")
print(f"RADIOS_DIR: {RADIOS_DIR} (exists: {RADIOS_DIR.exists()})")

# Tile download URLs
TILE_BASE_URL = "https://github.com/thetechprepper/emcomm-tools-os-community/releases/download"
TILE_RELEASE = "emcomm-tools-os-community-20251128-r5-final-5.0.0"
TILE_FILES = [
    "osm-us-zoom0to11-20251120.mbtiles",
    "osm-ca-zoom0to10-20251120.mbtiles",
    "osm-world-zoom0to7-20251121.mbtiles"
]

# OSM URLs
OSM_CANADA_URL = "http://download.geofabrik.de/north-america/canada.html"
OSM_USA_URL = "http://download.geofabrik.de/north-america/us.html"
OSM_BASE_CANADA = "http://download.geofabrik.de/north-america/canada"
OSM_BASE_USA = "http://download.geofabrik.de/north-america/us"

# Wikipedia URL
KIWIX_URL = "http://download.kiwix.org/zim/wikipedia"

# Download status tracking
download_status = {
    'current': '',
    'progress': 0,
    'total': 0,
    'done': False,
    'error': None,
    'files_done': []
}

# =============================================================================
# TRANSLATIONS
# =============================================================================

TRANSLATIONS = {
    'en': {
        'welcome': 'Welcome to EmComm-Tools',
        'welcome_msg': 'This wizard will help you configure your emergency communications system.',
        'select_language': 'Select Language',
        'next': 'Next',
        'back': 'Back',
        'skip': 'Skip',
        'finish': 'Finish',
        'step': 'Step',
        'of': 'of',
        
        # User setup
        'user_setup': 'User Setup',
        'callsign': 'Callsign',
        'callsign_placeholder': 'e.g., W1ABC',
        'grid_square': 'Grid Square',
        'grid_placeholder': 'e.g., FN35fl',
        'winlink_password': 'Winlink Password',
        'password_placeholder': 'Your Winlink password',
        'password_not_set': 'Not set',
        'password_set': 'Set',
        
        # Radio
        'radio_setup': 'Radio Setup',
        'select_radio': 'Select Your Radio',
        'no_radios': 'No radios configured',
        'radio_settings': 'Radio Settings',
        'manufacturer': 'Manufacturer',
        'model': 'Model',
        'baud_rate': 'Baud Rate',
        'data_bits': 'Data Bits',
        'stop_bits': 'Stop Bits',
        'notes': 'Notes',
        
        # Drive selection
        'drive_setup': 'Storage Setup',
        'select_drive': 'Select Download Destination',
        'local_drive': 'Local Drive',
        'local_desc': 'Download files to your local hard drive',
        'usb_drive': 'USB/External Drive',
        'usb_desc': 'Download files to external storage',
        'select_usb': 'Select USB Drive',
        'no_usb': 'No USB drives detected',
        'refresh': 'Refresh',
        'usb_checking': 'Checking write access...',
        'usb_write_ok': 'Drive is writable',
        'usb_write_protected': 'Write-protected',
        'usb_read_only': 'This drive is read-only or write-protected. Please unlock it or choose another drive.',
        'usb_help_title': 'How to fix a write-protected drive',
        'usb_help_step1': 'Check if your USB drive has a physical write-protect switch and slide it to unlock.',
        'usb_help_step2': 'Or run this command in a terminal:',
        'usb_help_step3': 'Then click on the drive again to retry.',
        'usb_help_close': 'Close',
        'usb_help_copy': 'Copy',
        'usb_help_copied': 'Copied!',
        'usb_how_to_fix': 'How to fix?',
        
        # Downloads
        'download_tiles': 'Download Map Tiles',
        'tiles_desc': 'Downloading offline map tiles (US, Canada, World)',
        'download_osm': 'Download OSM Maps',
        'osm_desc': 'Select a region for offline navigation',
        'select_country': 'Select Country',
        'canada': 'Canada',
        'usa': 'United States',
        'select_region': 'Select Province/State',
        'select_province': 'Select Province',
        'select_state': 'Select State',
        'download_wiki': 'Download Wikipedia',
        'wiki_desc': 'Select offline Wikipedia files',
        'english': 'English',
        'french': 'French',
        
        # Progress
        'downloading': 'Downloading',
        'processing': 'Processing',
        'complete': 'Complete',
        'error': 'Error',
        'download_complete': 'Download Complete',
        'creating_symlinks': 'Creating Symlinks',
        
        # Final
        'setup_complete': 'Setup Complete!',
        'complete_msg': 'Your EmComm-Tools system is ready to use.',
        'restart_note': 'Your system is ready! You can run this wizard again anytime from the applications menu.',
    },
    'fr': {
        'welcome': 'Bienvenue à EmComm-Tools',
        'welcome_msg': 'Cet assistant vous aidera à configurer votre système de communications d\'urgence.',
        'select_language': 'Choisir la langue',
        'next': 'Suivant',
        'back': 'Retour',
        'skip': 'Passer',
        'finish': 'Terminer',
        'step': 'Étape',
        'of': 'de',
        
        # User setup
        'user_setup': 'Configuration utilisateur',
        'callsign': 'Indicatif',
        'callsign_placeholder': 'ex: VE2ABC',
        'grid_square': 'Carré de grille',
        'grid_placeholder': 'ex: FN35fl',
        'winlink_password': 'Mot de passe Winlink',
        'password_placeholder': 'Votre mot de passe Winlink',
        'password_not_set': 'Non défini',
        'password_set': 'Défini',
        
        # Radio
        'radio_setup': 'Configuration radio',
        'select_radio': 'Sélectionnez votre radio',
        'no_radios': 'Aucune radio configurée',
        'radio_settings': 'Paramètres radio',
        'manufacturer': 'Fabricant',
        'model': 'Modèle',
        'baud_rate': 'Débit en bauds',
        'data_bits': 'Bits de données',
        'stop_bits': 'Bits d\'arrêt',
        'notes': 'Notes',
        
        # Drive selection
        'drive_setup': 'Configuration stockage',
        'select_drive': 'Sélectionnez la destination',
        'local_drive': 'Disque local',
        'local_desc': 'Télécharger sur le disque dur local',
        'usb_drive': 'Clé USB/Disque externe',
        'usb_desc': 'Télécharger sur un stockage externe',
        'select_usb': 'Sélectionnez le disque USB',
        'no_usb': 'Aucun disque USB détecté',
        'refresh': 'Actualiser',
        'usb_checking': 'Vérification de l\'accès en écriture...',
        'usb_write_ok': 'Disque inscriptible',
        'usb_write_protected': 'Protégé en écriture',
        'usb_read_only': 'Ce disque est en lecture seule ou protégé en écriture. Veuillez le déverrouiller ou choisir un autre disque.',
        'usb_help_title': 'Comment réparer un disque protégé',
        'usb_help_step1': 'Vérifiez si votre clé USB a un interrupteur de protection physique et glissez-le pour déverrouiller.',
        'usb_help_step2': 'Ou exécutez cette commande dans un terminal:',
        'usb_help_step3': 'Puis cliquez à nouveau sur le disque pour réessayer.',
        'usb_help_close': 'Fermer',
        'usb_help_copy': 'Copier',
        'usb_help_copied': 'Copié!',
        'usb_how_to_fix': 'Comment réparer?',
        
        # Downloads
        'download_tiles': 'Télécharger les tuiles',
        'tiles_desc': 'Téléchargement des tuiles de carte (US, Canada, Monde)',
        'download_osm': 'Télécharger cartes OSM',
        'osm_desc': 'Sélectionnez une région pour la navigation hors ligne',
        'select_country': 'Sélectionnez le pays',
        'canada': 'Canada',
        'usa': 'États-Unis',
        'select_region': 'Sélectionnez la province/état',
        'select_province': 'Sélectionnez la province',
        'select_state': 'Sélectionnez l\'état',
        'download_wiki': 'Télécharger Wikipédia',
        'wiki_desc': 'Sélectionnez les fichiers Wikipédia hors ligne',
        'english': 'Anglais',
        'french': 'Français',
        
        # Progress
        'downloading': 'Téléchargement',
        'processing': 'Traitement',
        'complete': 'Terminé',
        'error': 'Erreur',
        'download_complete': 'Téléchargement terminé',
        'creating_symlinks': 'Création des liens symboliques',
        
        # Final
        'setup_complete': 'Configuration terminée!',
        'complete_msg': 'Votre système EmComm-Tools est prêt.',
        'restart_note': 'Votre système est prêt! Vous pouvez relancer cet assistant à tout moment depuis le menu des applications.',
    }
}

def t(key):
    """Get translation for current language"""
    lang = session.get('lang', 'fr')
    return TRANSLATIONS.get(lang, TRANSLATIONS['fr']).get(key, key)

# =============================================================================
# CSS STYLES
# =============================================================================

CSS = """
:root {
    --bg-dark: #1a1a1a;
    --bg-card: rgba(26, 26, 26, 0.98);
    --bg-input: #2d2d2d;
    --bg-hover: #353535;
    --text-primary: #e0e0e0;
    --text-secondary: #9e9e9e;
    --text-muted: #666;
    --accent-primary: #FFA500;
    --accent-secondary: #ff8c00;
    --accent-success: #4ade80;
    --accent-warning: #fbbf24;
    --accent-danger: #f87171;
    --border-color: #404040;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
    height: 100%;
    overflow: hidden;
}

body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: var(--bg-dark);
    color: var(--text-primary);
    height: 100vh;
    padding: 20px;
    display: flex;
    flex-direction: column;
}

.container {
    max-width: 600px;
    margin: 0 auto;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

/* Close button in top-right (hidden when using window frame) */
.close-btn {
    position: absolute;
    top: 10px;
    right: 15px;
    background: none;
    border: none;
    color: #888;
    font-size: 1.2rem;
    cursor: pointer;
    display: none;  /* Hidden - using window frame instead */
}

.header {
    text-align: center;
    margin-bottom: 20px;
    padding-top: 10px;
    flex-shrink: 0;
}

.header h1, .header .step-indicator {
    -webkit-user-select: none;
}

.header img {
    width: 80px;
    height: 80px;
    margin-bottom: 15px;
}

.header h1 {
    font-size: 1.6rem;
    color: var(--accent-primary);
    margin-bottom: 10px;
}

.step-indicator {
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 25px;
    margin-bottom: 20px;
    flex: 1;
    overflow-y: auto;
    min-height: 0;
}

.card h2 {
    color: var(--accent-primary);
    font-size: 1.2rem;
    margin-bottom: 20px;
}

.form-group {
    margin-bottom: 20px;
}

.form-group label {
    display: block;
    margin-bottom: 8px;
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.form-group input,
.form-group select {
    width: 100%;
    padding: 12px 15px;
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    color: var(--text-primary);
    font-size: 1rem;
}

.form-group input:focus,
.form-group select:focus {
    outline: none;
    border-color: var(--accent-primary);
}

.form-group input::placeholder {
    color: var(--text-muted);
}

.radio-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.radio-item {
    padding: 15px;
    background: var(--bg-input);
    border: 2px solid var(--border-color);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s;
}

.radio-item:hover {
    border-color: var(--accent-primary);
    background: rgba(255, 165, 0, 0.1);
}

.radio-item.selected {
    border-color: var(--accent-primary);
    background: rgba(255, 165, 0, 0.15);
}

.radio-item .name {
    font-weight: 600;
    color: var(--text-primary);
}

.radio-item .details {
    font-size: 0.85rem;
    color: var(--text-secondary);
    margin-top: 5px;
}

.drive-options {
    display: flex;
    flex-direction: column;
    gap: 15px;
}

.drive-option {
    padding: 20px;
    background: var(--bg-input);
    border: 2px solid var(--border-color);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.2s;
}

.drive-option:hover {
    border-color: var(--accent-primary);
}

.drive-option.selected {
    border-color: var(--accent-primary);
    background: rgba(255, 165, 0, 0.15);
}

.drive-option .icon {
    font-size: 2rem;
    margin-bottom: 10px;
}

.drive-option .title {
    font-weight: 600;
    font-size: 1.1rem;
    margin-bottom: 5px;
}

.drive-option .desc {
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.usb-select {
    margin-top: 15px;
    padding: 15px;
    background: var(--bg-input);
    border-radius: 8px;
    display: none;
}

.usb-select.visible {
    display: block;
}

.region-list {
    max-height: 300px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.region-item {
    padding: 12px 15px;
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
}

.region-item:hover {
    border-color: var(--accent-primary);
}

.region-item.selected {
    border-color: var(--accent-primary);
    background: rgba(255, 165, 0, 0.15);
}

.wiki-list {
    max-height: 350px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.wiki-item {
    padding: 12px 15px;
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 10px;
}

.wiki-item:hover {
    border-color: var(--accent-primary);
}

.wiki-item.selected {
    border-color: var(--accent-primary);
    background: rgba(255, 165, 0, 0.15);
}

.wiki-item input[type="checkbox"] {
    width: 18px;
    height: 18px;
    accent-color: var(--accent-primary);
}

.wiki-item.exists {
    border-color: var(--accent-success);
    background: rgba(74, 222, 128, 0.1);
    opacity: 0.8;
}

.wiki-item.exists input[type="checkbox"]:disabled {
    accent-color: var(--accent-success);
}

.progress-container {
    margin: 20px 0;
}

.progress-bar {
    height: 8px;
    background: var(--bg-input);
    border-radius: 4px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary));
    border-radius: 4px;
    transition: width 0.3s;
}

.progress-text {
    margin-top: 10px;
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.status-list {
    margin-top: 15px;
    font-size: 0.85rem;
}

.status-item {
    padding: 8px 0;
    display: flex;
    align-items: center;
    gap: 10px;
}

.status-item .icon {
    width: 20px;
    text-align: center;
}

.status-item.done .icon { color: var(--accent-success); }
.status-item.pending .icon { color: var(--text-secondary); }
.status-item.active .icon { color: var(--accent-warning); }
.status-item.error .icon { color: var(--accent-danger); }

.settings-table {
    width: 100%;
    border-collapse: collapse;
}

.settings-table tr {
    border-bottom: 1px solid var(--border-color);
}

.settings-table td {
    padding: 10px 0;
}

.settings-table td:first-child {
    color: var(--text-secondary);
    width: 40%;
}

.settings-table td:last-child {
    color: var(--text-primary);
    font-family: monospace;
}

.buttons {
    display: flex;
    gap: 15px;
    margin-top: 15px;
    flex-shrink: 0;
    padding-bottom: 10px;
}

.btn {
    flex: 1;
    padding: 14px 20px;
    border: none;
    border-radius: 10px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-primary {
    background: var(--accent-primary);
    color: #1a1a1a;
}

.btn-primary:hover {
    background: var(--accent-secondary);
    transform: translateY(-2px);
}

.btn-secondary {
    background: var(--bg-input);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
}

.btn-secondary:hover {
    background: var(--bg-hover);
    border-color: var(--accent-primary);
}

.btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
}

.lang-select {
    display: flex;
    gap: 15px;
    justify-content: center;
    margin: 30px 0;
}

.lang-btn {
    padding: 15px 30px;
    background: var(--bg-input);
    border: 2px solid var(--border-color);
    border-radius: 12px;
    color: var(--text-primary);
    font-size: 1.1rem;
    cursor: pointer;
    transition: all 0.2s;
}

.lang-btn:hover {
    border-color: var(--accent-primary);
    background: rgba(255, 165, 0, 0.1);
}

.dest-info {
    background: rgba(255, 165, 0, 0.1);
    border: 1px solid rgba(255, 165, 0, 0.3);
    border-radius: 8px;
    padding: 12px 15px;
    margin-bottom: 20px;
    font-size: 0.9rem;
}

.dest-info .label { color: var(--text-secondary); }
.dest-info .path { color: var(--accent-primary); font-family: monospace; }

.tabs {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
}

.tab {
    flex: 1;
    padding: 12px;
    background: var(--bg-input);
    border: 2px solid var(--border-color);
    border-radius: 10px;
    text-align: center;
    cursor: pointer;
    font-weight: 500;
    color: var(--text-secondary);
}

.tab:hover {
    background: var(--bg-hover);
}

.tab.active {
    border-color: var(--accent-primary);
    background: rgba(255, 165, 0, 0.15);
    color: var(--accent-primary);
}

.success-icon {
    font-size: 4rem;
    color: var(--accent-success);
    margin-bottom: 20px;
}

.info-box {
    background: rgba(255, 165, 0, 0.1);
    border: 1px solid rgba(255, 165, 0, 0.3);
    border-radius: 8px;
    padding: 15px;
    margin: 15px 0;
    font-size: 0.9rem;
    color: var(--text-secondary);
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.spinner {
    display: inline-block;
    width: 20px;
    height: 20px;
    border: 2px solid var(--border-color);
    border-top-color: var(--accent-primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

select, select option {
    background: #2d2d2d !important;
    color: #e0e0e0 !important;
}

/* Scrollbar styling for better visibility on dark theme */
.card::-webkit-scrollbar,
.radio-list::-webkit-scrollbar,
.region-list::-webkit-scrollbar,
.wiki-list::-webkit-scrollbar,
.notes-content::-webkit-scrollbar {
    width: 8px;
}

.card::-webkit-scrollbar-track,
.radio-list::-webkit-scrollbar-track,
.region-list::-webkit-scrollbar-track,
.wiki-list::-webkit-scrollbar-track,
.notes-content::-webkit-scrollbar-track {
    background: var(--bg-input);
    border-radius: 4px;
}

.card::-webkit-scrollbar-thumb,
.radio-list::-webkit-scrollbar-thumb,
.region-list::-webkit-scrollbar-thumb,
.wiki-list::-webkit-scrollbar-thumb,
.notes-content::-webkit-scrollbar-thumb {
    background: var(--border-color);
    border-radius: 4px;
}

.card::-webkit-scrollbar-thumb:hover,
.radio-list::-webkit-scrollbar-thumb:hover,
.region-list::-webkit-scrollbar-thumb:hover,
.wiki-list::-webkit-scrollbar-thumb:hover,
.notes-content::-webkit-scrollbar-thumb:hover {
    background: var(--accent-primary);
}

/* Notes content scrollable area */
.notes-content {
    max-height: 250px;
    overflow-y: auto;
    padding-right: 10px;
}
"""

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def load_user_config():
    """Load user configuration from JSON file"""
    if USER_CONF.exists():
        try:
            with open(USER_CONF) as f:
                return json.load(f)
        except:
            pass
    return {
        'callsign': 'N0CALL',
        'grid': '',
        'winlinkPasswd': ''
    }

def save_user_config(config):
    """Save user configuration to JSON file"""
    try:
        USER_CONF.parent.mkdir(parents=True, exist_ok=True)
        with open(USER_CONF, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"[SAVE_CONFIG] Successfully saved to {USER_CONF}")
        # Verify the save
        with open(USER_CONF, 'r') as f:
            saved = json.load(f)
            print(f"[SAVE_CONFIG] Verified grid: '{saved.get('grid', 'NOT FOUND')}'")
    except Exception as e:
        print(f"[SAVE_CONFIG] ERROR saving config: {e}")

def set_active_radio(radio_id):
    """Set active radio by creating symlink."""
    print(f"[RADIO] set_active_radio called with: {radio_id}")
    
    if not radio_id or radio_id == 'none':
        return True
    
    target = RADIOS_DIR / f"{radio_id}.json"
    if not target.exists():
        print(f"[RADIO] Target file does not exist: {target}")
        return False
    
    try:
        if ACTIVE_RADIO_LINK.exists() or ACTIVE_RADIO_LINK.is_symlink():
            ACTIVE_RADIO_LINK.unlink()
        
        os.symlink(target.name, str(ACTIVE_RADIO_LINK))
        print(f"[RADIO] Created symlink: {ACTIVE_RADIO_LINK} -> {target.name}")
        return True
    except PermissionError:
        try:
            subprocess.run(['sudo', 'rm', '-f', str(ACTIVE_RADIO_LINK)], check=False)
            subprocess.run(['sudo', 'ln', '-sf', target.name, str(ACTIVE_RADIO_LINK)], 
                          check=True, cwd=str(RADIOS_DIR))
            print(f"[RADIO] Created symlink with sudo")
            return True
        except Exception as e:
            print(f"[RADIO] Failed with sudo: {e}")
            return False
    except Exception as e:
        print(f"[RADIO] Error: {e}")
        return False

def get_radios():
    """Get list of configured radios"""
    radios = []
    
    print(f"Looking for radios in: {RADIOS_DIR}")
    
    if not RADIOS_DIR.exists():
        print(f"WARNING: RADIOS_DIR does not exist: {RADIOS_DIR}")
        return radios
    
    for f in sorted(RADIOS_DIR.glob("*.json")):
        # Skip the active-radio symlink
        if f.name == "active-radio.json":
            continue
        try:
            with open(f) as fp:
                data = json.load(fp)
                data['filename'] = f.stem
                radios.append(data)
                print(f"  Loaded radio: {f.stem} - {data.get('model', 'Unknown')}")
        except Exception as e:
            print(f"  Error loading {f}: {e}")
    
    print(f"Total radios found: {len(radios)}")
    return radios

def get_usb_drives():
    """Get list of mounted USB drives"""
    drives = []
    try:
        result = subprocess.run(['lsblk', '-J', '-o', 'NAME,SIZE,MOUNTPOINT,LABEL,HOTPLUG'],
                              capture_output=True, text=True)
        data = json.loads(result.stdout)
        for device in data.get('blockdevices', []):
            # Check children (partitions)
            for child in device.get('children', []):
                if child.get('hotplug') and child.get('mountpoint'):
                    drives.append({
                        'name': child.get('label') or child.get('name'),
                        'path': child.get('mountpoint'),
                        'size': child.get('size')
                    })
    except:
        pass
    
    # Also check /media/$USER
    media_path = Path(f"/media/{os.environ.get('USER', 'user')}")
    if media_path.exists():
        for d in media_path.iterdir():
            if d.is_mount():
                if not any(drv['path'] == str(d) for drv in drives):
                    drives.append({
                        'name': d.name,
                        'path': str(d),
                        'size': ''
                    })
    
    return drives

def check_path_writable(path):
    """Check if a path is writable by attempting to create a test file"""
    if not path:
        return False
    
    test_file = Path(path) / ".emcomm-write-test"
    try:
        test_file.touch()
        test_file.unlink()
        return True
    except (PermissionError, OSError, IOError):
        return False
    except Exception:
        return False

def get_download_path():
    """Get the configured download path"""
    drive_type = session.get('drive_type', 'local')
    if drive_type == 'usb':
        return Path(session.get('usb_path', ''))
    return Path.home()

def create_symlinks():
    """Create symlinks from USB to local directories"""
    usb_path = Path(session.get('usb_path', ''))
    if not usb_path.exists():
        return []
    
    results = []
    
    # Symlink tilesets
    usb_tiles = usb_path / "tilesets"
    if usb_tiles.exists():
        local_tiles = TILESET_DIR
        local_tiles.parent.mkdir(parents=True, exist_ok=True)
        if local_tiles.exists() and not local_tiles.is_symlink():
            backup = local_tiles.with_name(f"tilesets.backup.{int(time.time())}")
            local_tiles.rename(backup)
            results.append(f"Backed up: {backup}")
        if local_tiles.is_symlink():
            local_tiles.unlink()
        local_tiles.symlink_to(usb_tiles)
        results.append(f"Linked: {local_tiles} -> {usb_tiles}")
    
    # Symlink OSM maps
    usb_maps = usb_path / "my-maps"
    if usb_maps.exists():
        local_maps = PBF_MAP_DIR
        local_maps.parent.mkdir(parents=True, exist_ok=True)
        if local_maps.exists() and not local_maps.is_symlink():
            backup = local_maps.with_name(f"my-maps.backup.{int(time.time())}")
            local_maps.rename(backup)
            results.append(f"Backed up: {backup}")
        if local_maps.is_symlink():
            local_maps.unlink()
        local_maps.symlink_to(usb_maps)
        results.append(f"Linked: {local_maps} -> {usb_maps}")
    
    # Symlink Wikipedia - INDIVIDUAL FILES ONLY (keep existing folder intact)
    usb_wiki = usb_path / "wikipedia"
    if usb_wiki.exists():
        local_wiki = ZIM_DIR
        local_wiki.mkdir(parents=True, exist_ok=True)  # Ensure folder exists
        
        # CLEANUP: Remove broken symlinks first
        for item in local_wiki.iterdir():
            if item.is_symlink():
                # Check if symlink target exists
                try:
                    target = item.resolve()
                    if not target.exists():
                        item.unlink()
                        results.append(f"Removed broken link: {item.name}")
                except:
                    # Can't resolve = broken, remove it
                    item.unlink()
                    results.append(f"Removed broken link: {item.name}")
        
        # Link each ZIM file from USB into local folder
        for zim_file in usb_wiki.glob("*.zim"):
            local_file = local_wiki / zim_file.name
            # Remove existing symlink if present
            if local_file.is_symlink():
                local_file.unlink()
            # Don't overwrite real files from skel
            if not local_file.exists():
                local_file.symlink_to(zim_file)
                results.append(f"Linked: {zim_file.name}")
    
    return results

# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def index():
    """Welcome page with language selection"""
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EmComm-Tools First Boot</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>🛰️ EmComm-Tools</h1>
            <p style="color: #888; margin-top: 10px;">Emergency Communications System</p>
        </div>
        
        <div class="card" style="text-align: center;">
            <h2>Choisir la langue / Select Language</h2>
            <div class="lang-select">
                <a href="{{ url_for('set_language', lang='fr') }}" class="lang-btn">Français</a>
                <a href="{{ url_for('set_language', lang='en') }}" class="lang-btn">English</a>
            </div>
        </div>
    </div>
</body>
</html>
''', css=CSS, t=t)

@app.route('/lang/<lang>')
def set_language(lang):
    """Set language and redirect to step 1"""
    session['lang'] = lang if lang in ['en', 'fr'] else 'fr'
    return redirect(url_for('user_setup'))

@app.route('/user', methods=['GET', 'POST'])
def user_setup():
    """Step 1: User configuration"""
    if request.method == 'POST':
        config = load_user_config()
        
        # Debug: log what we receive from form
        raw_grid = request.form.get('grid', '')
        print(f"[USER_SETUP] Raw grid from form: '{raw_grid}'")
        
        config['callsign'] = request.form.get('callsign', '').upper().strip() or 'N0CALL'
        config['grid'] = raw_grid.upper().strip()
        
        print(f"[USER_SETUP] Saving grid: '{config['grid']}'")
        
        password = request.form.get('password', '').strip()
        if password:
            config['winlinkPasswd'] = password
        save_user_config(config)
        
        print(f"[USER_SETUP] Config saved to {USER_CONF}")
        
        session['callsign'] = config['callsign']
        return redirect(url_for('radio_setup'))
    
    config = load_user_config()
    callsign = config.get('callsign', '')
    if callsign == 'N0CALL':
        callsign = ''
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('user_setup') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('user_setup') }}</h1>
            <div class="step-indicator">{{ t('step') }} 1 {{ t('of') }} 8</div>
        </div>
        
        <form method="POST">
            <div class="card">
                <div class="form-group">
                    <label>{{ t('callsign') }}</label>
                    <input type="text" name="callsign" value="{{ callsign }}" 
                           placeholder="{{ t('callsign_placeholder') }}" 
                           style="text-transform: uppercase;">
                </div>
                
                <div class="form-group">
                    <label>{{ t('grid_square') }} 
                        <a href="https://www.levinecentral.com/ham/grid_square.php" target="_blank" 
                           style="font-size: 0.85rem; color: #FFA500; margin-left: 8px;">
                            {{ "Find my grid" if lang == 'en' else "Trouver mon grid" }} ↗
                        </a>
                    </label>
                    <input type="text" name="grid" value="{{ config.get('grid', '') }}"
                           placeholder="{{ t('grid_placeholder') }}"
                           maxlength="6"
                           style="text-transform: uppercase;">
                </div>
                
                <div class="form-group">
                    <label>{{ t('winlink_password') }}
                        <a href="https://winlink.org/user" target="_blank" 
                           style="font-size: 0.85rem; color: #FFA500; margin-left: 8px;">
                            {{ "Create account / Reset password" if lang == 'en' else "Créer un compte / Réinitialiser" }} ↗
                        </a>
                    </label>
                    <div style="position: relative;">
                        <input type="password" name="password" id="password-field"
                               value="{{ config.get('winlinkPasswd', '') }}"
                               placeholder="{{ t('password_placeholder') }}"
                               style="padding-right: 40px;">
                    </div>
                    <label style="font-size: 0.85rem; margin-top: 8px; display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" id="show-password" style="width: auto; margin: 0;">
                        <span>{{ 'Show password' if lang == 'en' else 'Afficher le mot de passe' }}</span>
                    </label>
                </div>
            </div>
            
            <div class="buttons">
                <a href="{{ url_for('index') }}" class="btn btn-secondary">{{ t('back') }}</a>
                <button type="submit" class="btn btn-primary">{{ t('next') }}</button>
            </div>
        </form>
    </div>
    
    <script>
        document.getElementById('show-password').addEventListener('change', function() {
            const pwdField = document.getElementById('password-field');
            pwdField.type = this.checked ? 'text' : 'password';
        });
    </script>
</body>
</html>
''', css=CSS, t=t, config=load_user_config(), callsign=callsign, lang=session.get('lang', 'fr'))

@app.route('/radio', methods=['GET', 'POST'])
def radio_setup():
    """Step 2: Radio selection"""
    if request.method == 'POST':
        selected = request.form.get('radio')
        if selected:
            session['radio'] = selected
            set_active_radio(selected)  # Create the symlink!
        return redirect(url_for('radio_settings'))
    
    radios = get_radios()
    
    # Get currently selected radio - check session first, then active-radio symlink
    current_radio = session.get('radio', '')
    if not current_radio:
        active_radio_link = RADIOS_DIR / "active-radio.json"
        if active_radio_link.is_symlink():
            try:
                current_radio = active_radio_link.resolve().stem
            except:
                pass
    
    # Debug info
    debug_info = {
        'script_dir': str(SCRIPT_DIR),
        'et_base': str(ET_BASE),
        'radios_dir': str(RADIOS_DIR),
        'radios_dir_exists': RADIOS_DIR.exists(),
        'radios_count': len(radios),
        'current_radio': current_radio
    }
    if RADIOS_DIR.exists():
        debug_info['files_found'] = [f.name for f in RADIOS_DIR.iterdir()]
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('radio_setup') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('radio_setup') }}</h1>
            <div class="step-indicator">{{ t('step') }} 2 {{ t('of') }} 8</div>
        </div>
        
        <form method="POST">
            <div class="card">
                <h2>{{ t('select_radio') }}</h2>
                
                {% if radios %}
                <div style="max-height: 350px; overflow-y: auto; border: 1px solid #333; border-radius: 8px; padding: 5px;">
                    <div class="radio-list">
                        {% for radio in radios %}
                        <label class="radio-item {{ 'selected' if current_radio == radio.filename else '' }}" onclick="this.querySelector('input').checked=true; document.querySelectorAll('.radio-item').forEach(r=>r.classList.remove('selected')); this.classList.add('selected');">
                            <input type="radio" name="radio" value="{{ radio.filename }}" style="display:none;"
                                {{ 'checked' if current_radio == radio.filename else '' }}>
                            <div class="name">{{ radio.get('vendor', '') }} {{ radio.get('model', '') }}</div>
                        </label>
                        {% endfor %}
                    </div>
                </div>
                {% else %}
                <p style="color: #888; text-align: center; padding: 20px;">{{ t('no_radios') }}</p>
                {% endif %}
            </div>
            
            <div class="buttons">
                <a href="{{ url_for('user_setup') }}" class="btn btn-secondary">{{ t('back') }}</a>
                <button type="submit" class="btn btn-primary">{{ t('next') }}</button>
            </div>
        </form>
    </div>
</body>
</html>
''', css=CSS, t=t, radios=radios, current_radio=current_radio, debug_info=debug_info)

@app.route('/radio/settings')
def radio_settings():
    """Step 2b: Show radio settings"""
    radio_name = session.get('radio')
    radio = None
    saved_file = None
    
    if radio_name:
        radio_file = RADIOS_DIR / f"{radio_name}.json"
        if radio_file.exists():
            with open(radio_file) as f:
                radio = json.load(f)
            
            # Auto-save settings as MD file
            if radio and radio.get('notes'):
                vendor = radio.get('vendor', '')
                model = radio.get('model', '')
                notes = radio.get('notes', [])
                
                # Build MD content
                md_content = f"# {vendor} {model} - Radio Settings\n\n"
                md_content += "## Notes\n\n"
                
                if isinstance(notes, str):
                    md_content += f"{notes}\n"
                else:
                    for note in notes:
                        md_content += f"- {note}\n"
                
                md_content += f"\n---\n*Generated by EmComm-Tools - {time.strftime('%Y-%m-%d')}*\n"
                
                # Save to ~/Documents
                docs_dir = Path.home() / "Documents"
                docs_dir.mkdir(parents=True, exist_ok=True)
                
                safe_name = f"{vendor}-{model}".replace(' ', '-').replace('/', '-')
                md_file = docs_dir / f"radio-settings-{safe_name}.md"
                
                with open(md_file, 'w') as f:
                    f.write(md_content)
                
                saved_file = str(md_file)
                print(f"[RADIO] Saved settings to: {saved_file}")
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('radio_settings') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('radio_settings') }}</h1>
            <div class="step-indicator">{{ t('step') }} 2 {{ t('of') }} 8</div>
        </div>
        
        <div class="card">
            {% if radio %}
            <h2>{{ radio.get('vendor', '') }} {{ radio.get('model', '') }}</h2>
            
            {% if radio.get('notes') %}
            <div class="dest-info" style="margin-top: 15px;">
                <span class="label">{{ t('notes') }}:</span>
                <div class="notes-content" style="margin-top: 10px;">
                <span class="path">
                {% if radio.get('notes') is string %}
                    {{ radio.get('notes', '') }}
                {% else %}
                    {% for note in radio.get('notes', []) %}
                        {{ note }}<br>
                    {% endfor %}
                {% endif %}
                </span>
                </div>
            </div>
            
            {% if saved_file %}
            <div class="dest-info" style="margin-top: 15px;">
                <span class="label">💾 {{ 'Settings saved to:' if lang == 'en' else 'Paramètres sauvegardés dans:' }}</span><br>
                <span class="path">{{ saved_file }}</span>
            </div>
            {% endif %}
            
            {% else %}
            <p style="color: var(--text-secondary);">No configuration notes for this radio.</p>
            {% endif %}
            {% else %}
            <p style="color: var(--text-secondary); text-align: center; padding: 20px;">No radio selected</p>
            {% endif %}
        </div>
        
        <div class="buttons">
            <a href="{{ url_for('radio_setup') }}" class="btn btn-secondary">{{ t('back') }}</a>
            <a href="{{ url_for('internet_check') }}" class="btn btn-primary">{{ t('next') }}</a>
        </div>
    </div>
</body>
</html>
''', css=CSS, t=t, radio=radio, saved_file=saved_file, lang=session.get('lang', 'fr'))

def check_internet():
    """Check if internet is available"""
    import socket
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        pass
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3)
        return True
    except OSError:
        pass
    return False

@app.route('/internet')
def internet_check():
    """Step 3: Check internet before downloads"""
    has_internet = check_internet()
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ 'Internet Check' if lang == 'en' else 'Vérification Internet' }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ 'Download Maps & Files' if lang == 'en' else 'Télécharger cartes et fichiers' }}</h1>
            <div class="step-indicator">{{ t('step') }} 3 {{ t('of') }} 8</div>
        </div>
        
        <div class="card">
            {% if has_internet %}
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 3rem; margin-bottom: 15px;">🌐</div>
                <h2 style="color: #FFA500;">{{ 'Internet Connected' if lang == 'en' else 'Internet connecté' }}</h2>
                <p style="color: #ccc; margin-top: 10px;">
                    {{ 'You can now download offline maps and Wikipedia files.' if lang == 'en' else 'Vous pouvez maintenant télécharger les cartes et fichiers Wikipedia hors-ligne.' }}
                </p>
            </div>
            {% else %}
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 3rem; margin-bottom: 15px;">📡</div>
                <h2 style="color: #ff6b6b;">{{ 'No Internet Connection' if lang == 'en' else 'Pas de connexion Internet' }}</h2>
                <p style="color: #ccc; margin-top: 10px;">
                    {{ 'Connect to the internet to download maps and files, or skip this step.' if lang == 'en' else 'Connectez-vous à Internet pour télécharger les cartes et fichiers, ou passez cette étape.' }}
                </p>
            </div>
            {% endif %}
        </div>
        
        <div class="buttons">
            <a href="{{ url_for('radio_settings') }}" class="btn btn-secondary">{{ t('back') }}</a>
            {% if has_internet %}
            <a href="{{ url_for('drive_setup') }}" class="btn btn-primary">{{ t('next') }}</a>
            {% else %}
            <a href="{{ url_for('complete') }}" class="btn btn-secondary">{{ t('skip') }} →</a>
            <a href="{{ url_for('internet_check') }}" class="btn btn-primary">{{ 'Retry' if lang == 'en' else 'Réessayer' }}</a>
            {% endif %}
        </div>
    </div>
</body>
</html>
''', css=CSS, t=t, has_internet=has_internet, lang=session.get('lang', 'fr'))

@app.route('/drive', methods=['GET', 'POST'])
def drive_setup():
    """Step 4: Drive selection - BEFORE any downloads"""
    error_message = None
    
    if request.method == 'POST':
        drive_type = request.form.get('drive_type', 'local')
        session['drive_type'] = drive_type
        
        if drive_type == 'usb':
            usb_path = request.form.get('usb_path', '')
            if usb_path:
                # Double-check writability (belt and suspenders - JS should have validated)
                if not check_path_writable(usb_path):
                    error_message = t('usb_read_only')
                    drives = get_usb_drives()
                    return render_template_string(DRIVE_SETUP_TEMPLATE, 
                        css=CSS, t=t, drives=drives, error_message=error_message)
                
                session['usb_path'] = usb_path
                # Create directories on USB
                try:
                    usb = Path(usb_path)
                    (usb / "tilesets").mkdir(exist_ok=True)
                    (usb / "my-maps").mkdir(exist_ok=True)
                    (usb / "wikipedia").mkdir(exist_ok=True)
                except (PermissionError, OSError) as e:
                    print(f"[DRIVE] Error creating directories: {e}")
                    error_message = t('usb_read_only')
                    drives = get_usb_drives()
                    return render_template_string(DRIVE_SETUP_TEMPLATE,
                        css=CSS, t=t, drives=drives, error_message=error_message)
        
        return redirect(url_for('download_tiles'))
    
    drives = get_usb_drives()
    return render_template_string(DRIVE_SETUP_TEMPLATE, css=CSS, t=t, drives=drives, error_message=None)

# Template constant for drive setup page
DRIVE_SETUP_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('drive_setup') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
    <style>
        /* Additional styles for drive validation */
        .usb-status {
            margin-top: 15px;
            padding: 12px;
            border-radius: 6px;
            display: none;
        }
        .usb-status.checking {
            display: block;
            background: rgba(255, 165, 0, 0.1);
            border: 1px solid rgba(255, 165, 0, 0.3);
            color: #ffa500;
        }
        .usb-status.success {
            display: block;
            background: rgba(74, 222, 128, 0.1);
            border: 1px solid rgba(74, 222, 128, 0.3);
            color: #4ade80;
        }
        .usb-status.error {
            display: block;
            background: rgba(255, 100, 100, 0.1);
            border: 1px solid rgba(255, 100, 100, 0.3);
            color: #ff6b6b;
        }
        .radio-item.checking {
            opacity: 0.7;
            pointer-events: none;
        }
        .radio-item.validated {
            border-color: #4ade80 !important;
        }
        .radio-item.invalid {
            border-color: #ff6b6b !important;
            opacity: 0.6;
        }
        .drive-check-icon {
            float: right;
            font-size: 1.2rem;
        }
        /* Modal styles */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .modal-overlay.visible {
            display: flex;
        }
        .modal-content {
            background: #2a2a2a;
            border: 1px solid #404040;
            border-radius: 12px;
            max-width: 500px;
            width: 90%;
            padding: 25px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .modal-header h3 {
            color: #FFA500;
            margin: 0;
        }
        .modal-close {
            background: none;
            border: none;
            color: #888;
            font-size: 1.5rem;
            cursor: pointer;
        }
        .modal-close:hover {
            color: #fff;
        }
        .modal-body p {
            color: #ccc;
            margin-bottom: 15px;
            line-height: 1.5;
        }
        .modal-body .step-num {
            color: #FFA500;
            font-weight: bold;
        }
        .command-box {
            background: #1a1a1a;
            border: 1px solid #404040;
            border-radius: 6px;
            padding: 12px;
            margin: 15px 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }
        .command-box code {
            color: #4ade80;
            font-family: monospace;
            font-size: 0.9rem;
            word-break: break-all;
        }
        .command-box button {
            background: #404040;
            border: none;
            color: #ccc;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            white-space: nowrap;
        }
        .command-box button:hover {
            background: #505050;
        }
        .help-link {
            color: #FFA500;
            cursor: pointer;
            text-decoration: underline;
            margin-left: 10px;
            font-size: 0.9rem;
        }
        .help-link:hover {
            color: #ffb733;
        }
    </style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('drive_setup') }}</h1>
            <div class="step-indicator">{{ t('step') }} 4 {{ t('of') }} 8</div>
        </div>
        
        {% if error_message %}
        <div style="background: rgba(255, 100, 100, 0.15); border: 1px solid rgba(255, 100, 100, 0.4); border-radius: 8px; padding: 15px; margin-bottom: 20px;">
            <strong style="color: #ff6b6b;">⚠️ {{ t('error') }}</strong><br>
            <span style="color: #ffaaaa;">{{ error_message }}</span>
        </div>
        {% endif %}
        
        <form method="POST" id="driveForm">
            <input type="hidden" name="usb_path" id="usb_path_input" value="">
            
            <div class="card">
                <h2>{{ t('select_drive') }}</h2>
                
                <div class="drive-options">
                    <div class="drive-option" onclick="selectDriveType('local')">
                        <input type="radio" name="drive_type" value="local" id="drive-local" style="display:none;" checked>
                        <div class="icon">💾</div>
                        <div class="title">{{ t('local_drive') }}</div>
                        <div class="desc">{{ t('local_desc') }}</div>
                    </div>
                    
                    <div class="drive-option" onclick="selectDriveType('usb')">
                        <input type="radio" name="drive_type" value="usb" id="drive-usb" style="display:none;">
                        <div class="icon">🔌</div>
                        <div class="title">{{ t('usb_drive') }}</div>
                        <div class="desc">{{ t('usb_desc') }}</div>
                    </div>
                </div>
                
                <div class="usb-select" id="usb-select">
                    <label>{{ t('select_usb') }}</label>
                    {% if drives %}
                    <div class="radio-list" style="margin-top: 10px;" id="usb-drive-list">
                        {% for drive in drives %}
                        <label class="radio-item" id="drive-item-{{ loop.index }}" 
                               onclick="selectUsbDrive('{{ drive.path }}', this);">
                            <span class="drive-check-icon" id="icon-{{ loop.index }}"></span>
                            <div class="name">🔌 {{ drive.name }}</div>
                            <div class="details">{{ drive.path }} {% if drive.size %}({{ drive.size }}){% endif %}</div>
                        </label>
                        {% endfor %}
                    </div>
                    
                    <div class="usb-status" id="usb-status">
                        <span id="usb-status-text"></span>
                        <span class="help-link" id="help-link" onclick="showHelpModal()" style="display:none;">{{ t('usb_how_to_fix') }}</span>
                    </div>
                    {% else %}
                    <p style="color: #ff6b6b; margin-top: 10px;">{{ t('no_usb') }}</p>
                    {% endif %}
                </div>
            </div>
            
            <div class="buttons">
                <a href="{{ url_for('internet_check') }}" class="btn btn-secondary">{{ t('back') }}</a>
                <button type="submit" class="btn btn-primary" id="next-btn">{{ t('next') }}</button>
            </div>
        </form>
    </div>
    
    <!-- Help Modal -->
    <div class="modal-overlay" id="help-modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>🔧 {{ t('usb_help_title') }}</h3>
                <button class="modal-close" onclick="hideHelpModal()">✕</button>
            </div>
            <div class="modal-body">
                <p><span class="step-num">1.</span> {{ t('usb_help_step1') }}</p>
                <p><span class="step-num">2.</span> {{ t('usb_help_step2') }}</p>
                <div class="command-box">
                    <code id="remount-command">sudo mount -o remount,rw /path/to/drive</code>
                    <button onclick="copyCommand()">📋 {{ t('usb_help_copy') }}</button>
                </div>
                <p><span class="step-num">3.</span> {{ t('usb_help_step3') }}</p>
            </div>
            <div style="text-align: center; margin-top: 20px;">
                <button class="btn btn-secondary" onclick="hideHelpModal()">{{ t('usb_help_close') }}</button>
            </div>
        </div>
    </div>
    
    <script>
        let currentDriveType = 'local';
        let usbValidated = false;
        let validatedUsbPath = '';
        
        // Translations from server
        const MESSAGES = {
            checking: "{{ t('usb_checking') }}",
            success: "{{ t('usb_write_ok') }}",
            error: "{{ t('usb_read_only') }}",
            copied: "{{ t('usb_help_copied') }}"
        };
        
        let lastCheckedPath = '';
        
        function showHelpModal() {
            // Update command with actual path
            const cmd = 'sudo mount -o remount,rw ' + lastCheckedPath;
            document.getElementById('remount-command').textContent = cmd;
            document.getElementById('help-modal').classList.add('visible');
        }
        
        function hideHelpModal() {
            document.getElementById('help-modal').classList.remove('visible');
        }
        
        function copyCommand() {
            const cmd = document.getElementById('remount-command').textContent;
            navigator.clipboard.writeText(cmd).then(() => {
                const btn = event.target;
                const originalText = btn.textContent;
                btn.textContent = '✓ ' + MESSAGES.copied;
                setTimeout(() => { btn.textContent = originalText; }, 2000);
            });
        }
        
        function selectDriveType(type) {
            currentDriveType = type;
            
            // Update UI
            document.querySelectorAll('.drive-option').forEach(d => d.classList.remove('selected'));
            document.getElementById('drive-' + type).checked = true;
            document.getElementById('drive-' + type).closest('.drive-option').classList.add('selected');
            document.getElementById('usb-select').classList.toggle('visible', type === 'usb');
            
            // Update button state
            updateNextButton();
        }
        
        async function selectUsbDrive(path, element) {
            // Store path for help modal
            lastCheckedPath = path;
            
            // Hide help link initially
            document.getElementById('help-link').style.display = 'none';
            
            // Reset all drive items
            document.querySelectorAll('.radio-item').forEach(item => {
                item.classList.remove('selected', 'checking', 'validated', 'invalid');
            });
            document.querySelectorAll('.drive-check-icon').forEach(icon => {
                icon.textContent = '';
            });
            
            // Mark as checking
            element.classList.add('selected', 'checking');
            const iconEl = element.querySelector('.drive-check-icon');
            iconEl.textContent = '⏳';
            
            // Show checking status
            const statusEl = document.getElementById('usb-status');
            const statusText = document.getElementById('usb-status-text');
            statusEl.className = 'usb-status checking';
            statusText.textContent = '⏳ ' + MESSAGES.checking;
            
            // Reset validation state
            usbValidated = false;
            validatedUsbPath = '';
            document.getElementById('usb_path_input').value = '';
            updateNextButton();
            
            try {
                const response = await fetch('/api/drive/check', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({path: path})
                });
                const result = await response.json();
                
                element.classList.remove('checking');
                
                if (result.writable) {
                    // Success - drive is writable
                    element.classList.add('validated');
                    iconEl.textContent = '✓';
                    iconEl.style.color = '#4ade80';
                    
                    statusEl.className = 'usb-status success';
                    statusText.textContent = '✓ ' + MESSAGES.success;
                    
                    usbValidated = true;
                    validatedUsbPath = path;
                    document.getElementById('usb_path_input').value = path;
                } else {
                    // Error - drive is read-only
                    element.classList.add('invalid');
                    element.classList.remove('selected');
                    iconEl.textContent = '🔒';
                    iconEl.style.color = '#ff6b6b';
                    
                    statusEl.className = 'usb-status error';
                    statusText.textContent = '🔒 ' + (result.error || MESSAGES.error);
                    
                    // Show help link
                    document.getElementById('help-link').style.display = 'inline';
                    
                    usbValidated = false;
                    validatedUsbPath = '';
                }
            } catch (e) {
                // Network error
                element.classList.remove('checking');
                element.classList.add('invalid');
                element.classList.remove('selected');
                iconEl.textContent = '⚠️';
                
                statusEl.className = 'usb-status error';
                statusText.textContent = '⚠️ Error checking drive: ' + e.message;
                
                usbValidated = false;
                validatedUsbPath = '';
            }
            
            updateNextButton();
        }
        
        function updateNextButton() {
            const nextBtn = document.getElementById('next-btn');
            
            if (currentDriveType === 'local') {
                // Local drive always OK
                nextBtn.disabled = false;
                nextBtn.style.opacity = '1';
            } else {
                // USB requires validation
                if (usbValidated && validatedUsbPath) {
                    nextBtn.disabled = false;
                    nextBtn.style.opacity = '1';
                } else {
                    nextBtn.disabled = true;
                    nextBtn.style.opacity = '0.5';
                }
            }
        }
        
        // Initialize
        selectDriveType('local');
    </script>
</body>
</html>
'''

@app.route('/download/tiles', methods=['GET', 'POST'])
def download_tiles():
    """Step 4: Download map tiles (ALL - US, Canada, World)"""
    if request.method == 'POST':
        return redirect(url_for('download_osm'))
    
    # Determine destination
    if session.get('drive_type') == 'usb':
        dest_path = Path(session.get('usb_path', '')) / "tilesets"
    else:
        dest_path = TILESET_DIR
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('download_tiles') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('download_tiles') }}</h1>
            <div class="step-indicator">{{ t('step') }} 5 {{ t('of') }} 8</div>
        </div>
        
        <div class="dest-info">
            <span class="label">Destination:</span>
            <span class="path">{{ dest_path }}</span>
        </div>
        
        <div class="card">
            <h2>{{ t('tiles_desc') }}</h2>
            
            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-fill" id="progress" style="width: 0%"></div>
                </div>
                <div class="progress-text" id="progress-text">Preparing...</div>
            </div>
            
            <div class="status-list" id="status-list">
                {% for file in files %}
                <div class="status-item pending" id="status-{{ loop.index }}">
                    <span class="icon">⏳</span>
                    <span>{{ file }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="buttons">
            <a href="{{ url_for('drive_setup') }}" class="btn btn-secondary" id="back-btn">{{ t('back') }}</a>
            <button class="btn btn-primary" id="next-btn" disabled>{{ t('next') }}</button>
        </div>
    </div>
    
    <script>
        const files = {{ files | tojson }};
        let currentIndex = 0;
        
        async function downloadFile(index) {
            if (index >= files.length) {
                document.getElementById('progress-text').textContent = '{{ t("complete") }}!';
                document.getElementById('next-btn').disabled = false;
                document.getElementById('next-btn').onclick = () => window.location.href = '{{ url_for("download_osm") }}';
                return;
            }
            
            const file = files[index];
            const statusEl = document.getElementById('status-' + (index + 1));
            
            statusEl.className = 'status-item active';
            statusEl.querySelector('.icon').innerHTML = '<span class="spinner"></span>';
            document.getElementById('progress-text').textContent = '{{ t("downloading") }}: ' + file;
            
            try {
                const response = await fetch('/api/download/tile', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({file: file})
                });
                
                const result = await response.json();
                
                if (result.success || result.skipped) {
                    statusEl.className = 'status-item done';
                    statusEl.querySelector('.icon').textContent = '✓';
                    if (result.skipped) {
                        statusEl.innerHTML += ' <span style="color:#888;font-size:0.8rem">(exists)</span>';
                    }
                } else {
                    statusEl.className = 'status-item error';
                    statusEl.querySelector('.icon').textContent = '✗';
                    const errorMsg = result.error || 'Download failed';
                    statusEl.innerHTML += ' <span style="color:#ff6b6b;font-size:0.8rem">(' + errorMsg + ')</span>';
                    console.error('Tile download error:', errorMsg);
                }
            } catch (e) {
                statusEl.className = 'status-item error';
                statusEl.querySelector('.icon').textContent = '✗';
                statusEl.innerHTML += ' <span style="color:#ff6b6b;font-size:0.8rem">(Network: ' + e.message + ')</span>';
            }
            
            const progress = ((index + 1) / files.length) * 100;
            document.getElementById('progress').style.width = progress + '%';
            
            downloadFile(index + 1);
        }
        
        // Start downloads
        downloadFile(0);
    </script>
</body>
</html>
''', css=CSS, t=t, files=TILE_FILES, dest_path=dest_path)

@app.route('/api/download/tile', methods=['POST'])
def api_download_tile():
    """API endpoint to download a single tile file"""
    data = request.json
    filename = data.get('file')
    
    if not filename or filename not in TILE_FILES:
        return jsonify({'success': False, 'error': 'Invalid file'})
    
    # Determine destination
    if session.get('drive_type') == 'usb':
        dest_dir = Path(session.get('usb_path', '')) / "tilesets"
    else:
        dest_dir = TILESET_DIR
    
    # Create directory
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / filename
    
    # Skip if exists
    if dest_file.exists():
        print(f"Tile already exists: {dest_file}")
        return jsonify({'success': True, 'skipped': True, 'message': 'File already exists'})
    
    # Download
    url = f"{TILE_BASE_URL}/{TILE_RELEASE}/{filename}"
    
    try:
        print(f"Downloading tile: {url} -> {dest_file}")
        subprocess.run([
            'curl', '-L', '-f', '-o', str(dest_file), url
        ], check=True, capture_output=True)
        return jsonify({'success': True})
    except subprocess.CalledProcessError as e:
        # Human-friendly error messages
        error_messages = {
            6: 'No internet connection',
            7: 'Server not responding',
            22: 'File not found on server',
            23: 'Disk full - free up space',
            28: 'Connection timeout',
            56: 'Network error - try again',
        }
        if e.returncode in error_messages:
            error_msg = error_messages[e.returncode]
        else:
            error_msg = f'Download failed (error {e.returncode})'
        print(f"[TILE] Download error: {error_msg}")
        return jsonify({'success': False, 'error': error_msg})

@app.route('/download/osm', methods=['GET', 'POST'])
def download_osm():
    """Step 5: Download OSM maps - supports multiple selections"""
    if request.method == 'POST':
        # Get all selected regions (multiple)
        selected = request.form.getlist('regions')
        
        if selected:
            session['osm_regions'] = selected  # List of "country:region" pairs
            return redirect(url_for('download_osm_progress'))
        
        return redirect(url_for('download_wiki'))
    
    # Determine destination and find existing files
    if session.get('drive_type') == 'usb':
        dest_path = Path(session.get('usb_path', '')) / "my-maps"
    else:
        dest_path = PBF_MAP_DIR
    
    # Get list of existing .pbf files
    existing_files = []
    if dest_path.exists():
        existing_files = [f.stem.replace('-latest.osm', '') for f in dest_path.glob("*.pbf")]
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('download_osm') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('download_osm') }}</h1>
            <div class="step-indicator">{{ t('step') }} 6 {{ t('of') }} 8</div>
        </div>
        
        <div class="dest-info">
            <span class="label">Destination:</span>
            <span class="path">{{ dest_path }}</span>
        </div>
        
        <form method="POST" id="osmForm">
            <div class="card">
                <h2>🇨🇦 {{ t('select_province') }}</h2>
                <div class="region-list" id="canada-list">
                    <p style="color: #888; text-align: center;"><span class="spinner"></span> Loading...</p>
                </div>
                
                <h2 style="margin-top: 25px;">🇺🇸 {{ t('select_state') }}</h2>
                <div class="region-list" id="usa-list">
                    <p style="color: #888; text-align: center;"><span class="spinner"></span> Loading...</p>
                </div>
            </div>
            
            <div class="buttons">
                <a href="{{ url_for('download_tiles') }}" class="btn btn-secondary">{{ t('back') }}</a>
                <button type="button" class="btn btn-secondary" onclick="window.location.href='{{ url_for('download_wiki') }}'">{{ t('skip') }}</button>
                <button type="submit" class="btn btn-primary" id="download-btn">{{ t('next') }}</button>
            </div>
        </form>
    </div>
    
    <script>
        const existingFiles = {{ existing_files | tojson }};
        
        async function loadRegions(country, listId) {
            const listEl = document.getElementById(listId);
            
            try {
                const response = await fetch('/api/osm/regions/' + country);
                const data = await response.json();
                renderRegions(data.regions || [], country, listEl);
            } catch (e) {
                listEl.innerHTML = '<p style="color: #ff6b6b;">Error loading</p>';
            }
        }
        
        function renderRegions(regions, country, listEl) {
            listEl.innerHTML = '';
            
            regions.forEach(r => {
                const exists = existingFiles.includes(r.id);
                const label = document.createElement('label');
                label.className = 'wiki-item' + (exists ? ' exists' : '');
                const existsTag = exists ? '<span style="color:#FFA500;font-size:0.8rem;margin-left:8px;">✓ Downloaded</span>' : '';
                label.innerHTML = `
                    <input type="checkbox" name="regions" value="${country}:${r.id}" 
                           ${exists ? 'checked disabled' : ''}>
                    <span>${r.name}${existsTag}</span>
                `;
                label.onclick = updateButton;
                listEl.appendChild(label);
            });
        }
        
        function updateButton() {
            setTimeout(() => {
                // Count new selections (checked but not disabled)
                const newSelections = document.querySelectorAll('input[name="regions"]:checked:not(:disabled)');
                // Always enable the button - if no new selections, it will skip downloads
                document.getElementById('download-btn').disabled = false;
            }, 10);
        }
        
        // Load both countries on start
        loadRegions('canada', 'canada-list');
        loadRegions('usa', 'usa-list');
    </script>
</body>
</html>
''', css=CSS, t=t, dest_path=dest_path, existing_files=existing_files)

@app.route('/api/drive/check', methods=['POST'])
def api_check_drive():
    """Test if a drive path is writable - called when user selects a USB drive"""
    data = request.json
    path = data.get('path', '')
    
    if not path:
        return jsonify({'writable': False, 'error': 'No path specified'})
    
    # Test write access
    writable = check_path_writable(path)
    
    if writable:
        return jsonify({'writable': True, 'error': None})
    else:
        # Return bilingual error based on session language
        lang = session.get('lang', 'fr')
        if lang == 'en':
            error_msg = 'This drive is read-only or write-protected. Please unlock it or choose another drive.'
        else:
            error_msg = 'Ce disque est en lecture seule ou protégé en écriture. Veuillez le déverrouiller ou choisir un autre disque.'
        return jsonify({'writable': False, 'error': error_msg})

@app.route('/api/debug/radios')
def api_debug_radios():
    """Debug endpoint to check radio loading"""
    debug_info = {
        'radios_dir': str(RADIOS_DIR),
        'radios_dir_exists': RADIOS_DIR.exists(),
        'home_radios_dir': str(Path.home() / ".config/emcomm-tools/radios.d"),
        'home_radios_exists': (Path.home() / ".config/emcomm-tools/radios.d").exists(),
        'radios_found': [],
        'files_in_dir': []
    }
    
    if RADIOS_DIR.exists():
        debug_info['files_in_dir'] = [f.name for f in RADIOS_DIR.iterdir()]
    
    radios = get_radios()
    debug_info['radios_found'] = [{'filename': r.get('filename'), 'model': r.get('model')} for r in radios]
    
    return jsonify(debug_info)

@app.route('/api/osm/regions/<country>')
def api_osm_regions(country):
    """Get list of regions for a country"""
    regions = []
    
    if country == 'canada':
        url = OSM_CANADA_URL
        base = "canada"
    else:
        url = OSM_USA_URL
        base = "us"
    
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=30) as response:
            html = response.read().decode('utf-8')
        
        # Parse provinces/states from HTML - same logic as bash script
        import re
        # Match href="xxx.osm.pbf" and extract xxx
        pattern = r'href="([^"]+\.osm\.pbf)"'
        matches = re.findall(pattern, html)
        
        for match in matches:
            # Skip country-level file
            if f"{base}-latest" in match:
                continue
            # Extract just the filename (remove any path and -latest.osm.pbf)
            filename = match.split('/')[-1]  # Get just the filename, not path
            name = filename.replace('-latest.osm.pbf', '')
            display = name.replace('-', ' ').title()
            regions.append({'id': name, 'name': display})
        
        # Sort and dedupe
        seen = set()
        unique_regions = []
        for r in sorted(regions, key=lambda x: x['name']):
            if r['id'] not in seen:
                seen.add(r['id'])
                unique_regions.append(r)
        
        return jsonify({'regions': unique_regions})
    except Exception as e:
        return jsonify({'error': str(e), 'regions': []})

@app.route('/download/osm/progress')
def download_osm_progress():
    """OSM download progress page - handles multiple regions"""
    regions = session.get('osm_regions', [])  # List of "country:region" pairs
    
    if session.get('drive_type') == 'usb':
        dest_path = Path(session.get('usb_path', '')) / "my-maps"
    else:
        dest_path = PBF_MAP_DIR
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('download_osm') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('download_osm') }}</h1>
            <div class="step-indicator">{{ t('step') }} 6 {{ t('of') }} 8</div>
        </div>
        
        <div class="card">
            <h2>{{ t('downloading') }}</h2>
            
            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-fill" id="progress" style="width: 0%"></div>
                </div>
                <div class="progress-text" id="progress-text">Starting...</div>
            </div>
            
            <div class="status-list" id="status-list">
                {% for item in regions %}
                <div class="status-item pending" id="status-{{ loop.index }}">
                    <span class="icon">⏳</span>
                    <span>{{ item.split(':')[1].replace('-', ' ').title() }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="buttons">
            <button class="btn btn-primary" id="next-btn" disabled>{{ t('next') }}</button>
        </div>
    </div>
    
    <script>
        const regions = {{ regions | tojson }};
        let currentIndex = 0;
        
        async function downloadRegion(index) {
            if (index >= regions.length) {
                document.getElementById('progress-text').textContent = '{{ t("complete") }}!';
                document.getElementById('next-btn').disabled = false;
                document.getElementById('next-btn').onclick = () => window.location.href = '{{ url_for("download_wiki") }}';
                return;
            }
            
            const item = regions[index];
            const [country, region] = item.split(':');
            const statusEl = document.getElementById('status-' + (index + 1));
            
            statusEl.className = 'status-item active';
            statusEl.querySelector('.icon').innerHTML = '<span class="spinner"></span>';
            document.getElementById('progress-text').textContent = '{{ t("downloading") }}: ' + region.replace(/-/g, ' ');
            
            try {
                const response = await fetch('/api/download/osm', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({region: region, country: country})
                });
                
                const result = await response.json();
                
                if (result.success || result.skipped) {
                    statusEl.className = 'status-item done';
                    statusEl.querySelector('.icon').textContent = '✓';
                    if (result.skipped) {
                        statusEl.innerHTML += ' <span style="color:#888;font-size:0.8rem">(exists)</span>';
                    }
                } else {
                    statusEl.className = 'status-item error';
                    statusEl.querySelector('.icon').textContent = '✗';
                    const errorMsg = result.error || 'Download failed';
                    statusEl.innerHTML += ' <span style="color:#ff6b6b;font-size:0.8rem">(' + errorMsg + ')</span>';
                    console.error('OSM download error:', errorMsg);
                }
            } catch (e) {
                statusEl.className = 'status-item error';
                statusEl.querySelector('.icon').textContent = '✗';
                statusEl.innerHTML += ' <span style="color:#ff6b6b;font-size:0.8rem">(Network: ' + e.message + ')</span>';
            }
            
            const progress = ((index + 1) / regions.length) * 100;
            document.getElementById('progress').style.width = progress + '%';
            
            downloadRegion(index + 1);
        }
        
        // Start downloads
        downloadRegion(0);
    </script>
</body>
</html>
''', css=CSS, t=t, regions=regions)

@app.route('/api/download/osm', methods=['POST'])
def api_download_osm():
    """Download OSM file and convert for Navit"""
    data = request.json
    region = data.get('region')
    country = data.get('country', 'canada')
    
    if not region:
        return jsonify({'success': False, 'error': 'No region selected'})
    
    # Determine paths
    if session.get('drive_type') == 'usb':
        usb_path = session.get('usb_path', '')
        if not usb_path:
            return jsonify({'success': False, 'error': 'USB path not set'})
        dest_dir = Path(usb_path) / "my-maps"
    else:
        dest_dir = PBF_MAP_DIR
    
    # Create directory
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Cannot create directory: {e}'})
    
    # Build URL and filename
    # Geofabrik structure: http://download.geofabrik.de/north-america/canada/quebec-latest.osm.pbf
    #                  or: http://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf
    if country == 'canada':
        url = f"{OSM_BASE_CANADA}/{region}-latest.osm.pbf"
    else:
        url = f"{OSM_BASE_USA}/{region}-latest.osm.pbf"
    
    filename = f"{region}-latest.osm.pbf"
    dest_file = dest_dir / filename
    
    print(f"[OSM] Country: {country}, Region: {region}")
    print(f"[OSM] URL: {url}")
    print(f"[OSM] Dest: {dest_file}")
    
    # Check if file already exists
    if dest_file.exists():
        print(f"[OSM] File already exists: {dest_file}")
        return jsonify({'success': True, 'skipped': True, 'message': 'File already exists'})
    
    try:
        print(f"[OSM] Downloading: {url}")
        
        # Download with progress output
        result = subprocess.run([
            'curl', '-L', '-f', '--create-dirs', '-o', str(dest_file), url
        ], capture_output=True, timeout=1800)  # 30 min timeout for large files
        
        if result.returncode != 0:
            stderr = result.stderr.decode() if result.stderr else ''
            # Parse curl error for human-friendly messages
            error_messages = {
                6: 'No internet connection - check your network',
                7: 'Server not responding - try again later',
                22: 'File not found on server',
                23: 'Disk full or write error - free up space',
                28: 'Download too slow - connection timeout',
                35: 'SSL/TLS connection failed',
                52: 'Server returned empty response',
                56: 'Network error during download - try again',
            }
            if 'Failed to open' in stderr or 'No such file' in stderr:
                error_msg = 'Cannot create file - check drive permissions'
            elif result.returncode in error_messages:
                error_msg = error_messages[result.returncode]
            else:
                error_msg = f'Download failed (error {result.returncode})'
            
            print(f"[OSM] Download failed: {error_msg}")
            print(f"[OSM] stderr: {stderr}")
            
            # Clean up partial file
            if dest_file.exists():
                dest_file.unlink()
            return jsonify({'success': False, 'error': error_msg})
        
        # Verify file was downloaded
        if not dest_file.exists() or dest_file.stat().st_size < 1000:
            if dest_file.exists():
                dest_file.unlink()
            return jsonify({'success': False, 'error': 'Download incomplete'})
        
        print(f"[OSM] Download complete: {dest_file.stat().st_size} bytes")
        
        # Note: Navit conversion is handled separately by et-convert-navit-maps.sh
        # launched from the complete page
        
        return jsonify({'success': True})
    except subprocess.TimeoutExpired:
        # Clean up partial file
        if dest_file.exists():
            dest_file.unlink()
        return jsonify({'success': False, 'error': 'Download timed out (30 min limit)'})
    except Exception as e:
        print(f"[OSM] Exception: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download/wiki', methods=['GET', 'POST'])
def download_wiki():
    """Step 6: Download Wikipedia ZIM files"""
    if request.method == 'POST':
        selected = request.form.getlist('wiki_files')
        if selected:
            session['wiki_files'] = selected
            return redirect(url_for('download_wiki_progress'))
        return redirect(url_for('complete'))
    
    # Determine destination
    if session.get('drive_type') == 'usb':
        dest_path = Path(session.get('usb_path', '')) / "wikipedia"
    else:
        dest_path = ZIM_DIR
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('download_wiki') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('download_wiki') }}</h1>
            <div class="step-indicator">{{ t('step') }} 7 {{ t('of') }} 8</div>
        </div>
        
        <div class="dest-info">
            <span class="label">Destination:</span>
            <span class="path">{{ dest_path }}</span>
        </div>
        
        <form method="POST" id="wiki-form">
            <div class="card">
                <h2>{{ t('wiki_desc') }}</h2>
                
                <div class="tabs">
                    <div class="tab active" data-lang="en" onclick="filterWiki('en')">🇬🇧 {{ t('english') }}</div>
                    <div class="tab" data-lang="fr" onclick="filterWiki('fr')">🇫🇷 {{ t('french') }}</div>
                </div>
                
                <!-- Hidden container for all checkboxes (both languages) -->
                <div id="all-selections" style="display:none;"></div>
                
                <div class="wiki-list" id="wiki-list">
                    <p style="color: #888; text-align: center;"><span class="spinner"></span> Loading...</p>
                </div>
            </div>
            
            <div class="buttons">
                <a href="{{ url_for('download_osm') }}" class="btn btn-secondary">{{ t('back') }}</a>
                <button type="button" class="btn btn-secondary" onclick="window.location.href='{{ url_for('complete') }}'">{{ t('skip') }}</button>
                <button type="submit" class="btn btn-primary" id="download-btn">{{ t('next') }}</button>
            </div>
        </form>
    </div>
    
    <script>
        let wikiFiles = {en: [], fr: []};
        let currentLang = 'en';
        // Store user selections separately from existing files
        let userSelections = {en: new Set(), fr: new Set()};
        
        async function loadWikiFiles() {
            try {
                const response = await fetch('/api/wiki/files');
                const data = await response.json();
                wikiFiles = data.files || {en: [], fr: []};
                renderWikiFiles('en');
            } catch (e) {
                document.getElementById('wiki-list').innerHTML = '<p style="color: #ff6b6b;">Error loading files</p>';
            }
        }
        
        function saveCurrentSelections() {
            // Save current tab's selections before switching
            const checkboxes = document.querySelectorAll('#wiki-list input[type="checkbox"]:not(:disabled)');
            userSelections[currentLang].clear();
            checkboxes.forEach(cb => {
                if (cb.checked) {
                    userSelections[currentLang].add(cb.value);
                }
            });
        }
        
        function renderWikiFiles(lang) {
            const listEl = document.getElementById('wiki-list');
            const allSelectionsEl = document.getElementById('all-selections');
            listEl.innerHTML = '';
            
            wikiFiles[lang].forEach(file => {
                const label = document.createElement('label');
                label.className = 'wiki-item' + (file.exists ? ' exists' : '');
                const existsTag = file.exists ? '<span style="color:#FFA500;font-size:0.8rem;margin-left:8px;">✓ Downloaded</span>' : '';
                
                // Check if user previously selected this file
                const isSelected = userSelections[lang].has(file.name);
                
                label.innerHTML = `
                    <input type="checkbox" name="wiki_files" value="${file.name}" 
                           ${file.exists ? 'checked disabled' : (isSelected ? 'checked' : '')}>
                    <span>${file.display} (${file.size})${existsTag}</span>
                `;
                listEl.appendChild(label);
            });
            
            if (wikiFiles[lang].length === 0) {
                listEl.innerHTML = '<p style="color: #888; text-align: center;">No files found</p>';
            }
            
            // Also update hidden selections from other language so form submits all
            updateHiddenSelections();
        }
        
        function updateHiddenSelections() {
            // Create hidden inputs for selections from the OTHER language tab
            const allSelectionsEl = document.getElementById('all-selections');
            allSelectionsEl.innerHTML = '';
            
            // Add hidden inputs for selections not currently visible
            Object.keys(userSelections).forEach(lang => {
                if (lang !== currentLang) {
                    userSelections[lang].forEach(filename => {
                        const hidden = document.createElement('input');
                        hidden.type = 'hidden';
                        hidden.name = 'wiki_files';
                        hidden.value = filename;
                        allSelectionsEl.appendChild(hidden);
                    });
                }
            });
        }
        
        function filterWiki(lang) {
            // Save selections from current tab before switching
            saveCurrentSelections();
            
            // Switch to new tab
            currentLang = lang;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelector(`.tab[data-lang="${lang}"]`).classList.add('active');
            renderWikiFiles(lang);
        }
        
        // Save selections before form submit
        document.getElementById('wiki-form').addEventListener('submit', function(e) {
            saveCurrentSelections();
            updateHiddenSelections();
        });
        
        loadWikiFiles();
    </script>
</body>
</html>
''', css=CSS, t=t, dest_path=dest_path)

@app.route('/api/wiki/files')
def api_wiki_files():
    """Get list of Wikipedia ZIM files"""
    files = {'en': [], 'fr': []}
    
    # Get existing files from both USB and local
    existing_files = set()
    
    # Check USB path
    if session.get('drive_type') == 'usb':
        usb_wiki = Path(session.get('usb_path', '')) / "wikipedia"
        if usb_wiki.exists():
            for f in usb_wiki.glob("*.zim"):
                existing_files.add(f.name)
    
    # Check local path
    if ZIM_DIR.exists():
        for f in ZIM_DIR.glob("*.zim"):
            existing_files.add(f.name)
    
    print(f"[WIKI] Existing files: {existing_files}")
    
    try:
        import urllib.request
        with urllib.request.urlopen(KIWIX_URL, timeout=30) as response:
            html = response.read().decode('utf-8')
        
        import re
        # Format: <a href="filename.zim">filename.zim</a>    date    size
        # Example: <a href="wikipedia_en_100_2026-01.zim">wikipedia_en_100_2026-01.zim</a>   2026-01-15 10:23  319M
        # Size can be: 319M, 1.2G, 47M, 4.5G, etc.
        pattern = r'<a href="(wikipedia_(?:en|fr)[^"]+\.zim)">[^<]+</a>\s+[\d-]+\s+[\d:]+\s+([\d.]+[KMGT]?)'
        matches = re.findall(pattern, html)
        
        for filename, size in matches:
            # Determine language
            lang = 'en' if 'wikipedia_en' in filename else 'fr'
            
            # Display is the filename without .zim
            display = filename.replace('.zim', '')
            
            # Format size nicely - add B if no unit
            if size and not size[-1] in 'KMGT':
                size = size + 'B'
            
            # Check if file already exists
            exists = filename in existing_files
            
            files[lang].append({
                'name': filename,
                'display': display,
                'size': size,
                'exists': exists
            })
        
        # Sort by filename
        files['en'] = sorted(files['en'], key=lambda x: x['name'])
        files['fr'] = sorted(files['fr'], key=lambda x: x['name'])
        
    except Exception as e:
        print(f"Error fetching wiki files: {e}")
    
    return jsonify({'files': files})

@app.route('/download/wiki/progress')
def download_wiki_progress():
    """Wikipedia download progress"""
    files = session.get('wiki_files', [])
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('download_wiki') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('download_wiki') }}</h1>
            <div class="step-indicator">{{ t('step') }} 7 {{ t('of') }} 8</div>
        </div>
        
        <div class="card">
            <h2>{{ t('downloading') }}</h2>
            
            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-fill" id="progress" style="width: 0%"></div>
                </div>
                <div class="progress-text" id="progress-text">Starting...</div>
            </div>
            
            <div class="status-list" id="status-list">
                {% for file in files %}
                <div class="status-item pending" id="status-{{ loop.index }}">
                    <span class="icon">⏳</span>
                    <span>{{ file }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="buttons">
            <a href="{{ url_for('download_wiki') }}" class="btn btn-secondary" id="back-btn" style="display:none;">{{ t('back') }}</a>
            <button class="btn btn-primary" id="next-btn" disabled>{{ t('next') }}</button>
        </div>
    </div>
    
    <script>
        const files = {{ files | tojson }};
        let currentIndex = 0;
        
        async function downloadFile(index) {
            if (index >= files.length) {
                document.getElementById('progress-text').textContent = '{{ t("complete") }}!';
                document.getElementById('next-btn').disabled = false;
                document.getElementById('back-btn').style.display = 'inline-block';
                document.getElementById('next-btn').onclick = () => window.location.href = '{{ url_for("complete") }}';
                return;
            }
            
            const file = files[index];
            const statusEl = document.getElementById('status-' + (index + 1));
            
            statusEl.className = 'status-item active';
            statusEl.querySelector('.icon').innerHTML = '<span class="spinner"></span>';
            document.getElementById('progress-text').textContent = '{{ t("downloading") }}: ' + file;
            
            try {
                const response = await fetch('/api/download/wiki', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({file: file})
                });
                
                const result = await response.json();
                
                if (result.success) {
                    statusEl.className = 'status-item done';
                    statusEl.querySelector('.icon').textContent = '✓';
                    if (result.skipped) {
                        statusEl.innerHTML += ' <span style="color:#888;font-size:0.8rem">(exists)</span>';
                    }
                } else {
                    statusEl.className = 'status-item error';
                    statusEl.querySelector('.icon').textContent = '✗';
                    const errorMsg = result.error || 'Download failed';
                    statusEl.innerHTML += ' <span style="color:#ff6b6b;font-size:0.8rem">(' + errorMsg + ')</span>';
                    console.error('Wiki download error:', errorMsg);
                }
            } catch (e) {
                statusEl.className = 'status-item error';
                statusEl.querySelector('.icon').textContent = '✗';
                statusEl.innerHTML += ' <span style="color:#ff6b6b;font-size:0.8rem">(Network: ' + e.message + ')</span>';
            }
            
            const progress = ((index + 1) / files.length) * 100;
            document.getElementById('progress').style.width = progress + '%';
            
            downloadFile(index + 1);
        }
        
        downloadFile(0);
    </script>
</body>
</html>
''', css=CSS, t=t, files=files)

@app.route('/api/download/wiki', methods=['POST'])
def api_download_wiki():
    """Download a Wikipedia ZIM file"""
    data = request.json
    filename = data.get('file')
    
    if not filename:
        return jsonify({'success': False, 'error': 'No file specified'})
    
    # Determine destination
    if session.get('drive_type') == 'usb':
        dest_dir = Path(session.get('usb_path', '')) / "wikipedia"
    else:
        dest_dir = ZIM_DIR
    
    # Create directory
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / filename
    
    # Skip if exists
    if dest_file.exists():
        print(f"Wikipedia file already exists: {dest_file}")
        return jsonify({'success': True, 'skipped': True, 'message': 'File already exists'})
    
    url = f"{KIWIX_URL}/{filename}"
    
    try:
        print(f"Downloading Wikipedia: {url} -> {dest_file}")
        subprocess.run([
            'curl', '-L', '-f', '-o', str(dest_file), url
        ], check=True, capture_output=True, timeout=1800)  # 30 min timeout
        return jsonify({'success': True})
    except subprocess.CalledProcessError as e:
        # Human-friendly error messages
        error_messages = {
            6: 'No internet connection',
            7: 'Server not responding',
            22: 'File not found on server',
            23: 'Disk full - free up space',
            28: 'Connection timeout',
            56: 'Network error - try again',
        }
        if e.returncode in error_messages:
            error_msg = error_messages[e.returncode]
        else:
            error_msg = f'Download failed (error {e.returncode})'
        print(f"[WIKI] Download error: {error_msg}")
        return jsonify({'success': False, 'error': error_msg})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Download timed out (30 min limit)'})

@app.route('/complete')
def complete():
    """Step 7: Complete - create symlinks if USB was used"""
    symlink_results = []
    
    if session.get('drive_type') == 'usb':
        symlink_results = create_symlinks()
    
    # Check if OSM maps were downloaded (user may need Navit conversion)
    has_osm_maps = bool(session.get('osm_regions'))
    drive_type = session.get('drive_type', 'local')
    usb_path = session.get('usb_path', '')
    
    # Mark first boot as complete
    firstboot_flag = Path.home() / ".config" / "emcomm-tools" / ".firstboot-complete"
    firstboot_flag.parent.mkdir(parents=True, exist_ok=True)
    firstboot_flag.touch()
    
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ t('setup_complete') }} - EmComm-Tools</title>
    <style>{{ css }}</style>
</head>
<body>
    <div class="close-btn-wrapper" style="display:none;">
        <button onclick="fetch('/api/quit', {method: 'POST'});" style="background: none; border: none; color: #888; font-size: 1.2rem; cursor: pointer;">✕</button>
    </div>
    <div class="container">
        <div class="header">
            <h1>{{ t('setup_complete') }}</h1>
            <div class="step-indicator">{{ t('step') }} 8 {{ t('of') }} 8</div>
        </div>
        
        <div class="card" style="text-align: center;">
            <div class="success-icon">✓</div>
            <h2>{{ t('complete_msg') }}</h2>
            
            {% if symlinks %}
            <div style="margin-top: 20px; text-align: left;">
                <h3 style="color: #FFA500; margin-bottom: 10px;">{{ t('creating_symlinks') }}</h3>
                <div class="status-list">
                    {% for link in symlinks %}
                    <div class="status-item done">
                        <span class="icon">✓</span>
                        <span style="font-size: 0.8rem; font-family: monospace;">{{ link }}</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
            
            {% if has_osm_maps %}
            <div style="margin-top: 20px; background: rgba(255, 200, 0, 0.1); border: 1px solid rgba(255, 200, 0, 0.3); border-radius: 8px; padding: 15px; text-align: left;">
                <strong style="color: #ffc800;">🗺️ {{ 'Navit Maps (Optional)' if lang == 'en' else 'Cartes Navit (Optionnel)' }}</strong><br><br>
                <span style="font-size: 0.9rem; color: #ccc;">
                    {% if lang == 'en' %}
                    To use your maps with Navit (GPS navigation), open a terminal and run:<br><br>
                    <code style="background: rgba(0,0,0,0.3); padding: 8px; display: block; border-radius: 4px; margin: 10px 0;">et-navit-maps</code>
                    This may take several minutes per map.
                    {% else %}
                    Pour utiliser vos cartes avec Navit (navigation GPS), ouvrez un terminal et exécutez:<br><br>
                    <code style="background: rgba(0,0,0,0.3); padding: 8px; display: block; border-radius: 4px; margin: 10px 0;">et-navit-maps</code>
                    Cela peut prendre plusieurs minutes par carte.
                    {% endif %}
                </span>
            </div>
            {% endif %}
            
            <div class="info-box" style="margin-top: 20px;">
                {{ t('restart_note') }}
            </div>
        </div>
        
        <div class="buttons">
            <button class="btn btn-primary" onclick="fetch('/api/quit', {method: 'POST'});">{{ t('finish') }}</button>
        </div>
    </div>
</body>
</html>
''', css=CSS, t=t, symlinks=symlink_results, has_osm_maps=has_osm_maps, drive_type=drive_type, usb_path=usb_path, lang=session.get('lang', 'fr'))

@app.route('/api/quit', methods=['POST'])
def api_quit():
    """Quit the application"""
    print("[QUIT] Shutting down...")
    os._exit(0)

# =============================================================================
# MAIN
# =============================================================================

def run_flask(port):
    """Run Flask in a thread"""
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='EmComm-Tools First Boot Wizard')
    parser.add_argument('--port', type=int, default=5000, help='Port to run on')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--force', action='store_true', help='Run even if already completed')
    args = parser.parse_args()
    
    # Check if firstboot already completed (unless --force)
    if not args.force:
        firstboot_flag = Path.home() / ".config" / "emcomm-tools" / ".firstboot-complete"
        if firstboot_flag.exists():
            print("First boot wizard already completed. Use --force to run again.")
            sys.exit(0)
    
    # Remove Calamares icon on installed system (not live mode)
    is_live_mode = Path("/run/live").exists()
    if not is_live_mode:
        calamares_desktop = Path.home() / "Desktop" / "calamares-install-debian.desktop"
        if calamares_desktop.exists():
            try:
                calamares_desktop.unlink()
                print(f"[CLEANUP] Removed {calamares_desktop}")
            except Exception as e:
                print(f"[CLEANUP] Could not remove {calamares_desktop}: {e}")
    
    port = args.port
    
    if args.debug:
        # Debug mode: run Flask directly
        print(f"Starting in DEBUG mode on http://{args.host}:{port}")
        app.run(host=args.host, port=port, debug=True)
    else:
        # Default: PyWebView window (not frameless - fixes touch scroll issues)
        try:
            import webview
            
            # Get screen dimensions to adapt window size
            try:
                import gi
                gi.require_version('Gdk', '3.0')
                from gi.repository import Gdk
                screen = Gdk.Screen.get_default()
                screen_width = screen.get_width()
                screen_height = screen.get_height()
                
                # Reserve space for panel (typically 48px) and some margin
                panel_height = 60
                
                # Adapt to screen size - for small screens like 7" Toughpad
                if screen_height <= 800:
                    # Small screen (7" tablet ~1024x600 or 1280x800)
                    win_width = min(650, screen_width - 40)
                    win_height = screen_height - panel_height - 40
                else:
                    # Normal/large screen
                    win_width = 700
                    win_height = min(750, screen_height - panel_height - 60)
                
                # Center horizontally, position near top
                x = (screen_width - win_width) // 2
                y = 30
                
                print(f"[WINDOW] Screen: {screen_width}x{screen_height}, Window: {win_width}x{win_height} at ({x},{y})")
            except Exception as e:
                print(f"[WINDOW] Could not detect screen size: {e}")
                win_width = 650
                win_height = 550
                x = None
                y = None
            
            # Start Flask in background thread
            flask_thread = threading.Thread(target=run_flask, args=(port,), daemon=True)
            flask_thread.start()
            time.sleep(1)
            
            print(f"Starting EmComm-Tools First Boot Wizard (PyWebView)")
            
            # Create window with frame (better for touch)
            window = webview.create_window(
                'EmComm-Tools',
                f'http://127.0.0.1:{port}',
                width=win_width,
                height=win_height,
                resizable=True,
                min_size=(500, 450),
                x=x,
                y=y,
                frameless=False
            )
            
            def on_shown():
                """Apply dark title bar styling after window is shown"""
                try:
                    import gi
                    gi.require_version('Gtk', '3.0')
                    from gi.repository import Gtk, Gdk
                    
                    # Apply dark theme CSS to all windows
                    css = b'''
                    headerbar, .titlebar {
                        background: #1a1a1a;
                        color: #888;
                        min-height: 24px;
                        padding: 2px 6px;
                        border: none;
                        box-shadow: none;
                    }
                    headerbar .title, .titlebar .title {
                        font-size: 11px;
                        color: #888;
                    }
                    window decoration {
                        background: #1a1a1a;
                    }
                    '''
                    
                    style_provider = Gtk.CssProvider()
                    style_provider.load_from_data(css)
                    Gtk.StyleContext.add_provider_for_screen(
                        Gdk.Screen.get_default(),
                        style_provider,
                        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
                    )
                    print("[WINDOW] Applied dark title bar CSS")
                except Exception as e:
                    print(f"[WINDOW] Could not apply CSS: {e}")
            
            webview.start(func=on_shown)
            
        except ImportError:
            print("PyWebView not installed. Install with: sudo apt install python3-webview")
            sys.exit(1)

if __name__ == '__main__':
    main()

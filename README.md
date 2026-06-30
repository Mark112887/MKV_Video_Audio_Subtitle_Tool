# MKV Video Audio & Subtitle Tool

A desktop application for batch-processing MKV video files — changing display aspect ratio, removing subtitles, and filtering audio tracks — all without re-encoding. Powered by mkvtoolnix for fast, lossless container operations.

---

## Purpose

This tool is designed for users who need to quickly remux MKV files to:

- **Set a specific display aspect ratio** (e.g., 16:9, 4:3, 2.35:1) so media players render the video with the correct pixel aspect.
- **Remove embedded subtitles** that clutter the playback interface.
- **Keep only one audio track** (useful when a file contains multiple languages and you want to strip extras).
- **Delete original source files** after successful processing, freeing up disk space automatically.

Everything runs locally on your machine — no re-encoding means processing is fast and quality lossless.

---

## Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| **Aspect Ratio Conversion** | Set any display aspect ratio (DAR) using the `W:H` or `W/H` format (e.g., `16:9`, `4/3`, `2.35:1`). The tool writes `display-width`, `display-height`, and `display-unit` metadata into the MKV container via `mkvpropedit`. |
| **Subtitle Removal** | Strip all subtitle tracks from one or more MKV files with a single checkbox. Uses mkvmerge's `-S` flag to remove subtitles during remuxing. |
| **Delete Original Files** | Check a box before processing and the original source file(s) are deleted after successful remuxing, freeing up disk space. Available in both Batch and Individual modes with per-file granularity. |
| **Audio Track Filtering** | Keep only a single audio track while discarding all others. A dropdown auto-populates after loading an MKV file, showing each track's language (via IETF BCP 47 codes mapped to full names through ISO 639-1 lookup) and track ID. Selecting "Keep All" leaves every audio track untouched. |
| **Batch Processing** | Drag-and-drop an entire folder of MKV files (or a single file) and process them all in one go. The progress bar shows live percentage updates as each file completes. |
| **Per-File Override Mode** | Switch to "Individual" mode to customize DAR, audio track, and subtitle settings for each file independently. Click any file name in the list to load its saved settings; toggle the Batch/Individual switch to revert to global defaults. |

### User Interface

- **Dark theme** — easy on the eyes for extended use.
- **Drag-and-drop support** — drop MKV files or folders directly onto the blue drop zone at the top of the window.
- **Persistent output folder** — remembers your last chosen output location across launches.
- **Live progress feedback** — a blue animated progress bar with a percentage overlay shows real-time processing status for each file.
- **Clickable file list** — each entry displays a color-coded status tag (green = custom per-file settings, blue = global default, yellow-green highlight = selected).

### Technical Details

| Detail | Description |
|--------|-------------|
| **Backend** | Uses mkvtoolnix utilities (mkvmerge, mkvpropedit, mkvinfo) — bundled with the app so nothing extra to install. |
| **Processing Pipeline** | Step 1: mkvmerge remuxes your content with the chosen filters (audio track deletion, subtitle removal). Step 2: mkvpropedit writes display aspect ratio metadata into the container. |

---

## Requirements

- **Operating System:** Windows 10 or later (64-bit)
- **Python 3.11+** — only needed if building from source, not for running the pre-built EXE.
- **Pywin32** (`pip install pywin32`) — required for drag-and-drop support at runtime.
- The three mkvtoolnix executables are bundled with the app and do **not** need to be installed separately.

### From Source (Build Instructions)

```powershell
# 1. Clone or download this repository
# 2. Install dependencies
pip install pyinstaller pywin32

# 3. Build the standalone executable
python -m PyInstaller --clean MKV_Video_Audio_Subtitle_Tool.spec
```

The compiled application will be in `dist/MKV Video Audio & Subtitle Tool.exe`.

---

## How to Use

### Quick Start (Pre-Built EXE)

1. **Launch** `MKV Video Audio & Subtitle Tool.exe`.
2. **Drop MKV files** — drag any MKV file(s) or an entire folder onto the blue drop zone at the top, or click **Browse**.
3. **Choose global settings:**
   - **Desired Aspect Ratio** — type a ratio like `16:9` (default), `4:3`, or `2.35:1`.
   - **Audio Track to Keep** — select "Keep All" (default) or pick a specific track from the dropdown.
   - **Remove Subtitles** — check the box if you want subtitles stripped.
   - **Delete Original Files** — check the box to remove source files after successful processing (per-file in Individual mode).
4. **Choose output location** (optional) — click **Output Dir** to set where processed files will be saved. Defaults to a `Processed Files` folder next to the executable.
5. **Click Process** — the batch job begins. Watch progress in the panel below.

#### Default Output Folder

When you first launch the app, it automatically creates a **`Processed Files`** folder in the same location where the executable is launched (e.g., next to `MKV Video Audio & Subtitle Tool.exe`). All processed output goes there by default unless you explicitly change the output location via **Output Dir**.

### Using Individual Mode

1. Click the **Individual** tab (next to Batch) above the settings area.
2. Click any file name in the list below — its saved settings load into the controls.
3. Change DAR, audio track, subtitle, or delete-originals setting for that file only. Changes are saved automatically as you type or select.
4. Switch back to **Batch** at any time to apply global defaults across all files.

### Understanding Status Colors in the File List

| Color | Meaning |
|-------|---------|
| 🟢 Green text | This file has custom per-file settings that differ from global defaults |
| 🔵 Blue text | This file uses global default settings (no individual override) |
| 🟡 Yellow-green background highlight | The currently selected file in the list |

### Processing Output

During processing, each file entry shows:

- **Progress counter** — `[1/3] filename.mkv …` (which file out of total)
- **Success** — `✓ Display Aspect Ratio Set to 16:9  Subtitles Removed: Yes  Original Deleted: Yes` or similar, depending on choices made
- **Failure** — `✗ mkvmerge.exe not found.` or other error message

A summary line at the end shows: `═══ complete: X ok, Y failed ═══`

---

## File Structure

```
MKV Video Audio & Subtitle Tool/
├── MKV_Video_Audio_Subtitle_Tool.py    # Main application source code (GPL v3)
├── MKV_Video_Audio_Subtitle_Tool.spec  # PyInstaller build configuration
├── LICENSE                              # GNU GPL v3 license text
├── README.md                            # This file
│
├── dist/                                # Compiled standalone application
│   └── MKV Video Audio & Subtitle Tool.exe
│
└── mkvmerge.exe                         # Bundled mkvtoolnix remuxer (redistributable)
├── mkvpropedit.exe                      # Bundled mkvtoolnix property editor
└── mkvinfo.exe                          # Bundled mkvtoolnix file inspector
```

---

## Configuration

Your output folder choice is saved automatically — no configuration needed. To reset it, just delete the `settings.json` file in the app's directory. Processing logs are written to the same directory while jobs run; they contain command-level detail useful for troubleshooting.

---

## License

This project is licensed under the **GNU General Public License v3.0** (GPL-3.0). You are free to copy, distribute, and modify it under the terms of the GPL. See `LICENSE` for the full text.

The bundled mkvtoolnix executables remain property of their respective authors (MKVToolNix project by Moritz Bunge / molly). Refer to their license for redistribution terms.

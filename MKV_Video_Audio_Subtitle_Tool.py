# -*- mode: python ; coding: utf-8 -*-
"""MKV Pixel Aspect Ratio Changer + Subtitle Remover

tkinter desktop app — visual layout matches the original MP4 Pixel Aspect Ratio Changer.
Backend uses mkvtoolnix for container operations (no re-encoding).

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import sys
import os
import re
import math
import json
import threading

# ─── Windows DND support (pywin32 + ctypes for DragQueryFile) ──────────────
import ctypes
from ctypes import wintypes

WM_DROPFILES = 0x0233

_CallWindowProcW = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_void_p, wintypes.UINT,
    ctypes.c_ulonglong, ctypes.c_longlong
)(ctypes.windll.user32.CallWindowProcW)

_shell32 = ctypes.windll.shell32
_DragQueryFileW = _shell32.DragQueryFileW
_DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(wintypes.WCHAR), wintypes.UINT]
_DragQueryFileW.restype = wintypes.UINT
_DragFinish = _shell32.DragFinish
_DragFinish.argtypes = [ctypes.c_void_p]
_DragFinish.restype = ctypes.c_int


# ─── Settings persistence ──────────────────────────────────────────────

def _settings_path():
    """Return a path for a JSON settings file next to the script/executable."""
    base = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, 'frozen', False) else __file__
    ))
    return os.path.join(base, 'settings.json')


def _load_output_dir():
    """Load the previously saved output directory, or None."""
    try:
        with open(_settings_path(), 'r') as f:
            data = json.load(f)
        return data.get('output_dir')
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_output_dir(path):
    """Save the output directory to the settings file."""
    try:
        with open(_settings_path(), 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data['output_dir'] = path
    with open(_settings_path(), 'w') as f:
        json.dump(data, f, indent=2)


def _ensure_default_output_dir():
    """Ensure a default output directory exists.

    Returns the output directory path:
    - previously saved one if available;
    - otherwise creates (if missing) and returns a 'Processed Files' folder
      next to the script/executable.
    """
    saved = _load_output_dir()
    if saved and os.path.isdir(saved):
        return saved

    base = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, 'frozen', False) else __file__
    ))
    default = os.path.join(base, 'Processed Files')
    os.makedirs(default, exist_ok=True)
    return default


def parse_dar(dar_str):
    """Parse a DAR string like '16:9', '4/3', '2.35:1' → (dar_w, dar_h) ints.

    Raises ValueError on bad input.
    """
    dar_str = dar_str.strip()
    sep = re.search(r'[/:]', dar_str)
    if not sep:
        raise ValueError(f"Invalid DAR format: {dar_str!r}. Use 'W:H' or 'W/H'.")
    left, right = dar_str[:sep.start()], dar_str[sep.end():]
    left_f, right_f = float(left), float(right)
    if right_f == 0:
        raise ValueError("DAR denominator cannot be zero.")

    # Determine scale needed to convert both sides to integers.
    scale = 1
    for token in (left, right):
        token = token.strip()
        dot = token.find('.')
        if dot != -1:
            digits = len(token[dot + 1:])
            scale *= (10 ** digits)

    left_i = int(round(left_f * scale))
    right_i = int(round(right_f * scale))
    g = math.gcd(left_i, right_i)
    return left_i // g, right_i // g


# ─── mkvtoolnix helpers ──────────────────────────────────────────────

def _mkv_exe(name):
    """Find an mkvtoolnix executable — bundled with PyInstaller or alongside the script."""
    candidates = []
    if hasattr(sys, '_MEIPASS'):
        candidates.append(os.path.join(sys._MEIPASS, f'{name}.exe'))
    base_dir = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, 'frozen', False) else __file__
    ))
    candidates.append(os.path.join(base_dir, f'{name}.exe'))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _get_mkvinfop():
    """Return the path to mkvinfo.exe or None."""
    return _mkv_exe('mkvinfo')


def _get_mkvmerge():
    """Return the path to mkvmerge.exe or None."""
    return _mkv_exe('mkvmerge')


def _get_mkvpropedit():
    """Return the path to mkvpropEdit.exe or None."""
    return _mkv_exe('mkvpropedit')


def run_mkvtl(args, timeout=300):
    """Run an mkvtoolnix tool; returns (returncode, combined_text).

    On Windows some mkvtoolnix tools write to stderr — merge stdout+stderr.
    """
    # CREATE_NO_WINDOW hides the command prompt window on Windows for mkvtoolnix tools
    try:
        r = subprocess.run(
            args,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        return r.returncode, r.stdout or ''
    except subprocess.TimeoutExpired:
        return -1, "Timeout"


def probe_mkv(mkv_path):
    """Probe an MKV file with mkvinfo.

    Returns (info_dict | None, error_msg | None).
    info_dict keys: width, height, video_track_ids, subtitle_track_ids, total_tracks
    """
    mkvinfo = _get_mkvinfop()
    if mkvinfo is None:
        return None, "mkvinfo.exe not found."

    rc, text = run_mkvtl([mkvinfo, mkv_path], timeout=30)
    if rc != 0:
        return None, f"mkvinfo failed: {text}"

    width = height = None
    video_track_ids = []
    subtitle_track_ids = []
    total_tracks = 0

    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track count
        if 'Number of tracks' in stripped:
            m = re.search(r'(\d+)', stripped)
            if m:
                total_tracks = int(m.group(1))

        # Video track block
        if stripped.startswith('Track number:') and ': video' in stripped:
            m = re.search(r'Track number (\d+)', line)
            if m:
                video_track_ids.append(int(m.group(1)))

        # Subtitle track detection (SubRip, ASS, etc.)
        if 'Track number:' in stripped and ('Subtitles' in stripped or 'Text' in stripped):
            m = re.search(r'Track number (\d+)', line)
            if m:
                subtitle_track_ids.append(int(m.group(1)))

    # mkvinfo doesn't report raw pixel dimensions directly — fall back to mkvmerge -i
    for line in lines:
        stripped = line.strip()
        m_w = re.search(r'(\d{3,})\s*x\s*(\d{3,})', stripped)
        if m_w and ('Video' in line or 'Resolution' in line):
            width = int(m_w.group(1))
            height = int(m_w.group(2))
            break

    # Fallback: check mkvmerge -i output (more structured)
    if width is None or height is None:
        mkvmerge = _get_mkvmerge()
        if mkvmerge:
            rc, text = run_mkvtl([mkvmerge, '-i', mkv_path], timeout=30)
            if rc == 0:
                for line in text.splitlines():
                    if 'Video:' in line and 'Track ID' in line:
                        m_w = re.search(r'(\d{3,})\s*x\s*(\d{3,})', line)
                        if m_w:
                            width = int(m_w.group(1))
                            height = int(m_w.group(2))
                            break

    return {
        'width': width or 0,
        'height': height or 0,
        'video_track_ids': video_track_ids,
        'subtitle_track_ids': subtitle_track_ids,
        'total_tracks': total_tracks,
    }, None


# ─── Debug log helper ─────────────────────────────────────────────

def _debug_log_path():
    """Path to the debug log file next to the script/executable."""
    base = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, 'frozen', False) else __file__
    ))
    return os.path.join(base, 'mkv_debug.log')


def _debug_write(msg):
    """Write a timestamped line to the debug log file."""
    import datetime
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    line = f"[{ts}] {msg}\n"
    try:
        with open(_debug_log_path(), 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass  # don't crash logging


def process_mkv(mkv_path, output_dir, dar_str="16:9", remove_subs=True, audio_sel=None, delete_original=False):
    """Process one MKV — set DAR via mkvmerge + mkvpropedit.  Returns (ok, msg).

    *audio_sel*: None = keep all audio tracks; int = only keep this track ID.
    *delete_original*: True = remove the source file after successful processing.
    """
    _debug_write(f"=== START processing {mkv_path}")
    _debug_write(f"  output_dir={output_dir}  dar={dar_str}  remove_subs={remove_subs}")

    # Parse DAR
    try:
        dar_w, dar_h = parse_dar(dar_str)
    except ValueError as e:
        msg = f"Invalid DAR: {e}"
        _debug_write(f"  FAIL: {msg}")
        return False, msg

    _debug_write(f"  DAR parsed: {dar_w}:{dar_h} ({dar_w}/{dar_h})")

    basename = os.path.splitext(os.path.basename(mkv_path))[0]
    output_path = os.path.join(output_dir, f"{basename}.mkv")
    _debug_write(f"  Output will be: {output_path}")

    # ── Step 1 — mkvmerge: copy tracks, optionally filter audio & remove subs ─
    mkvmerge = _get_mkvmerge()
    if mkvmerge is None:
        msg = "mkvmerge.exe not found."
        _debug_write(f"  FAIL: {msg}")
        return False, msg

    # Build mkvmerge args: copy tracks, optionally delete subtitles, filter audio
    merge_args = ['-o', output_path]

    if audio_sel is not None:
        _debug_write(f"  Keeping audio Track #{audio_sel} (--audio-tracks)")
        merge_args += ['--audio-tracks', str(audio_sel)]

    if remove_subs:
        # -S removes all subtitle tracks (matches the batch file approach)
        _debug_write(f"  Removing subtitles (-S)")
        merge_args.append('-S')

    merge_args.append(mkv_path)
    full_command = [mkvmerge] + merge_args
    _debug_write(f"  mkvmerge command: {' '.join(full_command)}")

    rc, out_text = run_mkvtl(full_command, timeout=600)
    _debug_write(f"  mkvmerge rc={rc}")
    if out_text.strip():
        for l in out_text.splitlines():
            _debug_write(f"    mkvmerge: {l}")

    # Verify output file was actually created
    if not os.path.exists(output_path):
        msg = f"mkvmerge ran but output file does not exist at:\n  {output_path}"
        _debug_write(f"  FAIL: {msg}")
        return False, msg

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    _debug_write(f"  mkvmerge OK — output created ({file_size:.1f} MB)")

    # ── Step 2 — mkvpropedit: set display width/height on the NEW file ─
    mkvpropedit = _get_mkvpropedit()
    if mkvpropedit is None:
        os.remove(output_path)
        msg = "mkvpropEdit.exe not found."
        _debug_write(f"  FAIL: {msg}")
        return False, msg

    # Build mkvpropedit arguments for DAR editing
    dar_args = ['--edit', 'track:v1', '--set', f'display-width={dar_w}',
                '--set', f'display-height={dar_h}', '--set', 'display-unit=3']

    rc, out_text = run_mkvtl([mkvpropedit, output_path] + dar_args, timeout=60)

    _debug_write(f"  mkvpropedit DAR rc={rc}")
    if out_text.strip():
        for l in out_text.splitlines():
            _debug_write(f"    mkvpropedit: {l}")

    if rc != 0:
        os.remove(output_path)
        msg = f"mkvpropedit failed (rc={rc}):\n{out_text}"
        _debug_write(f"  FAIL: {msg}")
        return False, msg

    _debug_write("  mkvpropedit OK — DAR set on output file")

    # If a specific audio track was filtered out, the source may have had
    # "Enabled flag: 0" which persists through mkvmerge remuxing.
    # Set flag-enabled=1 on the remaining audio track so players will play it.
    if audio_sel is not None and audio_sel != 1:
        _debug_write(f"  Enabling remaining audio Track #1 (flag-enabled=1)")
        en_args = ['--edit', 'track:a1', '--set', 'flag-enabled=1']
        rc_en, out_en = run_mkvtl([mkvpropedit, output_path] + en_args, timeout=60)
        _debug_write(f"  mkvpropedit flag-enabled rc={rc_en}")
        if out_en.strip():
            for l in out_en.splitlines():
                _debug_write(f"    mkvpropedit-en: {l}")
        if rc_en != 0:
            msg = f"Failed to enable audio track:\n{out_en}"
            _debug_write(f"  FAIL: {msg}")
            return False, msg

    # Delete original file if requested (only after ALL steps succeed)
    if delete_original:
        try:
            _debug_write(f"  Deleting original source file: {mkv_path}")
            os.remove(mkv_path)
            _debug_write("  Original file deleted successfully")
            msg += "  Original Deleted: Yes"
        except OSError as e:
            # Log but don't fail the whole operation — output file is already good
            err_msg = f"Could not delete original ({e})"
            _debug_write(f"  WARN: {err_msg}")
            msg += f"  Original Deleted: No ({err_msg})"

    # Success message
    msg = f"Display Aspect Ratio Set to {dar_w}:{dar_h}"
    if remove_subs:
        msg += "  Subtitles Removed: Yes"
    else:
        msg += "  Subtitles Removed: No"
    if audio_sel is not None:
        msg += f"  Audio Kept: Track #{audio_sel}"
    _debug_write(f"  DONE — {msg}")
    return True, msg


# ─── Audio track probing ──────────────────────────────────────────────

# ─── Language code → full name mapping ─────────────────────────────────────

_ISO_639_1_TO_NAME = {
    'af': 'Afrikaans',       'sq': 'Albanian',      'ar': 'Arabic',
    'eu': 'Basque',          'be': 'Belarusian',    'bn': 'Bengali',
    'bg': 'Bulgarian',       'ca': 'Catalan',       'zh': 'Chinese',
    'hr': 'Croatian',        'cs': 'Czech',         'da': 'Danish',
    'nl': 'Dutch',           'en': 'English',       'et': 'Estonian',
    'fi': 'Finnish',         'fr': 'French',        'gl': 'Galician',
    'ka': 'Georgian',        'de': 'German',        'el': 'Greek',
    'gu': 'Gujarati',        'he': 'Hebrew',        'hi': 'Hindi',
    'hu': 'Hungarian',       'is': 'Icelandic',     'id': 'Indonesian',
    'ga': 'Irish',           'it': 'Italian',       'ja': 'Japanese',
    'kn': 'Kannada',         'kk': 'Kazakh',        'ko': 'Korean',
    'lv': 'Latvian',         'lt': 'Lithuanian',    'mk': 'Macedonian',
    'ms': 'Malay',           'ml': 'Malayalam',     'mt': 'Maltese',
    'mr': 'Marathi',         'mn': 'Mongolian',     'no': 'Norwegian',
    'fa': 'Persian',         'pl': 'Polish',        'pt': 'Portuguese',
    'ro': 'Romanian',        'ru': 'Russian',       'sr': 'Serbian',
    'sk': 'Slovak',          'sl': 'Slovenian',     'es': 'Spanish',
    'sw': 'Swahili',         'sv': 'Swedish',       'ta': 'Tamil',
    'te': 'Telugu',          'th': 'Thai',          'tr': 'Turkish',
    'uk': 'Ukrainian',       'ur': 'Urdu',          'vi': 'Vietnamese',
}


def probe_audio_tracks(mkv_path):
    """Probe an MKV file for audio tracks using mkvinfo.

    Returns a list of dicts:
        [{'id': <int>, 'language': <str or None>}, ...]
    Language is from the IETF BCP 47 track language tag, falls back to 'und' if not set.
    The id is the `Track number: N` value from mkvinfo — this works directly with
    mkvmerge --audio-tracks and mkvpropedit --edit track:N.
    """
    mkvinfo = _get_mkvinfop()
    if mkvinfo is None:
        return []

    rc, text = run_mkvtl([mkvinfo, mkv_path], timeout=30)
    if rc != 0 or not text.strip():
        return []

    audio_tracks = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect start of a track block: "| + Track number:" (with possible leading whitespace)
        if re.search(r'\|\s*\+\s+Track\s+number:', line):
            m_num = re.search(r'Track number:\s*(\d+)', line)
            if not m_num:
                i += 1
                continue
            track_num = int(m_num.group(1))

            # Extract the parenthetical mkvmerge ID — this is what --audio-tracks expects
            m_mkvmerge_id = re.search(r'mkvmerge.*:\s*(\d+)', line)
            merge_id = int(m_mkvmerge_id.group(1)) if m_mkvmerge_id else track_num

            # Parse this track block (collect until next Track block or top-level section)
            track_type = None
            language = None
            j = i + 1
            while j < len(lines):
                raw_j = lines[j]
                s = raw_j.strip()
                # New track block or top-level section ends the current block
                if re.search(r'\|\s*\+\s+Track\s+number:', raw_j) or '| Tracks' in raw_j:
                    break
                m_type = re.search(r'Track type:\s*(\w+)', s)
                if m_type:
                    track_type = m_type.group(1).lower()
                # IETF BCP 47 language (preferred over plain Language)
                m_lang = re.search(r'Language \(IETF BCP 47\):\s*(.+)', s)
                if m_lang:
                    language = m_lang.group(1).strip()
                j += 1

            if track_type == 'audio':
                audio_tracks.append({
                    'id': merge_id,
                    'track_num': track_num,  # MKV Track Number element for mkvpropedit
                    'language': language,
                })

        i += 1

    return audio_tracks


# ─── GUI ─────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("MKV Video Audio & Subtitle Tool")
        self.root.geometry("640x500")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1b26")
        # Always stay on top so processing windows and progress bar are never obscured
        self.root.attributes('-topmost', True)

        self.file_list = []
        self.selected_file_index = -1  # -1 = no file selected → global settings apply
        self.processing = False
        self.output_dir = _ensure_default_output_dir()

        # Per-file settings dict: path -> {'dar': str, 'audio_sel': int|None, 'remove_subs': bool}
        self.file_settings = {}

        # Colours (matching the original app)
        BG       = "#1a1b26"
        CARD     = "#24283b"
        FG       = "#c0caf5"
        ACCENT   = "#7aa2f7"
        GREEN    = "#9ece6a"
        RED      = "#f7768e"
        MUTED    = "#565f89"

        # ── Drop zone ────────────────────────────────────────────────
        self.drop_frame = tk.Frame(root, bg=CARD, height=100,
                                   highlightbackground="#414868", highlightthickness=2)
        self.drop_frame.pack(fill="x", padx=14, pady=10)
        self.drop_frame.pack_propagate(False)

        self.drop_icon = tk.Label(self.drop_frame, text="📂", font=("Segoe UI Emoji", 28),
                                  bg=CARD, fg=FG)
        self.drop_icon.place(relx=0.15, rely=0.4, anchor="center")

        self.drop_label = tk.Label(self.drop_frame,
                                   text="Drag & Drop MKV Files or Folders here\nor click Browse",
                                   font=("Segoe UI", 10), bg=CARD, fg=MUTED, justify="center")
        self.drop_label.place(relx=0.55, rely=0.4, anchor="center")

        self.drop_frame.bind("<Button-1>", self._browse)
        self.drop_frame.configure(cursor="hand2")

        # Hover effect
        def on_enter(_e):
            self.drop_frame.configure(highlightbackground=ACCENT)
        def on_leave(_e):
            self.drop_frame.configure(highlightbackground="#414868")
        self.drop_frame.bind("<Enter>", on_enter)
        self.drop_frame.bind("<Leave>", on_leave)

        # ── File list ────────────────────────────────────────────────
        list_frame = tk.Frame(root, bg=BG)
        list_frame.pack(fill="x", padx=14, pady=(0, 4))

        hdr = tk.Label(list_frame, text="Files & Status", font=("Segoe UI", 9, "bold"),
                       bg=BG, fg=MUTED)
        hdr.pack(anchor="nw")

        self.txt = tk.Text(list_frame, height=7,
                           font=("Consolas", 9), bg="#16171a", fg=FG,
                           insertbackground=ACCENT, state="disabled",
                           highlightthickness=0, wrap="word",
                           cursor="hand2")
        vsb = ttk.Scrollbar(list_frame, command=self.txt.yview)
        self.txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True)
        self.txt.bind("<Button-1>", self._on_text_click)

        # ── Info bar ─────────────────────────────────────────────────
        self.info_var = tk.StringVar(value=None)
        self.info_lbl = tk.Label(root, textvariable=self.info_var,
                                 font=("Segoe UI", 9), bg=BG, fg=MUTED, anchor="w")
        self.info_lbl.pack(fill="x", padx=16, pady=(0, 1))

        # ── Mode toggle (Batch / Individual) ─────────────────────────
        mode_row = tk.Frame(root, bg=BG)
        mode_row.pack(fill="x", padx=16, pady=(4, 2))

        self.mode_var = tk.StringVar(value="batch")

        # Batch button starts active (blue bg), Individual is inactive (gray text on dark card)
        self._btn_mode("Batch",       "batch",       mode_row)
        self._btn_mode("Individual",  "individual",  mode_row, inactive=True)

        # ── DAR input ────────────────────────────────────────────────
        dar_row = tk.Frame(root, bg=BG)
        dar_row.pack(fill="x", padx=16, pady=(0, 2))

        tk.Label(dar_row, text="Desired Aspect Ratio:", font=("Segoe UI", 9),
                 bg=BG, fg=MUTED).pack(side="left")

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure(
            "DAR.TEntry",
            fieldbackground="#16171a",
            foreground=FG,
            font=("Consolas", 9),
            padding=3
        )
        # DAR uses a tk.StringVar with textvariable on the Entry.
        # trace_add fires on BOTH user typing AND programmatic .set() calls.
        # To capture per-file settings we need saving in the trace, but we must
        # skip saving during file restoration (programmatic control updates).
        self._dar_last_valid = "16:9"  # track last valid value for reverting invalid input
        self._dar_reverting = False    # guard against re-entrant trace callbacks on DAR validation
        self._restoring_file = False   # set around file restoration to skip per-file save

        def _dar_trace(*_args):
            """Trace callback on dar_str — validates and saves per-file settings.

            Skips save during file restoration (_restoring_file flag) to avoid
            capturing intermediate control state as a per-file override.
            """
            if self._dar_reverting:
                return  # skip — reverting invalid DAR, don't validate or save
            if self._restoring_file:
                return  # skip — restoring controls for another file, not user input

            val = self.dar_str.get()

            # Validate: digits, colons, slashes only; must contain a separator
            sep = re.search(r'[:/]', val)
            if sep:
                left, right = val[:sep.start()], val[sep.end():]
                if not left or not right:
                    return  # partial (e.g. "16:" or ":9") — valid for typing
                if all(c.isdigit() for c in left) and all(c.isdigit() for c in right):
                    self._dar_last_valid = val
                    self._save_current_file_settings()
                    return
            else:
                # No separator yet — still valid partial (e.g. "16")
                if val and all(c.isdigit() for c in val):
                    self._save_current_file_settings()
                    return

            # Invalid input — revert dar_str to last valid value
            try:
                self._dar_reverting = True
                self.dar_str.set(self._dar_last_valid)
            finally:
                self._dar_reverting = False

        self.dar_str = tk.StringVar(value="16:9")
        self.dar_str.trace_add('write', _dar_trace)  # validation + save (guarded by _restoring_file)

        self.dar_entry = ttk.Entry(dar_row, style="DAR.TEntry", textvariable=self.dar_str, width=8)
        self.dar_entry.pack(side="left", padx=(6, 0))

        def _select_dar(_event=None):
            self.dar_entry.selection_range(0, "end")
        self.dar_entry.bind("<FocusIn>", _select_dar)

        # ── Audio tracks dropdown + Remove Subtitles checkbox ─────────
        tk.Label(dar_row, text="", bg=BG, width=1).pack(side="left")

        # "Audio", "Track", "To", "Keep" stacked vertically beside the combobox
        audio_frame = tk.Frame(dar_row, bg=BG)
        audio_frame.pack(side="left", padx=(0, 4))
        for word in ("Audio", "Track", "To", "Keep"):
            tk.Label(audio_frame, text=word, font=("Segoe UI", 9),
                     bg=BG, fg=MUTED).pack(side="top")

        self.audio_var = tk.StringVar(value="Keep All")
        self.audio_combo = ttk.Combobox(
            dar_row, textvariable=self.audio_var,
            font=("Segoe UI", 9), state="readonly", width=26, justify="center"
        )
        self.audio_combo["values"] = ("Keep All",)
        self.audio_combo.pack(side="left", padx=(0, 8))

        def _on_audio_change(*_args):
            """Save per-file settings on audio change — skip if restoring controls."""
            if getattr(self, '_restoring_file', False):
                return
            self._save_current_file_settings()
        self.audio_var.trace_add('write', _on_audio_change)

        self.remove_subs_var = tk.BooleanVar(value=False)
        subs_cb = tk.Checkbutton(
            dar_row, text="Remove Subtitles", variable=self.remove_subs_var,
            font=("Segoe UI", 9), bg=BG, fg=FG,
            activebackground=BG, selectcolor=CARD, anchor="w", cursor="hand2"
        )
        subs_cb.pack(side="left")

        def _on_subs_change(*_args):
            """Save per-file settings on subs change — skip if restoring controls."""
            if getattr(self, '_restoring_file', False):
                return
            self._save_current_file_settings()
        self.remove_subs_var.trace_add('write', _on_subs_change)

        self.delete_originals_var = tk.BooleanVar(value=False)
        del_cb = tk.Checkbutton(
            dar_row, text="Delete\nOriginal\nFiles", variable=self.delete_originals_var,
            font=("Segoe UI", 9), bg=BG, fg=FG,
            activebackground=BG, selectcolor=CARD, anchor="w", cursor="hand2"
        )
        del_cb.pack(side="left")

        def _on_delete_change(*_args):
            """Save per-file settings on delete-originals change — skip if restoring controls."""
            if getattr(self, '_restoring_file', False):
                return
            self._save_current_file_settings()
        self.delete_originals_var.trace_add('write', _on_delete_change)

        tk.Label(dar_row, text="", bg=BG, width=1).pack(side="left")

        # ── Progress ─────────────────────────────────────────────────
        self.pbar_style = ttk.Style()
        self.pbar_style.configure("custom.Horizontal.TProgressbar",
                                  background=ACCENT, troughcolor="#16171a", thickness=8)

        pbar_outer = tk.Frame(root, bg=BG)
        pbar_outer.pack(fill="x", padx=14, pady=(0, 6))

        # Percentage label — always visible above the tray
        self.pbar_label = tk.Label(
            pbar_outer, text="0%", font=("Segoe UI", 9, "bold"),
            bg=BG, fg=ACCENT,
        )
        self.pbar_label.pack(fill="x")

        # Tray frame — bg is the tray color so everything inside has a seamless background
        pbar_tray = tk.Frame(pbar_outer, bg="#16171a")
        pbar_tray.pack(fill="x")

        self.pbar = ttk.Progressbar(pbar_tray, style="custom.Horizontal.TProgressbar",
                                    mode="determinate", length=520)
        self.pbar.pack(fill="x", padx=8, pady=2)

        # ── Buttons ──────────────────────────────────────────────────
        btn_row = tk.Frame(root, bg=BG)
        btn_row.pack(fill="x", padx=14, pady=6)

        self._btn("📁 Browse", self._browse, btn_row, side="left")
        self._btn("🗑 Clear",  self._clear,  btn_row, side="left")
        tk.Label(btn_row, text="", bg=BG, width=2).pack(side="left")
        self._btn("📂 Output Dir",  self._pick_output, btn_row, side="right")
        self.proc_btn = self._btn("▶  Process", self._start_process, btn_row,
                                  side="right", bg=GREEN, state="disabled")

        # ── CLI args ─────────────────────────────────────────────────
        for arg in sys.argv[1:]:
            for mkv in self._collect_mkv(arg):
                self.add_file(mkv)

        # ── Windows drag-and-drop hook ───────────────────────────────
        self._setup_win_dnd()

    def _btn(self, text, cmd, master, side="left", bg="#3b4261", **kw):
        b = tk.Button(master, text=text, command=cmd, font=("Segoe UI", 9),
                      width=10, bg=bg, fg="#e1e5ee", padx=6, pady=3,
                      activebackground="#474c68", activeforeground="white",
                      relief="flat", cursor="hand2")
        b.config(**kw)
        b.pack(side=side, padx=3)
        return b

    def _dnd_log(self, msg):
        """Append a DND diagnostic message to the app text area."""
        self._append_text(msg + "\n", color="#7aa2f7")

    # -- Windows DND via pywin32 --
    def _setup_win_dnd(self):
        try:
            import win32gui
            self.root.after(200, self._enable_dnd_delayed)
        except ImportError as e:
            self._dnd_log(f"pywin32 not available ({e}), DND disabled")
        except Exception as e:
            self._dnd_log(f"Setup failed: {e}")

    def _enable_dnd_delayed(self):
        import win32gui

        try:
            target = self.drop_frame
            hwnd = int(target.winfo_id())

            result = ctypes.windll.shell32.DragAcceptFiles(hwnd, True)
            if not result:
                self._dnd_log(f"DragAcceptFiles returned FALSE (hwnd=0x{hwnd:x})")
                return

            GWLP_WNDPROC = -4
            original_proc = win32gui.GetWindowLong(hwnd, GWLP_WNDPROC)
            self._dnd_original_proc = original_proc

            def wnd_callback(h, msg, wp, lp):
                if msg == WM_DROPFILES:
                    try:
                        count = _DragQueryFileW(wp, -1, None, 0)
                        dropped_paths = []
                        for i in range(count):
                            buf = ctypes.create_unicode_buffer(260)
                            _DragQueryFileW(wp, i, buf, 260)
                            dropped_paths.append(buf.value)
                        _DragFinish(wp)
                        mkvs = []
                        for dp in dropped_paths:
                            mkvs.extend(self._collect_mkv(dp))
                        added = sum(1 for f in mkvs if self.add_file(f))
                        self._dnd_log(f"Added {added} mkv(s).")
                    except Exception as e:
                        self._dnd_log(f"error querying drop: {e}")
                    return 0
                return _CallWindowProcW(self._dnd_original_proc, h, msg, wp, lp)

            win32gui.SetWindowLong(hwnd, GWLP_WNDPROC, wnd_callback)

        except Exception as e:
            self._dnd_log(f"enable failed: {type(e).__name__}: {e}")

    @staticmethod
    def _collect_mkv(path):
        """Return a list of .mkv paths from *path*.

        If *path* is a file → return it (if .mkv).
        If *path* is a directory  → walk the tree and return all .mkv files.
        """
        if os.path.isfile(path) and path.lower().endswith(".mkv"):
            return [path]
        if os.path.isdir(path):
            mkvs = []
            for root, _dirs, files in os.walk(path):
                for fname in files:
                    if fname.lower().endswith(".mkv"):
                        mkvs.append(os.path.join(root, fname))
            return mkvs
        return []

    # -- file management --
    def _browse(self, event=None):
        files = filedialog.askopenfilenames(
            title="Select MKV Files", filetypes=[("MKV Files", "*.mkv")]
        )
        for f in files:
            self.add_file(f)

    def add_file(self, path):
        if path not in self.file_list and os.path.isfile(path):
            self.file_list.append(path)
            self._append_text(os.path.basename(path) + "\n", color="#c0caf5", tag_name=path)
            self._update_info()
            # Probe audio tracks from the first file added
            self.root.after(100, self._probe_and_populate_audio)
            if not self.processing and self.output_dir:
                self.proc_btn.config(state="normal")
            return True
        return False

    def _clear(self):
        self.file_list.clear()
        self.selected_file_index = -1
        self.file_settings.clear()
        self._global_audio_sel = None
        self.audio_var.set("Keep All")
        self.audio_combo.config(values=("Keep All",))
        self._audio_track_data = {"Keep All": None}
        self.txt.config(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.config(state="disabled")
        self.pbar['value'] = 0
        self._update_info()
        if not self.processing:
            self.proc_btn.config(state="disabled")

    def _update_info(self):
        """Update the info bar — shows file count and output directory."""
        if self.output_dir:
            self.info_var.set(f"Files: {len(self.file_list)}   |   Output: {self.output_dir}")
        else:
            self.info_var.set('Output folder not set')

    def _pick_output(self):
        d = filedialog.askdirectory(title="Choose Output Directory")
        if d:
            self.output_dir = d
            _save_output_dir(d)
            self._update_info()
            if not self.processing and self.file_list:
                self.proc_btn.config(state="normal", bg="#9ece6a")

    # -- processing (stub — no backend yet) --
    def _start_process(self):
        if not self.file_list or self.processing:
            return
        if not self.output_dir:
            messagebox.showwarning("No Output Folder",
                                  "Please select an output folder first.\n\nClick 📂 Output Dir to choose a destination.")
            return
        try:
            parse_dar(self.dar_str.get())
        except ValueError as e:
            messagebox.showerror("Invalid DAR", str(e))
            return
        threading.Thread(target=self._process, daemon=True).start()

    def _save_current_file_settings(self):
        """Save current control values to per-file settings for the selected file.

        If no file is selected (selected_file_index == -1), also store global defaults
        so the user can see there's nothing special for any single file.
        """
        if 0 <= self.selected_file_index < len(self.file_list):
            sel_path = self.file_list[self.selected_file_index]
            # Resolve audio selection to track ID
            display = self.audio_var.get()
            data = getattr(self, '_audio_track_data', {"Keep All": None})
            audio_sel = data.get(display, None)

            self.file_settings[sel_path] = {
                'dar': self.dar_str.get(),
                'audio_sel': audio_sel,
                'remove_subs': self.remove_subs_var.get(),
                'delete_originals': self.delete_originals_var.get(),
            }
        else:
            # No file selected — store global "no override" marker
            pass

    def _process(self):
        remove_subs_global = self.remove_subs_var.get()
        delete_originals_global = self.delete_originals_var.get()
        dar_str_global = self.dar_str.get()
        display = self.audio_var.get()
        data = getattr(self, '_audio_track_data', {"Keep All": None})
        audio_sel_global = data.get(display, None)

        # Cache global values for comparison in _highlight_selected
        self._global_audio_sel = audio_sel_global

        # Save any pending per-file settings first
        self._save_current_file_settings()

        self.processing = True
        self._tk(lambda: self.proc_btn.config(state="disabled", bg="#3b4261"))
        self._tk(lambda: self.info_var.set("Processing…"))
        self._tk(lambda: self._append_text("\n── processing ──\n", color="#565f89"))

        total = len(self.file_list)
        ok = fail = 0

        for i, fp in enumerate(self.file_list, 1):
            if not os.path.isfile(fp):
                self._tk(lambda fn=os.path.basename(fp):
                         self._append_text(f"⊘ SKIP {fn} (not found)\n", color="#f7768e"))
                fail += 1
                continue

            # Look up per-file settings; fall back to global defaults
            fs = self.file_settings.get(fp)
            if fs:
                dar_str = fs['dar']
                remove_subs = fs['remove_subs']
                audio_sel = fs['audio_sel']
                delete_originals = fs['delete_originals']
            else:
                dar_str = dar_str_global
                remove_subs = remove_subs_global
                audio_sel = audio_sel_global
                delete_originals = delete_originals_global

            self._tk(lambda n=os.path.basename(fp), ix=i, t=total:
                     self._append_text(f"[{ix}/{t}] {n} …\n", color="#c0caf5"))
            self._tk(lambda prog=i * 100 // total: self._set_prog(prog))

            s, msg = process_mkv(fp, self.output_dir, dar_str, remove_subs, audio_sel, delete_originals)
            if s:
                ok += 1
                self._tk(lambda m=msg: self._append_text(f"  ✓ {m}\n", color="#9ece6a"))
            else:
                fail += 1
                self._tk(lambda m=msg: self._append_text(f"  ✗ {m}\n", color="#f7768e"))

        self._tk(lambda: self._set_prog(100))
        self._tk(lambda: self.info_var.set(f"Done — ✓ {ok}   ✗ {fail}"))
        self._tk(lambda: self._append_text(
            f"\n═══ complete: {ok} ok, {fail} failed ═══\n", color="#7aa2f7"))

        self.processing = False
        self._tk(lambda: self.proc_btn.config(state="normal", bg="#9ece6a"))

    # -- Tk threading helpers --
    # -- audio track probing --
    def _probe_and_populate_audio(self):
        """Probe the first file in the list for audio tracks and update the dropdown."""
        if not self.file_list:
            self.root.after(0, lambda: (
                self.audio_var.set("Keep All"),
                self.audio_combo.config(values=("Keep All",))
            ))
            return

        mkv_path = self.file_list[0]
        if not os.path.isfile(mkv_path):
            return

        audio_tracks = probe_audio_tracks(mkv_path)

        # Build options with embedded track ID as data
        options = [("Keep All", None)]  # (display_label, audio_index)
        for track in audio_tracks:
            lang = track.get('language', '').lower() or ''
            tid = track.get('id')

            if not lang or lang in ('und', 'unk'):
                display = f"Track #{tid}"
            elif len(lang) == 2:
                # Look up ISO 639-1 code → full name; fall back to uppercase if unknown
                display = f"Track #{tid} ({_ISO_639_1_TO_NAME.get(lang, lang.upper())})"
            else:
                display = f"Track #{tid} ({lang})"

            options.append((display, tid))

        self.root.after(0, lambda: (
            self.audio_var.set("Keep All"),
            self.audio_combo.config(values=tuple(opt[0] for opt in options))
        ))
        # Store full data on the widget for lookup during processing
        self._audio_track_data = dict(options)

    def _btn_mode(self, text, value, master, inactive=False):
        """Create one half of the Batch/Individual toggle.

        Uses plain tk.Button (not ttk) so bg/fg are always respected on Windows.
        Active = ACCENT blue bg + dark text, Inactive = CARD bg + light text.
        """
        btn_bg = "#24283b" if inactive else "#7aa2f7"
        btn_fg = "#c0caf5" if inactive else "#1a1b26"

        btn = tk.Button(
            master, text=text, width=14, font=("Segoe UI", 9),
            bg=btn_bg, fg=btn_fg, activebackground="#7aa2f7", activeforeground="#1a1b26",
            relief="flat", cursor="hand2", padx=10, pady=3, bd=0,
            command=lambda v=value: self._switch_mode(v),
        )
        btn.pack(side="left", padx=(3 if inactive else 0, 0))
        setattr(self, f"_mode_btn_{value}", btn)

    def _switch_mode(self, value):
        """Switch between batch and individual mode and update UI."""
        old_value = self.mode_var.get()
        if old_value == value:
            return

        # Save any pending per-file settings before switching modes
        if self.file_list and 0 <= self.selected_file_index < len(self.file_list):
            sel_path = self.file_list[self.selected_file_index]
            display = self.audio_var.get()
            data = getattr(self, '_audio_track_data', {"Keep All": None})
            audio_sel = data.get(display, None)
            self.file_settings[sel_path] = {
                'dar': self.dar_str.get(),
                'audio_sel': audio_sel,
                'remove_subs': self.remove_subs_var.get(),
            }

        # Block trace saves during mode-dependent control updates
        self._restoring_file = True

        self.mode_var.set(value)

        ACCENT_COLOR = "#7aa2f7"
        CARD_COLOR = "#24283b"
        FG_COLOR = "#c0caf5"

        for v in ("batch", "individual"):
            btn = getattr(self, f"_mode_btn_{v}")
            is_active = (v == value)
            if is_active:
                # Active: ACCENT bg + dark text
                btn.config(bg=ACCENT_COLOR, fg="#1a1b26", activebackground=ACCENT_COLOR, activeforeground="#1a1b26")
            else:
                # Inactive: CARD bg + light text
                btn.config(bg=CARD_COLOR, fg=FG_COLOR, activebackground=CARD_COLOR, activeforeground=FG_COLOR)

        # Sync selected_file_index to mode
        if value == "batch":
            self.selected_file_index = -1
        else:
            if self.file_list:
                self.selected_file_index = 0
            else:
                self.selected_file_index = -1

        # Unblock trace saves after mode-dependent control updates
        self._restoring_file = False

        self._highlight_selected()
        self.root.update()

    def _tk(self, fn):
        self.root.after(0, fn)

    def _set_prog(self, v):
        self.pbar['value'] = v
        self.pbar_label.config(text=f"{v}%")

    def _append_text(self, msg, color=None, tag_name=None):
        """Append text to the file list area.

        *tag_name*: optional full file path to attach as a Tk tag on this insertion.
        Clicking text with a tag_name will select that file for per-file settings.
        """
        self.txt.config(state="normal")
        if color:
            self.txt.tag_configure(color, foreground=color)
            self.txt.insert("end", msg, color)
            if tag_name:
                # Tag the last inserted span (from 'end-1c' back to the start of this insertion)
                line_start = self.txt.index("end-1c linestart")
                self.txt.tag_add(tag_name, line_start, "end-1c")
        else:
            self.txt.insert("end", msg)
        self.txt.config(state="disabled")
        self.txt.see("end")

    def _on_text_click(self, event):
        """Handle clicks on the text widget to select individual files.

        Only works when in Individual mode — batch mode ignores clicks.
        Saves current file's settings before restoring the new file.
        """
        if self.mode_var.get() != "individual" or not self.file_list:
            return

        # First save any pending changes for the currently selected file
        if 0 <= self.selected_file_index < len(self.file_list):
            self._save_current_file_settings()

        idx = self.txt.index(f"@{event.x},{event.y}")
        line_num_str, _ = idx.split(".")
        line_num = int(line_num_str)
        if 1 <= line_num <= len(self.file_list):
            new_idx = line_num - 1
            sel_path = self.file_list[new_idx]

            fs = self.file_settings.get(sel_path)

            if fs and not self.processing:
                # Restore per-file settings into controls — block trace saves mid-restoration
                self._restoring_file = True

                self.dar_str.set(fs['dar'])
                self.remove_subs_var.set(fs['remove_subs'])
                self.delete_originals_var.set(fs.get('delete_originals', False))
                data = getattr(self, '_audio_track_data', {"Keep All": None})
                for display, tid in data.items():
                    if tid == fs['audio_sel']:
                        self.audio_var.set(display)
                        break
                else:
                    self.audio_var.set("Keep All")

                self._restoring_file = False
            elif not self.processing:
                # No per-file override — reset all controls to their defaults
                self._restoring_file = True

                self.dar_str.set(self._dar_last_valid)
                self.audio_var.set("Keep All")
                self.remove_subs_var.set(False)
                self.delete_originals_var.set(False)

                self._restoring_file = False

            self.selected_file_index = new_idx
            self._highlight_selected()
            self.root.update()

    def _highlight_selected(self):
        """Update overlay tags to highlight the selected file."""
        # Remove old overlays
        for tag in ("sel_bg", "sel_fg_green", "sel_fg_blue"):
            try:
                self.txt.tag_lower(tag, "1.0")
            except tk.TclError:
                pass

        # Reset all overlay tags to empty ranges
        for tag in ("sel_bg", "sel_fg_green", "sel_fg_blue"):
            self.txt.tag_remove(tag, "1.0", "end-1c")

        if 0 <= self.selected_file_index < len(self.file_list):
            sel_path = self.file_list[self.selected_file_index]
            line_num = self.selected_file_index + 1
            line_start = f"{line_num}.0"
            line_end = f"{line_num}.end"

            # Yellow-green background for selected file
            self.txt.tag_configure("sel_bg", background="#2d313a")
            self.txt.tag_add("sel_bg", line_start, line_end)

            # Check if this file's stored settings differ from what's currently displayed.
            # Green when different (has override), blue when matching (no override).
            fs = self.file_settings.get(sel_path)
            if fs:
                has_diff = (fs.get('dar') != self.dar_str.get() or
                           fs.get('remove_subs') != self.remove_subs_var.get() or
                           fs.get('audio_sel') != self.audio_var.get())
            else:
                has_diff = False

            # Green text for files with custom settings, blue for global default
            fg_tag = "sel_fg_green" if has_diff else "sel_fg_blue"
            self.txt.tag_configure(fg_tag, foreground="#9ece6a" if has_diff else "#7aa2f7")
            self.txt.tag_add(fg_tag, line_start, line_end)
            # Put foreground tag above background so text stays visible
            try:
                self.txt.tag_raise(fg_tag)
            except tk.TclError:
                pass


# ─── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()

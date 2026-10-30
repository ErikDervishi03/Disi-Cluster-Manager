import fnmatch
import json
import os
import platform
import posixpath
import queue
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import paramiko


APP_NAME = "DISI HPC & Remote Access Manager"
APP_SUBTITLE = "Cluster DISI  ·  Laboratori Ercolani  ·  SLURM"
APP_VERSION = "1.0"
HPC_HOST = "giano.cs.unibo.it"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".hpc_disi_manager.json")
HOME_QUOTA_MB = 400

TEXT_EXTENSIONS = (
    ".py", ".c", ".cpp", ".cc", ".h", ".hpp", ".txt", ".sbatch", ".sh",
    ".out", ".err", ".json", ".md", ".csv", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".log", ".java", ".js", ".html", ".css", ".tex",
)

JOB_TYPES = [
    "Python (GPU)",
    "C/OpenMP (Multi-core CPU)",
    "C/MPI (Multi-nodo CPU)",
    "C/CUDA (GPU Compilata)",
]
PARTITIONS = ["rtx2080", "l40", "N/A (Solo CPU)"]
GPU_PARTITIONS = PARTITIONS[:2]

# Elenco host dei laboratori Ercolani, virtuali e docenti
LAB_MACHINES_DEFAULT = [
    "marullo.cs.unibo.it", "morales.cs.unibo.it", "remendado.cs.unibo.it",
    "roderigo.cs.unibo.it", "dancairo.cs.unibo.it", "moschina.cs.unibo.it",
    "giovanna.cs.unibo.it", "zuniga.cs.unibo.it", "edmondo.cs.unibo.it",
    "altoum.cs.unibo.it", "doncurzio.cs.unibo.it", "pancrazio.cs.unibo.it",
    "lucia.cs.unibo.it", "abigaille.cs.unibo.it", "melot.cs.unibo.it",
    "brangania.cs.unibo.it", "donbasilio.cs.unibo.it", "aremberg.cs.unibo.it",
    "amneris.cs.unibo.it", "arianna.cs.unibo.it", "norina.cs.unibo.it",
    "benes.cs.unibo.it", "berta.cs.unibo.it", "bettina.cs.unibo.it",
    "brander.cs.unibo.it", "dalibor.cs.unibo.it", "donandronico.cs.unibo.it",
    "donbartolo.cs.unibo.it", "donpasquale.cs.unibo.it", "donprocopio.cs.unibo.it",
    "dorina.cs.unibo.it", "douphol.cs.unibo.it", "eboli.cs.unibo.it",
    "edgar.cs.unibo.it", "elisabetta.cs.unibo.it", "ernesto.cs.unibo.it",
    "eufemia.cs.unibo.it", "ferrando.cs.unibo.it", "fidelia.cs.unibo.it",
    "filindo.cs.unibo.it", "fiorello.cs.unibo.it", "frank.cs.unibo.it",
    "grenvil.cs.unibo.it", "gretel.cs.unibo.it", "gualtiero.cs.unibo.it",
    "hansel.cs.unibo.it", "ines.cs.unibo.it", "leonora.cs.unibo.it",
    "lily.cs.unibo.it", "malatesta.cs.unibo.it", "manrico.cs.unibo.it",
    "margherita.cs.unibo.it", "milada.cs.unibo.it", "mingo.cs.unibo.it",
    "rosina.cs.unibo.it",
    # Workstation virtuali laboratorio
    "annina.cs.unibo.it", "nabucco.cs.unibo.it", "eva.cs.unibo.it",
    "maria.cs.unibo.it", "giuseppe.cs.unibo.it", "emilia.cs.unibo.it",
    # Workstation docenti
    "laura.cs.unibo.it", "flora.cs.unibo.it", "magda.cs.unibo.it",
    "marcello.cs.unibo.it", "carmen.cs.unibo.it", "gilda.cs.unibo.it",
    "normanno.cs.unibo.it", "colline.cs.unibo.it", "zerlina.cs.unibo.it",
    "papagena.cs.unibo.it", "maddalena.cs.unibo.it", "donnaelvira.cs.unibo.it",
    "alice.cs.unibo.it",
]

ALL_HOSTS = [HPC_HOST] + LAB_MACHINES_DEFAULT

# ----------------------------- Tema / colori -----------------------------

BASE_BG = "#eef2f7"
CARD_BG = "#ffffff"
NAVY = "#12263f"
NAVY_LIGHT = "#1c3554"
ACCENT = "#1f6feb"
ACCENT_HOVER = "#1558c0"
DANGER = "#c0392b"
DANGER_HOVER = "#962d22"
MUTED = "#6b7785"
BORDER = "#d6dee8"
GREEN = "#1a7f37"
ORANGE = "#b26a00"
RED = "#c0392b"

UI_FONT = "DejaVu Sans"
MONO_FONT = "DejaVu Sans Mono"

ANSI_RE = re.compile(
    r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)"          # OSC
    r"|\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"     # CSI / escape
)


def choose_fonts():
    """Sceglie font disponibili sul sistema, con fallback affidabili."""
    global UI_FONT, MONO_FONT
    try:
        families = set(tkfont.families())
    except Exception:
        return
    ui_candidates = ["Inter", "Segoe UI", "SF Pro Text", "Helvetica Neue",
                     "DejaVu Sans", "Noto Sans", "Liberation Sans"]
    mono_candidates = ["JetBrains Mono", "Cascadia Mono", "Consolas",
                       "SF Mono", "DejaVu Sans Mono", "Noto Sans Mono",
                       "Liberation Mono", "Courier New"]
    for name in ui_candidates:
        if name in families:
            UI_FONT = name
            break
    for name in mono_candidates:
        if name in families:
            MONO_FONT = name
            break


def load_settings():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


def human_size(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{size:.0f} B"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def remote_join(base, name):
    base = (base or ".").strip()
    if name == "..":
        return posixpath.dirname(base.rstrip("/")) or "/"
    if base in ("", "."):
        return f"./{name}" if base == "." else name
    return base.rstrip("/") + "/" + name


def strip_ansi(text):
    return ANSI_RE.sub("", text)


class ToolTip:
    """Piccolo tooltip non invasivo per i pulsanti icona."""

    def __init__(self, widget, text, delay=600):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tk.Label(
                tip, text=self.text, bg="#1f2937", fg="white",
                padx=8, pady=4, font=(UI_FONT, 9), justify="left",
            ).pack()
            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self, _event=None):
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class MainThreadDispatcher:
    """Esegue callback sulla GUI partendo da thread di lavoro in modo sicuro."""

    def __init__(self, widget, interval=40):
        self.widget = widget
        self.interval = interval
        self.queue = queue.Queue()
        self.running = True
        self._after_id = None
        self._schedule()

    def _schedule(self):
        if not self.running:
            return
        try:
            self._after_id = self.widget.after(self.interval, self._drain)
        except Exception:
            self._after_id = None

    def _drain(self):
        self._after_id = None
        if not self.running:
            return
        while True:
            try:
                callback = self.queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                traceback.print_exc()
        self._schedule()

    def call(self, callback):
        if self.running:
            self.queue.put(callback)

    def stop(self):
        self.running = False
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None


class InteractiveTerminalWindow(tk.Toplevel):
    """Shell SSH integrata nell'applicazione (nessun terminale esterno)."""

    SPECIAL_KEYS = {
        "Return": "\r", "KP_Enter": "\r",
        "BackSpace": "\x7f", "Tab": "\t", "ISO_Left_Tab": "\x1b[Z",
        "Escape": "\x1b", "Delete": "\x1b[3~",
        "Up": "\x1b[A", "Down": "\x1b[B", "Right": "\x1b[C", "Left": "\x1b[D",
        "Home": "\x1b[H", "End": "\x1b[F",
        "Prior": "\x1b[5~", "Next": "\x1b[6~", "Insert": "\x1b[2~",
    }
    IGNORED_KEYS = {
        "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
        "Caps_Lock", "Num_Lock", "Super_L", "Super_R", "Meta_L", "Meta_R",
        "Menu", "Pause", "Scroll_Lock",
    }

    def __init__(self, parent, ssh_client, host_name, username):
        super().__init__(parent)
        self.title(f"Shell SSH  ·  {username}@{host_name}")
        self.geometry("920x580")
        self.minsize(560, 340)
        self.configure(bg="#0f1115")

        self.ssh_client = ssh_client
        self.host_name = host_name
        self.username = username
        self.running = True
        self._buffer = []
        self._flush_id = None
        self._flush_pending = False
        self._resize_id = None
        self._font_size = 10
        self._dispatcher = MainThreadDispatcher(self)

        self._build_toolbar()

        self.txt_term = scrolledtext.ScrolledText(
            self, bg="#0f1115", fg="#e6edf3", insertbackground="#e6edf3",
            selectbackground="#264f78", font=(MONO_FONT, self._font_size),
            wrap=tk.CHAR, padx=10, pady=8, relief=tk.FLAT, borderwidth=0,
        )
        self.txt_term.pack(fill=tk.BOTH, expand=True)

        self._build_menu()
        self.bind("<Button-1>", self._close_menu, add="+")
        self.txt_term.bind("<Key>", self._on_key_press)
        self.txt_term.bind("<Control-Shift-C>", lambda e: self._copy_selection())
        self.txt_term.bind("<Control-Shift-V>", lambda e: self._paste_clipboard())
        self.txt_term.bind("<Command-c>", lambda e: self._copy_selection())
        self.txt_term.bind("<Command-v>", lambda e: self._paste_clipboard())
        self.txt_term.bind("<Button-2>", self._show_context_menu)
        self.txt_term.bind("<Button-3>", self._show_context_menu)
        self.txt_term.bind("<Configure>", self._on_terminal_resize)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Destroy>", self._on_destroy)

        try:
            self.chan = ssh_client.invoke_shell(term="dumb", width=100, height=30)
        except Exception as exc:
            messagebox.showerror(
                "Shell SSH", f"Impossibile aprire la shell:\n{exc}", parent=self
            )
            self.destroy()
            return

        self.after(100, lambda: self.txt_term.focus_set())
        threading.Thread(target=self._listen_shell, daemon=True).start()
        self._set_status("Connesso")

    # -------- costruzione interfaccia --------
    def _build_toolbar(self):
        bar = tk.Frame(self, bg=NAVY, padx=10, pady=7)
        bar.pack(fill=tk.X)
        tk.Label(
            bar, text=f"● {self.username}@{self.host_name}", bg=NAVY,
            fg="#7ee787", font=(UI_FONT, 10, "bold"),
        ).pack(side=tk.LEFT)
        self.lbl_shell_status = tk.Label(
            bar, text="", bg=NAVY, fg="#aeb9c9", font=(UI_FONT, 9)
        )
        self.lbl_shell_status.pack(side=tk.LEFT, padx=12)

        for label, command, tip in (
            ("Pulisci", self._clear, "Svuota il terminale (solo schermo)"),
            ("Ctrl+C", lambda: self._send("\x03"), "Interrompi il comando corrente"),
            ("Incolla", self._paste_clipboard, "Incolla dagli appunti (Ctrl+Shift+V)"),
            ("Copia", self._copy_selection, "Copia la selezione (Ctrl+Shift+C)"),
            ("A-", lambda: self._change_font(-1), "Riduci carattere"),
            ("A+", lambda: self._change_font(1), "Ingrandisci carattere"),
        ):
            btn = tk.Button(
                bar, text=label, command=command, bg=NAVY_LIGHT, fg="#e6edf3",
                activebackground=ACCENT, activeforeground="white",
                relief=tk.FLAT, padx=9, pady=3, font=(UI_FONT, 9),
                cursor="hand2", borderwidth=0,
            )
            btn.pack(side=tk.RIGHT, padx=2)
            ToolTip(btn, tip)

    def _build_menu(self):
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Copia", command=self._copy_selection)
        self.menu.add_command(label="Incolla", command=self._paste_clipboard)
        self.menu.add_separator()
        self.menu.add_command(label="Seleziona tutto", command=self._select_all)
        self.menu.add_command(label="Pulisci schermo", command=self._clear)

    # -------- azioni toolbar --------
    def _set_status(self, text):
        try:
            self.lbl_shell_status.config(text=text)
        except Exception:
            pass

    def _change_font(self, delta):
        self._font_size = max(7, min(20, self._font_size + delta))
        self.txt_term.configure(font=(MONO_FONT, self._font_size))

    def _send(self, data):
        if not self.running or self.chan.closed:
            return
        try:
            self.chan.send(data)
        except Exception:
            pass

    def _copy_selection(self):
        try:
            text = self.txt_term.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("Selezione copiata")
        self.after(1500, lambda: self._set_status("Connesso"))
        return "break"

    def _paste_clipboard(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        if text:
            self._send(text.replace("\r\n", "\n"))
        return "break"

    def _select_all(self):
        self.txt_term.tag_add(tk.SEL, "1.0", tk.END)
        self.txt_term.mark_set(tk.INSERT, "1.0")
        return "break"

    def _clear(self):
        self.txt_term.delete("1.0", tk.END)
        self._set_status("Schermo pulito")

    def _show_context_menu(self, event):
        self._close_menu()
        self.menu.post(event.x_root, event.y_root)

    def _close_menu(self, _event=None):
        try:
            self.menu.unpost()
        except Exception:
            pass

    # -------- tastiera --------
    def _on_key_press(self, event):
        if not self.running or self.chan.closed:
            return "break"

        if event.keysym == "Escape" and self.menu.winfo_ismapped():
            self._close_menu()
            return "break"

        # Ctrl+Shift+C / Ctrl+Shift+V: copia e incolla locali
        if (event.state & 0x4) and (event.state & 0x1):
            key = event.keysym.lower()
            if key == "c":
                return self._copy_selection()
            if key == "v":
                return self._paste_clipboard()

        # Ctrl+lettera -> carattere di controllo
        if event.state & 0x4:
            if event.keysym in ("c", "C"):
                self._send("\x03")
                return "break"
            if event.char and event.char.isalpha():
                self._send(chr(ord(event.char.lower()) - 96))
                return "break"
            if event.keysym == "space":
                self._send("\x00")
                return "break"

        if event.keysym in self.IGNORED_KEYS:
            return "break"

        char_to_send = self.SPECIAL_KEYS.get(event.keysym)
        if char_to_send is None:
            if event.char:
                char_to_send = event.char
            else:
                return "break"

        self._send(char_to_send)
        return "break"

    # -------- lettura output --------
    def _listen_shell(self):
        while self.running and not self.chan.closed:
            try:
                if self.chan.recv_ready():
                    data = self.chan.recv(8192).decode("utf-8", errors="ignore")
                    clean = strip_ansi(data)
                    clean = clean.replace("\r\n", "\n").replace("\r", "\n")
                    if clean:
                        self._queue_write(clean)
                else:
                    time.sleep(0.02)
            except Exception:
                break
        if self.running:
            self._queue_write("\n--- Connessione shell interrotta ---\n")

    def _queue_write(self, text):
        if not self.running:
            return
        self._buffer.append(text)
        if not self._flush_pending:
            self._flush_pending = True
            self._dispatcher.call(self._flush)

    def _flush(self):
        self._flush_pending = False
        if not self._buffer or not self.running:
            self._buffer.clear()
            return
        text = "".join(self._buffer)
        self._buffer.clear()
        self._append_text(text)

    def _append_text(self, text):
        if not text:
            return
        try:
            if "\x08" in text:
                for index, part in enumerate(text.split("\x08")):
                    if index > 0 and len(self.txt_term.get("1.0", tk.END)) > 1:
                        self.txt_term.delete("end-2c", "end-1c")
                    self.txt_term.insert(tk.END, part)
            else:
                self.txt_term.insert(tk.END, text)
            self.txt_term.see(tk.END)
        except Exception:
            pass

    # -------- ridimensionamento --------
    def _on_terminal_resize(self, _event=None):
        if self._resize_id:
            try:
                self.after_cancel(self._resize_id)
            except Exception:
                pass
        self._resize_id = self.after(250, self._apply_resize)

    def _apply_resize(self):
        self._resize_id = None
        if not self.running or self.chan.closed:
            return
        try:
            font = tkfont.Font(font=self.txt_term.cget("font"))
            char_w = max(1, font.measure("M"))
            line_h = max(1, font.metrics("linespace"))
            cols = max(20, (self.txt_term.winfo_width() - 20) // char_w)
            rows = max(5, (self.txt_term.winfo_height() - 16) // line_h)
            self.chan.resize_pty(width=cols, height=rows)
        except Exception:
            pass

    def _on_close(self):
        self.running = False
        if self._flush_id:
            try:
                self.after_cancel(self._flush_id)
            except Exception:
                pass
        if self._resize_id:
            try:
                self.after_cancel(self._resize_id)
            except Exception:
                pass
        try:
            self.chan.close()
        except Exception:
            pass
        self._dispatcher.stop()
        self.destroy()

    def _on_destroy(self, event):
        if event.widget is self:
            self._dispatcher.stop()


class TextSearchBar(ttk.Frame):
    """Barra di ricerca riutilizzabile per widget Text.

    Evidenzia tutte le occorrenze e permette di spostarsi tra esse senza
    ripetere la ricerca a ogni clic.
    """

    MAX_MATCHES = 2000
    MATCH_TAG = "ts_match"
    CURRENT_TAG = "ts_current"

    def __init__(self, parent, text_widget, pack_kwargs=None, on_status=None,
                 on_show=None, on_hide=None):
        super().__init__(parent)
        self.text_widget = text_widget
        self._pack_kwargs = dict(pack_kwargs or {"fill": tk.X})
        self._on_status = on_status
        self._on_show = on_show
        self._on_hide = on_hide
        self._matches = []
        self._current = -1
        self._last_needle = ""
        self._debounce_id = None
        self._visible = False
        self._truncated = False

        ttk.Label(self, text="Cerca:").pack(side=tk.LEFT)
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=36)
        self.entry.pack(side=tk.LEFT, padx=(6, 6))
        self.lbl_count = ttk.Label(self, text="", style="Muted.TLabel", width=11)
        self.lbl_count.pack(side=tk.LEFT)
        self.btn_prev = ttk.Button(
            self, text="◀", width=3, command=self.previous
        )
        self.btn_prev.pack(side=tk.LEFT, padx=(6, 0))
        self.btn_next = ttk.Button(
            self, text="▶", width=3, command=self.next
        )
        self.btn_next.pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(self, text="Chiudi", command=self.hide).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ToolTip(self.btn_prev, "Occorrenza precedente (Shift+Invio)")
        ToolTip(self.btn_next, "Occorrenza successiva (Invio)")

        self.entry.bind("<Return>", lambda _e: self.next())
        self.entry.bind("<Shift-Return>", lambda _e: self.previous())
        self.entry.bind("<Escape>", lambda _e: self.hide())
        self.var.trace_add("write", self._on_var_change)
        self.bind("<Destroy>", self._on_destroy)

        self.text_widget.tag_configure(
            self.MATCH_TAG, background="#ffe9a8", foreground="#0f1115"
        )
        self.text_widget.tag_configure(
            self.CURRENT_TAG, background="#f0b72f", foreground="#0f1115"
        )

    # -------- visibilità --------
    def show(self, _event=None):
        self._visible = True
        try:
            self.pack(**self._pack_kwargs)
        except Exception:
            self.pack(fill=tk.X)
        try:
            self.entry.focus_set()
            self.entry.selection_range(0, tk.END)
        except tk.TclError:
            pass
        if self._on_show:
            try:
                self._on_show()
            except Exception:
                pass
        if self.var.get().strip():
            self._refresh_matches()
        else:
            self._update_count()
        return "break"

    def hide(self, _event=None):
        self._cancel_debounce()
        self._clear_tags()
        try:
            self.pack_forget()
        except Exception:
            pass
        self._visible = False
        self._matches = []
        self._current = -1
        self._last_needle = ""
        self._truncated = False
        try:
            self.text_widget.focus_set()
        except tk.TclError:
            pass
        if self._on_hide:
            try:
                self._on_hide()
            except Exception:
                pass
        return "break"

    def invalidate(self):
        """Da chiamare quando il testo cambia dall'esterno."""
        self._matches = []
        self._current = -1
        self._last_needle = ""
        self._clear_tags()
        if self._visible and self.var.get().strip():
            self._cancel_debounce()
            self._debounce_id = self.after(300, self._refresh_matches)
        else:
            self._update_count()

    # -------- ricerca --------
    def _on_var_change(self, *_args):
        self._cancel_debounce()
        self._debounce_id = self.after(250, self._refresh_matches)

    def _on_destroy(self, event):
        if event.widget is self:
            self._cancel_debounce()

    def _cancel_debounce(self):
        if self._debounce_id is not None:
            try:
                self.after_cancel(self._debounce_id)
            except Exception:
                pass
            self._debounce_id = None

    def _clear_tags(self):
        try:
            self.text_widget.tag_remove(self.MATCH_TAG, "1.0", tk.END)
            self.text_widget.tag_remove(self.CURRENT_TAG, "1.0", tk.END)
        except tk.TclError:
            pass

    def _find_all(self, needle):
        try:
            raw = self.text_widget.tk.call(
                self.text_widget._w, "search", "-all", "-nocase", "--",
                needle, "1.0", "end",
            )
        except tk.TclError:
            return []
        if isinstance(raw, str):
            try:
                indices = list(self.text_widget.tk.splitlist(raw))
            except tk.TclError:
                return []
        else:
            indices = list(raw)
        self._truncated = len(indices) > self.MAX_MATCHES
        return indices[: self.MAX_MATCHES]

    def _refresh_matches(self):
        self._debounce_id = None
        if not self._visible:
            return
        needle = self.var.get()
        self._clear_tags()
        if needle != self._last_needle:
            self._current = -1
        self._last_needle = needle
        if not needle.strip():
            self._matches = []
            self._current = -1
            self._update_count()
            return

        indices = self._find_all(needle)
        self._matches = [
            (index, f"{index}+{len(needle)}c") for index in indices
        ]
        for start, end in self._matches:
            try:
                self.text_widget.tag_add(self.MATCH_TAG, start, end)
            except tk.TclError:
                break
        if self._matches:
            if not (0 <= self._current < len(self._matches)):
                self._current = 0
            self._focus_current()
            if self._on_status:
                try:
                    total = len(self._matches)
                    extra = "+" if self._truncated else ""
                    self._on_status(
                        f"{total}{extra} occorrenze di «{needle}»"
                    )
                except Exception:
                    pass
        else:
            self._current = -1
            self._update_count()
            if self._on_status:
                try:
                    self._on_status(f"Nessuna occorrenza di «{needle}»")
                except Exception:
                    pass

    def _focus_current(self):
        if not self._matches:
            return
        try:
            self.text_widget.tag_remove(self.CURRENT_TAG, "1.0", tk.END)
        except tk.TclError:
            return
        start, end = self._matches[self._current]
        try:
            self.text_widget.tag_add(self.CURRENT_TAG, start, end)
            self.text_widget.see(start)
        except tk.TclError:
            return
        self._update_count()

    def _update_count(self):
        total = len(self._matches)
        if not self.var.get().strip():
            text = ""
        elif total == 0:
            text = "0/0"
        else:
            current = self._current + 1 if self._current >= 0 else 0
            extra = "+" if self._truncated else ""
            text = f"{current}/{total}{extra}"
        try:
            self.lbl_count.config(text=text)
        except tk.TclError:
            pass

    def next(self, _event=None):
        if not self._visible:
            self.show()
            return "break"
        if self._last_needle != self.var.get() or not self._matches:
            self._refresh_matches()
            return "break"
        self._current = (self._current + 1) % len(self._matches)
        self._focus_current()
        return "break"

    def previous(self, _event=None):
        if not self._visible:
            self.show()
            return "break"
        if self._last_needle != self.var.get() or not self._matches:
            self._refresh_matches()
            return "break"
        self._current = (self._current - 1) % len(self._matches)
        self._focus_current()
        return "break"


class RemoteEditorWindow(tk.Toplevel):
    """Editor remoto con salvataggio diretto via SFTP."""

    def __init__(self, parent, sftp_client, remote_path, sftp_lock=None):
        super().__init__(parent)
        self.sftp_client = sftp_client
        self.remote_path = remote_path
        self.sftp_lock = sftp_lock or threading.Lock()
        self._dirty = False
        self._loading = False
        self._dispatcher = MainThreadDispatcher(self)

        self.title(f"Editor remoto · {os.path.basename(remote_path)}")
        self.geometry("900x650")
        self.minsize(560, 360)
        self.configure(bg=BASE_BG)

        # Header
        header = tk.Frame(self, bg=NAVY, padx=14, pady=10)
        header.pack(fill=tk.X)
        self.lbl_title = tk.Label(
            header, text=os.path.basename(remote_path), bg=NAVY, fg="white",
            font=(UI_FONT, 12, "bold"),
        )
        self.lbl_title.pack(side=tk.LEFT)
        tk.Label(
            header, text=remote_path, bg=NAVY, fg="#aeb9c9", font=(UI_FONT, 9)
        ).pack(side=tk.LEFT, padx=12)

        # Toolbar
        toolbar = ttk.Frame(self, padding=(12, 8))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Ricarica", command=self.reload_file).pack(side=tk.LEFT)
        ttk.Button(
            toolbar, text="Salva sul server", style="Accent.TButton",
            command=self.save_file,
        ).pack(side=tk.LEFT, padx=8)
        self.wrap_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar, text="A capo automatico", variable=self.wrap_var,
            command=self._toggle_wrap,
        ).pack(side=tk.LEFT, padx=12)
        ttk.Label(
            toolbar, text="Ctrl+S per salvare", style="Muted.TLabel"
        ).pack(side=tk.RIGHT)

        # Editor + scrollbar
        body = ttk.Frame(self, padding=(12, 0, 12, 8))
        body.pack(fill=tk.BOTH, expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.txt_editor = tk.Text(
            body, wrap=tk.NONE, undo=True, font=(MONO_FONT, 11),
            bg=CARD_BG, fg="#1f2937", insertbackground="#1f2937",
            selectbackground="#cfe0ff", padx=10, pady=8,
            relief=tk.SOLID, borderwidth=1, highlightthickness=0,
        )
        vbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.txt_editor.yview)
        hbar = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.txt_editor.xview)
        self.txt_editor.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.txt_editor.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.txt_editor.bind("<<Modified>>", self._on_modified)
        self.txt_editor.bind("<Control-s>", lambda e: self.save_file())

        # Status bar
        status = ttk.Frame(self, style="StatusBar.TFrame", padding=(12, 6))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Caricamento...")
        ttk.Label(
            status, textvariable=self.status_var, style="StatusBar.TLabel"
        ).pack(side=tk.LEFT)

        self.search = TextSearchBar(
            self, self.txt_editor,
            pack_kwargs={
                "fill": tk.X, "padx": 12, "pady": (0, 6), "before": body,
            },
            on_status=self._set_status,
        )
        ttk.Button(
            toolbar, text="Cerca (Ctrl+F)", command=self.search.show
        ).pack(side=tk.LEFT, padx=12)
        self.bind("<Control-f>", lambda _e: self.search.show())
        self.bind("<F3>", lambda _e: self.search.next())
        self.bind("<Shift-F3>", lambda _e: self.search.previous())

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Destroy>", self._on_destroy)
        self.load_file()

    def _on_destroy(self, event):
        if event.widget is self:
            self._dispatcher.stop()

    # -------- helpers --------
    def _set_status(self, text):
        try:
            self.status_var.set(text)
        except Exception:
            pass

    def _update_title(self):
        marker = "* " if self._dirty else ""
        try:
            self.title(f"{marker}Editor remoto · {os.path.basename(self.remote_path)}")
            self.lbl_title.config(text=marker + os.path.basename(self.remote_path))
        except Exception:
            pass

    def _call(self, fn):
        self._dispatcher.call(fn)

    def _toggle_wrap(self):
        self.txt_editor.configure(wrap=tk.WORD if self.wrap_var.get() else tk.NONE)

    def _on_modified(self, _event=None):
        if self._loading:
            return
        if self.txt_editor.edit_modified():
            self._dirty = True
            self._update_title()
            self.txt_editor.edit_modified(False)
            if hasattr(self, "search"):
                self.search.invalidate()

    # -------- caricamento / salvataggio --------
    def load_file(self):
        self._loading = True
        self._set_status("Caricamento dal server...")

        def work():
            with self.sftp_lock:
                with self.sftp_client.file(self.remote_path, "r") as fh:
                    return fh.read().decode("utf-8", errors="replace")

        def done(content):
            self._loading = True
            self.txt_editor.delete("1.0", tk.END)
            self.txt_editor.insert("1.0", content)
            self.txt_editor.edit_reset()
            self.txt_editor.edit_modified(False)
            self._dirty = False
            self._loading = False
            self._update_title()
            if hasattr(self, "search"):
                self.search.invalidate()
            lines = content.count("\n") + 1
            self._set_status(f"Caricato · {lines} righe · {human_size(len(content))}")

        def failed(exc):
            self._loading = False
            messagebox.showerror("Errore di lettura", str(exc), parent=self)
            self._set_status("Errore di lettura")
            self.destroy()

        def runner():
            try:
                result = work()
            except Exception as exc:
                self._call(lambda e=exc: failed(e))
            else:
                self._call(lambda r=result: done(r))

        threading.Thread(target=runner, daemon=True).start()

    def reload_file(self):
        if self._dirty and not messagebox.askyesno(
            "Ricarica", "Le modifiche non salvate andranno perse. Continuare?", parent=self
        ):
            return
        self.load_file()

    def save_file(self, close_after=False):
        content = self.txt_editor.get("1.0", "end-1c")
        self._set_status("Salvataggio sul server...")

        def work():
            with self.sftp_lock:
                with self.sftp_client.file(self.remote_path, "w") as fh:
                    fh.write(content.encode("utf-8"))
            return len(content.encode("utf-8"))

        def done(size):
            self._dirty = False
            self.txt_editor.edit_modified(False)
            self._update_title()
            self._set_status(f"Salvato · {datetime.now().strftime('%H:%M:%S')} · {human_size(size)}")
            if close_after:
                self.destroy()

        def failed(exc):
            messagebox.showerror("Errore di scrittura", str(exc), parent=self)
            self._set_status("Errore di salvataggio")

        def runner():
            try:
                result = work()
            except Exception as exc:
                self._call(lambda e=exc: failed(e))
            else:
                self._call(lambda r=result: done(r))

        threading.Thread(target=runner, daemon=True).start()

    def _on_close(self):
        if self._dirty:
            choice = messagebox.askyesnocancel(
                "Modifiche non salvate",
                "Vuoi salvare le modifiche sul server prima di chiudere?",
                parent=self,
            )
            if choice is None:
                return
            if choice:
                self.save_file(close_after=True)
                return
        self.destroy()


class HPCManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME}  ·  v{APP_VERSION}")
        self.root.geometry("1180x800")
        self.root.minsize(1000, 660)
        self.root.configure(bg=BASE_BG)

        self.settings = load_settings()

        self.ssh_client = None
        self.sftp_client = None
        self.connected = False
        self.current_user = ""
        self.current_host = ""
        self.is_hpc_node = False

        self._sftp_lock = threading.Lock()
        self._busy_count = 0
        self._closing = False
        self._connecting = False
        self._squeue_inflight = False
        self._squeue_reload = False
        self._quota_inflight = False
        self._jobs_auto_id = None
        self._jobs_menu_tree = None
        self._details_win = None
        self._history_rows = []
        self._history_paths = {}
        self._history_label = "7 giorni"
        self._history_truncated = False
        self._history_loaded = False
        self._history_fetched_at = 0.0
        self._history_source = None
        self._sacct_available = None
        self._sacct_retry_at = 0.0
        self._log_poll_id = None
        self._log_token = 0
        self._auto_output_retry_id = None
        self._files_token = 0
        self._dir_items = {}
        self._file_item_order = []
        self._file_up_item = None
        self._filtered_item_ids = []
        self._filter_after = None
        self._last_filter_pattern = None
        self._last_file_tree_path = None
        self._folder_size_cache = {}
        self._preview_after = None
        self._temp_dir = None

        self.current_log_path = None
        self.current_log_size = 0
        self._log_paths = {}
        self._log_waiting = False
        self._log_search_active = False

        self.dispatcher = MainThreadDispatcher(self.root)
        self._setup_style()
        self._build_ui()
        self._restore_settings()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<F5>", self._on_refresh_shortcut)
        self.root.report_callback_exception = self._report_exception

    # ----------------------------- tema -----------------------------
    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", font=(UI_FONT, 10), background=BASE_BG, foreground="#1f2937")
        style.configure("TFrame", background=BASE_BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("TLabel", background=BASE_BG, foreground="#1f2937")
        style.configure("Muted.TLabel", foreground=MUTED, font=(UI_FONT, 9))
        style.configure("Section.TLabel", font=(UI_FONT, 10, "bold"), foreground=NAVY)
        style.configure("Guide.TLabel", background="#e3ebf7", foreground="#29476f",
                        font=(UI_FONT, 9), padding=(12, 8))
        style.configure("StatusBar.TFrame", background="#dfe6ef")
        style.configure("StatusBar.TLabel", background="#dfe6ef", foreground="#415064",
                        font=(UI_FONT, 9))
        style.configure("StatusStrong.TLabel", background="#dfe6ef", foreground=NAVY,
                        font=(UI_FONT, 9, "bold"))
        style.configure("TButton", padding=(10, 6), font=(UI_FONT, 9))
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        font=(UI_FONT, 10, "bold"), padding=(16, 9), borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER), ("disabled", "#9db8e8")],
                  foreground=[("disabled", "#f0f4ff")])
        style.configure("Danger.TButton", background=DANGER, foreground="white",
                        font=(UI_FONT, 9), padding=(10, 6), borderwidth=0)
        style.map("Danger.TButton",
                  background=[("active", DANGER_HOVER), ("disabled", "#d8a39d")])
        style.configure("DangerOutline.TButton", background=DANGER,
                        foreground="white", font=(UI_FONT, 9), padding=(10, 6),
                        borderwidth=1, bordercolor="#000000")
        style.map("DangerOutline.TButton",
                  background=[("active", DANGER_HOVER), ("disabled", "#d8a39d")],
                  bordercolor=[("active", "#000000"), ("pressed", "#000000")])

        # Pulsanti compatti per le barre degli strumenti.
        style.configure("Toolbar.TButton", background="#f7f9fc", foreground="#33475e",
                        font=(UI_FONT, 9), padding=(10, 6), borderwidth=1,
                        bordercolor=BORDER)
        style.map("Toolbar.TButton",
                  background=[("pressed", "#dbe7ff"), ("active", "#e9f1fb"),
                              ("disabled", "#f4f6f9")],
                  foreground=[("disabled", "#9aa7b8")],
                  bordercolor=[("active", ACCENT), ("pressed", ACCENT)])
        style.configure("DangerGhost.TButton", background="#fff7f6", foreground=DANGER,
                        font=(UI_FONT, 9, "bold"), padding=(10, 6),
                        borderwidth=1, bordercolor="#e7c3bd")
        style.map("DangerGhost.TButton",
                  background=[("pressed", "#ffd9d3"), ("active", "#ffe7e3"),
                              ("disabled", "#f7f7f7")],
                  foreground=[("disabled", "#c9a7a2")],
                  bordercolor=[("active", DANGER), ("pressed", DANGER)])
        style.configure("Accent.TMenubutton", background=ACCENT, foreground="white",
                        font=(UI_FONT, 9, "bold"), padding=(12, 7), borderwidth=0)
        style.map("Accent.TMenubutton",
                  background=[("active", ACCENT_HOVER), ("disabled", "#9db8e8")],
                  foreground=[("disabled", "#f0f4ff")])

        style.configure("CardMuted.TLabel", background=CARD_BG, foreground=MUTED,
                        font=(UI_FONT, 9))
        style.configure("CardSection.TLabel", background=CARD_BG, foreground=NAVY,
                        font=(UI_FONT, 10, "bold"))
        style.configure("CardValue.TLabel", background=CARD_BG, foreground="#1f2937",
                        font=(UI_FONT, 9))
        style.configure("CardValueBold.TLabel", background=CARD_BG, foreground=NAVY,
                        font=(UI_FONT, 9, "bold"))
        style.configure("CardValueMono.TLabel", background=CARD_BG, foreground="#1f2937",
                        font=(MONO_FONT, 9))
        style.configure("LiveMono.TLabel", background=BASE_BG, foreground="#1f2937",
                        font=(MONO_FONT, 9))
        style.configure("QuotaValue.TLabel", background=CARD_BG, foreground="#1f2937",
                        font=(UI_FONT, 10, "bold"))
        style.configure("Card.TCheckbutton", background=CARD_BG, font=(UI_FONT, 9))
        style.map("Card.TCheckbutton", background=[("active", CARD_BG)])
        style.configure("Path.TEntry", padding=6, fieldbackground="#f8fafc",
                        foreground="#1f2937", bordercolor=BORDER)

        for quota_style, quota_color in (
            ("QuotaGreen", GREEN), ("QuotaOrange", ORANGE), ("QuotaRed", RED)
        ):
            style.configure(
                f"{quota_style}.Horizontal.TProgressbar",
                troughcolor="#e4eaf3", background=quota_color,
                bordercolor="#e4eaf3", lightcolor=quota_color,
                darkcolor=quota_color, thickness=10,
            )

        style.configure("TEntry", padding=5)
        style.configure("TCombobox", padding=3)
        style.configure("TSpinbox", padding=3)
        style.configure("TLabelframe", background=BASE_BG, bordercolor=BORDER,
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=BASE_BG, foreground=NAVY,
                        font=(UI_FONT, 10, "bold"))
        style.configure("Card.TLabelframe", background=CARD_BG, bordercolor=BORDER,
                        relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=CARD_BG, foreground=NAVY,
                        font=(UI_FONT, 10, "bold"))
        style.configure("TNotebook", background=BASE_BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        style.configure("TNotebook.Tab", padding=(18, 9), font=(UI_FONT, 10, "bold"),
                        background="#e1e8f2", foreground="#4b5b6f", borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD_BG), ("active", "#edf2fa")],
                  foreground=[("selected", ACCENT), ("disabled", "#9aa7b8")])
        style.configure("Treeview", rowheight=27, background=CARD_BG,
                        fieldbackground=CARD_BG, foreground="#1f2937", borderwidth=0)
        style.configure("Treeview.Heading", font=(UI_FONT, 9, "bold"),
                        background="#e8eef6", foreground="#33475e", padding=(6, 6))
        style.map("Treeview.Heading", background=[("active", "#dbe6f4")])
        style.map("Treeview", background=[("selected", "#dbe7ff")],
                  foreground=[("selected", "#0b1f3a")])
        style.configure("TCheckbutton", background=BASE_BG)
        style.configure("TRadiobutton", background=BASE_BG, font=(UI_FONT, 10))
        style.configure("Mode.TRadiobutton", font=(UI_FONT, 10, "bold"))
        style.configure("Vertical.TScrollbar", background="#cdd8e5", troughcolor=BASE_BG)
        style.configure("Horizontal.TScrollbar", background="#cdd8e5", troughcolor=BASE_BG)

    # ----------------------------- struttura -----------------------------
    def _build_ui(self):
        self._build_header()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=(12, 8))
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.tab_conn = ttk.Frame(self.notebook, padding=14)
        self.tab_files = ttk.Frame(self.notebook, padding=12)
        self.tab_slurm = ttk.Frame(self.notebook, padding=12)
        self.tab_jobs = ttk.Frame(self.notebook, padding=12)
        self.tab_output = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.tab_conn, text="1 · Connessione")
        self.notebook.add(self.tab_files, text="2 · File & Spazio")
        self.notebook.add(self.tab_slurm, text="3 · Nuovo Job")
        self.notebook.add(self.tab_jobs, text="4 · Job")
        self.notebook.add(self.tab_output, text="5 · Output Job")

        self._build_conn_tab()
        self._build_files_tab()
        self._build_slurm_tab()
        self._build_jobs_tab()
        self._build_output_tab()
        self._build_statusbar()

        self._set_tabs_enabled(False)

        # Chiude i menu contestuali con un clic sinistro o con Esc
        self.root.bind("<Button-1>", self._close_context_menus, add="+")
        self.root.bind("<Escape>", self._close_context_menus, add="+")
        self.root.bind("<Control-f>", self._on_global_search, add="+")
        self.root.bind("<F3>", lambda _e: self._global_log_nav(True), add="+")
        self.root.bind("<Shift-F3>", lambda _e: self._global_log_nav(False), add="+")
        self.root.bind("<Button-2>", self._on_root_context_click, add="+")
        self.root.bind("<Button-3>", self._on_root_context_click, add="+")

    def _close_context_menus(self, _event=None):
        for name in ("file_context_menu", "jobs_menu", "output_menu"):
            menu = getattr(self, name, None)
            if menu is None:
                continue
            try:
                menu.unpost()
            except Exception:
                pass

    def _on_root_context_click(self, event):
        """Chiude i menu aperti se il tasto destro cade fuori dalle liste."""
        trees = (self.tree_files, self.tree_jobs)
        history_tree = getattr(self, "tree_history", None)
        if history_tree is not None:
            trees += (history_tree,)
        if event.widget not in trees and event.widget is not self.txt_output_log:
            self._close_context_menus()

    def _build_header(self):
        header = tk.Frame(self.root, bg=NAVY, padx=18, pady=12)
        header.pack(fill=tk.X)

        left = tk.Frame(header, bg=NAVY)
        left.pack(side=tk.LEFT)
        tk.Label(
            left, text=APP_NAME, bg=NAVY, fg="white",
            font=(UI_FONT, 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left, text=APP_SUBTITLE, bg=NAVY, fg="#aeb9c9", font=(UI_FONT, 9),
        ).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(header, bg=NAVY)
        right.pack(side=tk.RIGHT)
        self.lbl_header_status = tk.Label(
            right, text="●  Disconnesso", bg=NAVY, fg="#ff9b9b",
            font=(UI_FONT, 10, "bold"),
        )
        self.lbl_header_status.pack(anchor="e")
        tk.Label(
            right, text=f"v{APP_VERSION}", bg=NAVY, fg="#7086a3", font=(UI_FONT, 8),
        ).pack(anchor="e", pady=(2, 0))

    def _build_statusbar(self):
        bar = ttk.Frame(self.root, style="StatusBar.TFrame", padding=(14, 6))
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Pronto · non connesso")
        self.conn_var = tk.StringVar(value="Nessuna connessione")
        ttk.Label(bar, textvariable=self.status_var, style="StatusBar.TLabel").pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=110)
        ttk.Label(bar, textvariable=self.conn_var, style="StatusStrong.TLabel").pack(side=tk.RIGHT)

    def _set_tabs_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for index in range(1, 5):
            try:
                self.notebook.tab(index, state=state)
            except Exception:
                pass

    def _set_header_status(self, connected):
        if connected:
            self.lbl_header_status.config(
                text=f"●  {self.current_user}@{self.current_host}", fg="#7ee787"
            )
            self.conn_var.set(f"{self.current_user}@{self.current_host}")
        else:
            self.lbl_header_status.config(text="●  Disconnesso", fg="#ff9b9b")
            self.conn_var.set("Nessuna connessione")

    def _set_status(self, text):
        try:
            self.status_var.set(text)
        except Exception:
            pass

    def _idle_status(self):
        if self.connected:
            return f"Pronto · {self.current_user}@{self.current_host}"
        return "Pronto · non connesso"

    def _begin_busy(self, message):
        self._busy_count += 1
        self._set_status(message)
        if self._busy_count == 1:
            try:
                self.progress.pack(side=tk.RIGHT, padx=(8, 0))
                self.progress.start(12)
            except Exception:
                pass

    def _end_busy(self, message=None):
        self._busy_count = max(0, self._busy_count - 1)
        if self._busy_count == 0:
            try:
                self.progress.stop()
                self.progress.pack_forget()
            except Exception:
                pass
            self._set_status(message if message is not None else self._idle_status())
        elif message:
            self._set_status(message)

    def _call_main(self, fn):
        if self._closing:
            return
        self.dispatcher.call(fn)

    # ----------------------------- connessione -----------------------------
    def _build_conn_tab(self):
        tab = self.tab_conn
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(1, weight=1)

        ttk.Label(
            tab,
            text="1  Scegli la modalita'  ·  2  Inserisci le credenziali  ·  3  Connetti",
            style="Guide.TLabel", anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        # ---- credenziali ----
        card_login = ttk.LabelFrame(tab, text=" Accesso ", padding=16)
        card_login.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=5)
        card_login.columnconfigure(0, weight=1)
        card_login.columnconfigure(1, weight=1)

        ttk.Label(card_login, text="Username unibo").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.ent_user = ttk.Entry(card_login)
        self.ent_user.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        ttk.Label(card_login, text="Password").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        pass_row = ttk.Frame(card_login)
        pass_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        pass_row.columnconfigure(0, weight=1)
        self.ent_pass = ttk.Entry(pass_row, show="*")
        self.ent_pass.grid(row=0, column=0, sticky="ew")
        self.show_pass_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            pass_row, text="Mostra", variable=self.show_pass_var,
            command=self._toggle_password,
        ).grid(row=0, column=1, padx=(8, 0))

        self.remember_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            card_login, text="Ricorda username sul computer",
            variable=self.remember_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 12))

        ttk.Separator(card_login, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=8
        )

        btn_row = ttk.Frame(card_login)
        btn_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.btn_connect = ttk.Button(
            btn_row, text="Connetti", style="Accent.TButton", command=self.connect_ssh
        )
        self.btn_connect.pack(side=tk.LEFT)
        self.btn_disconnect = ttk.Button(
            btn_row, text="Disconnetti", command=self.disconnect, state=tk.DISABLED
        )
        self.btn_disconnect.pack(side=tk.LEFT, padx=8)

        ttk.Label(
            card_login,
            text="Suggerimento: usa lo username Unibo senza @studio.unibo.it.\n"
                 "La password non viene mai salvata su disco.",
            style="Muted.TLabel", justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(14, 0))

        self.conn_detail_var = tk.StringVar(value="Nessun host selezionato.")
        ttk.Label(
            card_login, textvariable=self.conn_detail_var, style="Muted.TLabel",
            justify="left", wraplength=380,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ---- modalita + terminale ----
        card_mode = ttk.LabelFrame(tab, text=" Modalita di connessione ", padding=16)
        card_mode.grid(row=1, column=1, sticky="nsew", padx=(7, 0), pady=5)
        card_mode.columnconfigure(0, weight=1)

        self.conn_mode = tk.StringVar(value="hpc")
        self._add_mode_option(
            card_mode, 0, "hpc", "HPC · Giano",
            "Accedi al cluster per SLURM, /scratch.hpc/ e alle partizioni GPU.",
        )
        self._add_mode_option(
            card_mode, 1, "lab", "Laboratorio · prima macchina libera",
            "Prova automaticamente le workstation Ercolani fino alla prima disponibile.",
        )
        self._add_mode_option(
            card_mode, 2, "manual", "Manuale · scegli tu l'host",
            "Utile per collegarsi a una workstation specifica o a Giano.",
        )

        manual_box = ttk.Frame(card_mode)
        manual_box.grid(row=3, column=0, sticky="ew", padx=(22, 0), pady=(0, 10))
        manual_box.columnconfigure(1, weight=1)
        ttk.Label(manual_box, text="Filtra:").grid(row=0, column=0, sticky="w")
        self.ent_host_filter = ttk.Entry(manual_box, width=18)
        self.ent_host_filter.grid(row=0, column=1, sticky="ew", padx=(6, 10))
        self.ent_host_filter.bind("<KeyRelease>", self._filter_hosts)
        self.combo_manual_host = ttk.Combobox(
            manual_box, values=ALL_HOSTS, state="readonly", width=30
        )
        self.combo_manual_host.grid(row=0, column=2, sticky="ew")
        self.combo_manual_host.set(HPC_HOST)

        ttk.Separator(card_mode, orient="horizontal").grid(
            row=4, column=0, sticky="ew", pady=10
        )
        ttk.Label(card_mode, text="Terminale", style="Section.TLabel").grid(
            row=5, column=0, sticky="w", pady=(0, 4)
        )
        term_row = ttk.Frame(card_mode)
        term_row.grid(row=6, column=0, sticky="ew")
        self.btn_term = ttk.Button(
            term_row, text="Shell integrata", command=self.open_interactive_terminal,
            state=tk.DISABLED,
        )
        self.btn_term.pack(side=tk.LEFT)
        self.btn_term_ext = ttk.Button(
            term_row, text="Terminale esterno", command=self.open_external_terminal,
            state=tk.DISABLED,
        )
        self.btn_term_ext.pack(side=tk.LEFT, padx=8)
        ttk.Label(
            card_mode,
            text="La shell integrata resta dentro l'app; quella esterna usa il\n"
                 "terminale del sistema (con sshpass, se installato).",
            style="Muted.TLabel", justify="left",
        ).grid(row=7, column=0, sticky="w", pady=(6, 0))

        self.ent_pass.bind("<Return>", lambda _e: self.connect_ssh())
        self.ent_user.bind("<Return>", lambda _e: self.ent_pass.focus_set())
        self._on_mode_change()

    def _add_mode_option(self, parent, row, value, title, description):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        ttk.Radiobutton(
            frame, text=title, value=value, variable=self.conn_mode,
            command=self._on_mode_change, style="Mode.TRadiobutton",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame, text=description, style="Muted.TLabel", justify="left",
        ).grid(row=1, column=0, sticky="w", padx=(22, 0))

    def _toggle_password(self):
        self.ent_pass.config(show="" if self.show_pass_var.get() else "*")

    def _on_mode_change(self):
        manual = self.conn_mode.get() == "manual"
        try:
            self.combo_manual_host.config(state="readonly" if manual else "disabled")
            self.ent_host_filter.config(state=tk.NORMAL if manual else tk.DISABLED)
        except Exception:
            pass

    def _filter_hosts(self, _event=None):
        query = self.ent_host_filter.get().strip().lower()
        values = [host for host in ALL_HOSTS if query in host.lower()] if query else ALL_HOSTS
        self.combo_manual_host.config(values=values)
        if values and self.combo_manual_host.get() not in values:
            self.combo_manual_host.set(values[0])

    def _restore_settings(self):
        if self.settings.get("remember", True):
            self.remember_var.set(True)
            self.ent_user.insert(0, self.settings.get("username", ""))
        else:
            self.remember_var.set(False)
        mode = self.settings.get("mode", "hpc")
        if mode in ("hpc", "lab", "manual"):
            self.conn_mode.set(mode)
        host = self.settings.get("manual_host", HPC_HOST)
        if host in ALL_HOSTS:
            self.combo_manual_host.set(host)
        self.show_hidden_var.set(bool(self.settings.get("show_hidden", False)))
        self._on_mode_change()

    # ----------------------------- helper asincroni -----------------------------
    def _run_async(self, work, on_success=None, on_error=None,
                   busy_msg=None, done_msg=None, show_error=True):
        if busy_msg:
            self._begin_busy(busy_msg)

        def runner():
            try:
                result = work()
            except Exception as exc:
                self._call_main(
                    lambda e=exc: self._async_error(e, on_error, busy_msg, show_error)
                )
            else:
                self._call_main(
                    lambda r=result: self._async_success(r, on_success, busy_msg, done_msg)
                )

        threading.Thread(target=runner, daemon=True).start()

    def _async_success(self, result, on_success, busy_msg, done_msg):
        if busy_msg:
            self._end_busy(done_msg)
        elif done_msg:
            self._set_status(done_msg)
        if on_success:
            try:
                on_success(result)
            except Exception:
                traceback.print_exc()

    def _async_error(self, exc, on_error, busy_msg, show_error):
        if busy_msg:
            self._end_busy()
        if on_error:
            try:
                on_error(exc)
            except Exception:
                traceback.print_exc()
            return
        message = str(exc) or exc.__class__.__name__
        if show_error:
            messagebox.showerror("Errore", message)
        self._set_status(f"Errore · {message.splitlines()[0][:120]}")

    # ----------------------------- connessione -----------------------------
    def connect_ssh(self):
        if self._connecting:
            return
        if self.connected:
            if not messagebox.askyesno(
                "Riconnessione",
                "Sei gia connesso.\nVuoi disconnetterti e aprire una nuova connessione?",
            ):
                return
            self.disconnect()
        user = self.ent_user.get().strip()
        password = self.ent_pass.get()
        mode = self.conn_mode.get()

        if not user or not password:
            messagebox.showwarning(
                "Credenziali mancanti", "Inserisci username e password."
            )
            return

        if mode == "hpc":
            hosts_to_try = [HPC_HOST]
        elif mode == "lab":
            hosts_to_try = list(LAB_MACHINES_DEFAULT)
        else:
            manual_host = self.combo_manual_host.get().strip()
            if manual_host not in ALL_HOSTS:
                messagebox.showerror(
                    "Host non valido",
                    f"L'host '{manual_host}' non e riconosciuto.\n"
                    "Seleziona una macchina valida dalla lista.",
                )
                return
            hosts_to_try = [manual_host]

        self._connecting = True
        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.DISABLED)
        self._begin_busy("Connessione in corso...")
        cancel = threading.Event()
        total = len(hosts_to_try)
        auth_failed = object()
        auth_hosts = []

        def try_host(host):
            if cancel.is_set():
                return None
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    host, port=22, username=user, password=password,
                    timeout=4, banner_timeout=8, auth_timeout=8,
                )
            except paramiko.AuthenticationException:
                # Credenziali rifiutate: blocca subito gli altri tentativi.
                auth_hosts.append(host)
                cancel.set()
                try:
                    client.close()
                except Exception:
                    pass
                return auth_failed
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass
                return None
            if cancel.is_set():
                client.close()
                return None
            return client, host

        def worker():
            chosen = None
            done = 0
            workers = 1 if total == 1 else 6
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(try_host, host): host for host in hosts_to_try}
                for future in as_completed(futures):
                    host = futures[future]
                    try:
                        result = future.result()
                    except Exception:
                        result = None
                    done += 1
                    if result is auth_failed:
                        cancel.set()
                        for pending in futures:
                            pending.cancel()
                        break
                    if result:
                        chosen = result
                        cancel.set()
                        for pending in futures:
                            pending.cancel()
                        break
                    if cancel.is_set():
                        continue
                    self._call_main(
                        lambda d=done, h=host, n=total: self._set_status(
                            f"Connessione · tentativo {d}/{n} · {h} non disponibile"
                        )
                    )

            if not chosen:
                if auth_hosts:
                    self._call_main(
                        lambda h=auth_hosts[0]: self._connect_failed(auth=True, host=h)
                    )
                else:
                    self._call_main(lambda: self._connect_failed())
                return

            client, host = chosen
            try:
                sftp = client.open_sftp()
            except Exception as exc:
                try:
                    client.close()
                except Exception:
                    pass
                self._call_main(lambda e=exc: self._connect_failed(str(e)))
                return

            self._call_main(
                lambda: self._connect_finished(client, sftp, host, user)
            )

        threading.Thread(target=worker, daemon=True).start()

    def _connect_finished(self, client, sftp, host, user):
        self._connecting = False
        self.ssh_client = client
        self.sftp_client = sftp
        self.connected = True
        self.current_user = user
        self.current_host = host
        self.is_hpc_node = host == HPC_HOST

        self.btn_connect.config(state=tk.NORMAL, text="Riconnetti")
        self.btn_disconnect.config(state=tk.NORMAL)
        self.btn_term.config(state=tk.NORMAL)
        self.btn_term_ext.config(state=tk.NORMAL)
        self._set_header_status(True)
        self._set_tabs_enabled(True)
        self.conn_detail_var.set(
            f"Connesso a {host}\nUtente: {user}\n"
            f"Cartella HPC: {'/scratch.hpc/' + user if self.is_hpc_node else 'non disponibile'}"
        )

        self.ent_email.delete(0, tk.END)
        self.ent_email.insert(0, user)

        self.path_var.set(".")
        self.combo_outputs["values"] = []
        self._log_paths = {}
        self.current_log_path = None
        self.current_log_size = 0
        self._log_waiting = False
        self._stop_log_polling()
        self.lbl_log_path_var.set("nessuno")
        self._set_output_text(
            "L'ultimo file .out della cartella corrente verra aperto e "
            "aggiornato automaticamente.\n"
            "Fai doppio clic su un job nella scheda «Job» per aprire un log "
            "specifico."
        )

        self.notebook.select(self.tab_files)
        self._end_busy(f"Connesso a {host}")

        self._update_file_action_buttons()
        self.refresh_remote_files()
        self.update_quota_live()
        self.refresh_squeue(silent=True)
        self._schedule_jobs_refresh()
        self._save_current_settings()

    def _connect_failed(self, detail="", auth=False, host=""):
        self._connecting = False
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self._end_busy()
        if auth:
            message = (
                "Autenticazione rifiutata.\n\n"
                + (f"La macchina {host} non accetta queste credenziali.\n\n" if host else "")
                + "Controlla username e password (o il metodo di accesso richiesto).\n"
                  "Per evitare blocchi dell'account non verranno fatti altri tentativi automatici."
            )
            messagebox.showerror("Credenziali non valide", message)
            try:
                self.ent_pass.focus_set()
                self.ent_pass.selection_range(0, tk.END)
            except Exception:
                pass
            self._set_status("Autenticazione fallita · controlla le credenziali")
            return
        message = "Connessione fallita.\nMacchina offline, timeout o credenziali errate."
        if detail:
            message += f"\n\nDettaglio: {detail}"
        messagebox.showerror("Errore di connessione", message)
        self._set_status("Connessione fallita")

    def disconnect(self):
        if self._connecting:
            return
        self._stop_log_polling()
        self._stop_jobs_auto_refresh()

        details = getattr(self, "_details_win", None)
        if details is not None:
            try:
                details.close()
            except Exception:
                pass

        try:
            if self.sftp_client:
                self.sftp_client.close()
        except Exception:
            pass
        try:
            if self.ssh_client:
                self.ssh_client.close()
        except Exception:
            pass

        self.ssh_client = None
        self.sftp_client = None
        self.connected = False
        self.current_user = ""
        self.current_host = ""
        self.is_hpc_node = False
        self.current_log_path = None
        self.current_log_size = 0
        self._log_paths = {}
        self._log_waiting = False
        self._squeue_inflight = False
        self._quota_inflight = False

        self.btn_connect.config(state=tk.NORMAL, text="Connetti")
        self.btn_disconnect.config(state=tk.DISABLED)
        self.btn_term.config(state=tk.DISABLED)
        self.btn_term_ext.config(state=tk.DISABLED)
        self._set_header_status(False)
        self._set_tabs_enabled(False)
        self.conn_detail_var.set("Nessun host selezionato.")
        self.notebook.select(self.tab_conn)

        for tree in (self.tree_files, self.tree_jobs, self.tree_history):
            for item in tree.get_children():
                tree.delete(item)
        self._history_rows = []
        self._history_paths = {}
        self._history_loaded = False
        self._history_fetched_at = 0.0
        self._history_truncated = False
        self._history_source = None
        self._sacct_available = None
        self._sacct_retry_at = 0.0
        self.lbl_jobs_info.config(text="Nessun job.")
        self.lbl_history_info.config(text="Nessun job.")
        self._files_token += 1
        self._dir_items = {}
        self._file_item_order = []
        self._file_up_item = None
        self._filtered_item_ids = []
        self._last_filter_pattern = None
        self._last_file_tree_path = None
        if self._filter_after is not None:
            try:
                self.root.after_cancel(self._filter_after)
            except Exception:
                pass
            self._filter_after = None
        if hasattr(self, "filter_var"):
            self.filter_var.set("")
        if hasattr(self, "lbl_filter_count"):
            self.lbl_filter_count.config(text="")
        if hasattr(self, "btn_filter_select"):
            self.btn_filter_select.config(state=tk.DISABLED)
        self._set_output_text("")
        self.txt_sinfo.delete("1.0", tk.END)
        self.lbl_quota_text.config(text="Connettiti per calcolare lo spazio usato.", foreground=MUTED)
        self.progress_quota["value"] = 0
        self.progress_quota.configure(style="QuotaGreen.Horizontal.TProgressbar")
        self._files_info_base = "Nessun file caricato."
        self._update_file_action_buttons()
        self.lbl_jobs_info.config(text="Nessun job.")
        self.combo_outputs["values"] = []
        self.lbl_log_path_var.set("nessuno")
        self._set_status("Disconnesso")

    # ----------------------------- terminale -----------------------------
    def open_interactive_terminal(self):
        if not self.connected:
            messagebox.showwarning("Terminale", "Connettiti prima a un host.")
            return
        try:
            InteractiveTerminalWindow(
                self.root, self.ssh_client, self.current_host, self.current_user
            )
        except Exception as exc:
            messagebox.showerror("Terminale", f"Impossibile aprire la shell:\n{exc}")

    def open_external_terminal(self):
        if not self.connected:
            return

        user = self.current_user
        host = self.current_host
        password = self.ent_pass.get()
        system = platform.system()
        env = os.environ.copy()
        env["SSHPASS"] = password
        has_sshpass = shutil.which("sshpass") is not None

        target = f"{user}@{host}"
        if has_sshpass:
            ssh_cmd = f"sshpass -e ssh -o StrictHostKeyChecking=no {target}"
        else:
            ssh_cmd = f"ssh -o StrictHostKeyChecking=no {target}"

        try:
            if system == "Windows":
                subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", ssh_cmd], env=env)
            elif system == "Darwin":
                escaped = ssh_cmd.replace('"', '\\"')
                subprocess.Popen(
                    ["osascript", "-e",
                     f'tell application "Terminal" to do script "{escaped}"'],
                    env=env,
                )
            else:
                terminals = [
                    "x-terminal-emulator", "gnome-terminal", "konsole",
                    "xfce4-terminal", "kitty", "alacritty", "xterm",
                ]
                opened = False
                for term in terminals:
                    if not shutil.which(term):
                        continue
                    if term == "gnome-terminal":
                        subprocess.Popen([term, "--", "bash", "-c", f"{ssh_cmd}; exec bash"], env=env)
                    elif term in ("kitty", "alacritty"):
                        subprocess.Popen([term, "-e", "bash", "-c", f"{ssh_cmd}; exec bash"], env=env)
                    else:
                        subprocess.Popen([term, "-e", f"bash -c '{ssh_cmd}; exec bash'"], env=env)
                    opened = True
                    break
                if not opened:
                    messagebox.showerror(
                        "Terminale esterno",
                        "Nessun emulatore di terminale trovato.\n"
                        "Usa la shell integrata dell'app.",
                    )
                    return
            if not has_sshpass:
                messagebox.showinfo(
                    "Login automatico non disponibile",
                    "Installa sshpass (sudo apt install sshpass) per evitare "
                    "di reinserire la password nel terminale esterno.\n\n"
                    "In alternativa usa la Shell integrata.",
                )
        except Exception as exc:
            messagebox.showerror("Errore avvio terminale", str(exc))

    # ----------------------------- schede -----------------------------
    def _on_tab_changed(self, _event=None):
        try:
            index = self.notebook.index(self.notebook.select())
        except Exception:
            return
        if index == 2 and hasattr(self, "lbl_job_dir_var"):
            self.lbl_job_dir_var.set(self._current_path())
            self._refresh_script_preview()
        elif index == 3 and self.connected:
            # Carica lo storico la prima volta che si apre la scheda; gli
            # aggiornamenti successivi avvengono solo col pulsante «Aggiorna».
            self.refresh_squeue(
                silent=True, force_history=not self._history_loaded
            )
        elif index == 4 and self.connected:
            # Aggiorna da solo l'elenco dei .out e segue il log aperto.
            self._auto_load_output()
        else:
            self._stop_output_auto_retry()

    def _on_refresh_shortcut(self, _event=None):
        try:
            index = self.notebook.index(self.notebook.select())
        except Exception:
            return
        if index == 1:
            self.refresh_remote_files()
        elif index == 3:
            self.refresh_squeue(force_history=True)
        elif index == 4:
            self.find_outputs()

    # ----------------------------- TAB 2: FILE -----------------------------
    def _build_files_tab(self):
        tab = self.tab_files
        self.filter_var = tk.StringVar(master=self.root, value="")

        explorer = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
        explorer.pack(fill=tk.BOTH, expand=True)

        # --- barra di navigazione ---
        nav = ttk.Frame(explorer, style="Card.TFrame")
        nav.pack(fill=tk.X)

        btn_home = ttk.Button(
            nav, text="⌂  Home", style="Toolbar.TButton", command=self.go_home
        )
        btn_home.pack(side=tk.LEFT)
        ToolTip(btn_home, "Torna alla home remota")

        btn_up = ttk.Button(
            nav, text="↑  Su", style="Toolbar.TButton", command=self.navigate_up
        )
        btn_up.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(btn_up, "Cartella superiore (Backspace)")

        btn_refresh = ttk.Button(
            nav, text="⟳  Aggiorna", style="Toolbar.TButton",
            command=self.refresh_remote_files,
        )
        btn_refresh.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(btn_refresh, "Aggiorna l'elenco dei file (F5)")

        ttk.Separator(nav, orient="vertical").pack(
            side=tk.LEFT, fill=tk.Y, padx=10, pady=2
        )

        ttk.Label(nav, text="Percorso", style="CardMuted.TLabel").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.path_var = tk.StringVar(value=".")
        self.ent_remote_path = ttk.Entry(
            nav, textvariable=self.path_var, style="Path.TEntry"
        )
        self.ent_remote_path.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.ent_remote_path.bind("<Return>", lambda _e: self.refresh_remote_files())

        btn_go = ttk.Button(
            nav, text="Apri", style="Toolbar.TButton",
            command=self.refresh_remote_files,
        )
        btn_go.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(btn_go, "Apri il percorso scritto (Invio)")

        ttk.Separator(explorer, orient="horizontal").pack(fill=tk.X, pady=(10, 8))

        # --- ricerca per nome ---
        search = ttk.Frame(explorer, style="Card.TFrame")
        search.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(search, text="Cerca per nome", style="CardMuted.TLabel").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.ent_file_filter = ttk.Entry(
            search, textvariable=self.filter_var, style="Path.TEntry"
        )
        self.ent_file_filter.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.ent_file_filter.bind("<KeyRelease>", self._schedule_file_filter)
        self.ent_file_filter.bind("<Escape>", self._on_filter_escape)
        ToolTip(
            self.ent_file_filter,
            "Filtra per nome nella cartella corrente. Supporta * e ? "
            "(es. log*). Premi Esc per cancellare il filtro.",
        )

        self.btn_filter_select = ttk.Button(
            search, text="Seleziona risultati", style="Toolbar.TButton",
            command=self.select_filtered_files, state=tk.DISABLED,
        )
        self.btn_filter_select.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(
            self.btn_filter_select,
            "Seleziona tutti i file e le cartelle che corrispondono al filtro",
        )

        self.lbl_filter_count = ttk.Label(
            search, text="", style="CardMuted.TLabel"
        )
        self.lbl_filter_count.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            search, text="es. log*  ·  *.py", style="CardMuted.TLabel"
        ).pack(side=tk.RIGHT, padx=(8, 0))

        # --- azioni sui file ---
        actions = ttk.Frame(explorer, style="Card.TFrame")
        actions.pack(fill=tk.X)

        self.btn_upload = ttk.Menubutton(
            actions, text="↑  Carica", style="Accent.TMenubutton"
        )
        upload_menu = tk.Menu(self.btn_upload, tearoff=0)
        upload_menu.add_command(label="Carica singolo file", command=self.upload_file)
        upload_menu.add_command(label="Carica intera cartella", command=self.upload_folder)
        self.btn_upload["menu"] = upload_menu
        self.btn_upload.pack(side=tk.LEFT)
        ToolTip(self.btn_upload, "Carica un file o una cartella nella posizione corrente")

        self.btn_download = ttk.Button(
            actions, text="↓  Scarica", style="Toolbar.TButton",
            command=self.download_selected,
        )
        self.btn_download.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(self.btn_download, "Scarica i file e le cartelle selezionati")

        ttk.Separator(actions, orient="vertical").pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=2
        )

        self.btn_edit = ttk.Button(
            actions, text="✎  Modifica", style="Toolbar.TButton",
            command=self.edit_remote_file,
        )
        self.btn_edit.pack(side=tk.LEFT)
        ToolTip(self.btn_edit, "Modifica il file selezionato nell'editor remoto")

        self.btn_new_folder = ttk.Button(
            actions, text="+  Nuova cartella", style="Toolbar.TButton",
            command=self.create_remote_folder,
        )
        self.btn_new_folder.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(self.btn_new_folder, "Crea una nuova cartella nella posizione corrente")

        self.btn_rename = ttk.Button(
            actions, text="Rinomina", style="Toolbar.TButton",
            command=self.rename_remote_item,
        )
        self.btn_rename.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(self.btn_rename, "Rinomina l'elemento selezionato (uno solo)")

        ttk.Separator(actions, orient="vertical").pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=2
        )

        self.btn_delete = ttk.Button(
            actions, text="✕  Elimina", style="DangerGhost.TButton",
            command=self.delete_remote_item,
        )
        self.btn_delete.pack(side=tk.LEFT)
        ToolTip(self.btn_delete, "Elimina definitivamente gli elementi selezionati (Canc)")

        self.show_hidden_var = tk.BooleanVar(value=False)
        chk_hidden = ttk.Checkbutton(
            actions, text="Mostra nascosti", variable=self.show_hidden_var,
            style="Card.TCheckbutton", command=self.refresh_remote_files,
        )
        chk_hidden.pack(side=tk.RIGHT)
        ToolTip(chk_hidden, "Mostra anche i file e le cartelle che iniziano con un punto")

        # --- elenco file ---
        tree_box = ttk.Frame(explorer, style="Card.TFrame")
        tree_box.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        tree_box.rowconfigure(0, weight=1)
        tree_box.columnconfigure(0, weight=1)

        columns = ("name", "type", "size", "modified")
        self.tree_files = ttk.Treeview(
            tree_box, columns=columns, show="headings", selectmode="extended",
            height=6,
        )
        self.tree_files.heading("name", text="Nome")
        self.tree_files.heading("type", text="Tipo")
        self.tree_files.heading("size", text="Dimensione")
        self.tree_files.heading("modified", text="Modificato")
        self.tree_files.column("name", width=430, anchor="w")
        self.tree_files.column("type", width=100, anchor="center", stretch=False)
        self.tree_files.column("size", width=110, anchor="e", stretch=False)
        self.tree_files.column("modified", width=150, anchor="center", stretch=False)
        self.tree_files.tag_configure("dir", foreground=ACCENT)
        self.tree_files.tag_configure("file", foreground="#1f2937")

        vbar = ttk.Scrollbar(tree_box, orient=tk.VERTICAL, command=self.tree_files.yview)
        self.tree_files.configure(yscrollcommand=vbar.set)
        self.tree_files.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")

        self.tree_files.bind("<Double-1>", self.on_tree_double_click)
        self.tree_files.bind("<<TreeviewSelect>>",
                             lambda _e: self._update_file_action_buttons())
        self.tree_files.bind("<Button-3>", self.show_context_menu)
        self.tree_files.bind("<Button-2>", self.show_context_menu)
        self.tree_files.bind("<Return>", self.on_tree_double_click)
        self.tree_files.bind("<Delete>", lambda _e: self.delete_remote_item())
        self.tree_files.bind("<BackSpace>", lambda _e: self.navigate_up())
        self.tree_files.bind("<Control-a>", self.select_all_visible)
        self.tree_files.bind("<Control-A>", self.select_all_visible)

        self.file_context_menu = tk.Menu(self.tree_files, tearoff=0)
        self.file_context_menu.add_command(label="Scarica", command=self.download_selected)
        self.file_context_menu.add_command(label="Modifica nell'editor", command=self.edit_remote_file)
        self.file_context_menu.add_command(label="Copia percorso", command=self.copy_selected_path)
        self.file_context_menu.add_separator()
        self.file_context_menu.add_command(label="Rinomina", command=self.rename_remote_item)
        self.file_context_menu.add_separator()
        self.file_context_menu.add_command(label="Elimina", command=self.delete_remote_item)

        self._files_info_base = "Nessun file caricato."
        self.lbl_files_info = ttk.Label(
            explorer, text=self._files_info_base, style="CardMuted.TLabel"
        )
        self.lbl_files_info.pack(fill=tk.X, pady=(6, 0))

        # --- spazio home ---
        quota = ttk.Frame(tab, style="Card.TFrame", padding=(14, 10))
        quota.pack(fill=tk.X, pady=(8, 0))

        quota_left = ttk.Frame(quota, style="Card.TFrame")
        quota_left.pack(side=tk.LEFT)
        ttk.Label(quota_left, text="Spazio home", style="CardSection.TLabel").pack(anchor="w")
        ttk.Label(
            quota_left, text=f"Limite {HOME_QUOTA_MB} MB", style="CardMuted.TLabel"
        ).pack(anchor="w", pady=(2, 0))

        quota_middle = ttk.Frame(quota, style="Card.TFrame")
        quota_middle.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(18, 18))
        self.progress_quota = ttk.Progressbar(
            quota_middle, orient="horizontal", mode="determinate",
            maximum=HOME_QUOTA_MB, style="QuotaGreen.Horizontal.TProgressbar",
        )
        self.progress_quota.pack(fill=tk.X)
        self.lbl_quota_text = ttk.Label(
            quota_middle, text="Connettiti per calcolare lo spazio usato.",
            style="QuotaValue.TLabel",
        )
        self.lbl_quota_text.pack(anchor="w", pady=(5, 0))

        quota_right = ttk.Frame(quota, style="Card.TFrame")
        quota_right.pack(side=tk.RIGHT)
        self.btn_quota_refresh = ttk.Button(
            quota_right, text="⟳  Aggiorna", style="Toolbar.TButton",
            command=self.update_quota_live,
        )
        self.btn_quota_refresh.pack(side=tk.LEFT)
        ToolTip(self.btn_quota_refresh, "Ricalcola lo spazio usato nella home")

        self._update_file_action_buttons()

    def _current_path(self):
        return (self.path_var.get() or ".").strip()

    def copy_selected_path(self):
        selected = self._selected_entry()
        if not selected or selected[0] == "..":
            return
        path = remote_join(self._current_path(), selected[0])
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(path)
        except Exception:
            return
        self._set_status(f"Percorso copiato · {path}")

    def _update_file_action_buttons(self):
        """Abilita le azioni in base al numero di elementi selezionati."""
        if not hasattr(self, "btn_download") or not hasattr(self, "lbl_files_info"):
            return
        selected = self._selected_entries() if self.connected else []
        count = len(selected)
        any_state = tk.NORMAL if count else tk.DISABLED
        for button in (self.btn_download, self.btn_delete):
            try:
                button.config(state=any_state)
            except Exception:
                pass
        try:
            self.btn_rename.config(
                state=tk.NORMAL if count == 1 else tk.DISABLED
            )
        except Exception:
            pass
        try:
            self.btn_edit.config(
                state=(
                    tk.NORMAL
                    if count == 1 and not selected[0][1]
                    else tk.DISABLED
                )
            )
        except Exception:
            pass
        connected_state = tk.NORMAL if self.connected else tk.DISABLED
        for button in (self.btn_upload, self.btn_new_folder):
            try:
                button.config(state=connected_state)
            except Exception:
                pass
        quota_state = (
            tk.NORMAL if self.connected and not self._quota_inflight
            else tk.DISABLED
        )
        try:
            self.btn_quota_refresh.config(state=quota_state)
        except Exception:
            pass
        base = getattr(self, "_files_info_base", "Nessun file caricato.")
        if count == 1:
            text = f"{base}  ·  selezionato: {selected[0][0]}"
        elif count > 1:
            text = f"{base}  ·  {count} selezionati"
        else:
            text = base
        self.lbl_files_info.config(text=text)

    # ----------------------------- operazioni file -----------------------------
    def _ssh_exec(self, command):
        """Esegue un comando remoto e restituisce (exit_code, stdout, stderr)."""
        _stdin, stdout, stderr = self.ssh_client.exec_command(command)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    def _ensure_remote_dir(self, sftp, path):
        if not path or path in (".", "/"):
            return
        try:
            sftp.stat(path)
            return
        except IOError:
            parent = posixpath.dirname(path.rstrip("/"))
            if parent and parent != path:
                self._ensure_remote_dir(sftp, parent)
            try:
                sftp.mkdir(path)
            except IOError:
                sftp.stat(path)

    def navigate_up(self):
        current = self._current_path()
        if current in (".", "", "/"):
            return
        parent = posixpath.dirname(current.rstrip("/")) or "/"
        self.path_var.set(parent)
        self.refresh_remote_files()

    def go_home(self):
        if not self.connected:
            return
        self.path_var.set(".")
        self.refresh_remote_files()

    def refresh_remote_files(self):
        if not self.connected:
            return
        path = self._current_path()

        def work():
            with self._sftp_lock:
                return self.sftp_client.listdir_attr(path)

        def done(entries):
            self._update_file_tree(path, entries)
            self._set_status(f"{len(entries)} elementi · {path}")

        def failed(exc):
            messagebox.showerror("Errore SFTP", f"Impossibile accedere a {path}:\n{exc}")

        self._run_async(work, done, failed, busy_msg=f"Lettura di {path}...")

    def _update_file_tree(self, path, entries):
        for item in self.tree_files.get_children():
            self.tree_files.delete(item)

        if path != self._last_file_tree_path:
            self._last_file_tree_path = path
            if self.filter_var.get():
                self.filter_var.set("")

        self._files_token += 1
        token = self._files_token
        self._dir_items = {}
        self._file_item_order = []
        self._file_up_item = None
        self._filtered_item_ids = []
        self._last_filter_pattern = None

        if path not in ("/", "", "."):
            self._file_up_item = self.tree_files.insert(
                "", tk.END, values=("..", "Cartella", "", ""), tags=("dir",)
            )
            self._file_item_order.append(self._file_up_item)

        show_hidden = self.show_hidden_var.get()
        visible = [e for e in entries if show_hidden or not e.filename.startswith(".")]
        visible.sort(key=lambda e: (not stat.S_ISDIR(e.st_mode), e.filename.lower()))

        count_dirs = 0
        count_files = 0
        for entry in visible:
            is_dir = stat.S_ISDIR(entry.st_mode)
            if is_dir:
                count_dirs += 1
                type_label = "Cartella"
                cache_key = (self.current_host, path, entry.filename)
                cached_size = self._folder_size_cache.get(cache_key)
                size_label = human_size(cached_size) if cached_size is not None else "calcolo..."
            else:
                count_files += 1
                ext = os.path.splitext(entry.filename)[1][1:].upper()
                type_label = ext or "File"
                size_label = human_size(entry.st_size)

            modified = "-"
            if entry.st_mtime:
                modified = datetime.fromtimestamp(entry.st_mtime).strftime("%d/%m/%Y %H:%M")

            item_id = self.tree_files.insert(
                "", tk.END,
                values=(entry.filename, type_label, size_label, modified),
                tags=("dir",) if is_dir else ("file",),
            )
            self._file_item_order.append(item_id)
            if is_dir:
                self._dir_items[entry.filename] = item_id

        self._files_info_base = (
            f"{path}  ·  {count_dirs} cartelle, {count_files} file"
            + ("  ·  calcolo spazio cartelle..." if count_dirs and self.connected else "")
        )
        self.lbl_files_info.config(text=self._files_info_base)
        self._apply_file_filter()

        if count_dirs and self.connected:
            self._load_folder_sizes(path, list(self._dir_items), token, count_dirs, count_files)

    def _load_folder_sizes(self, path, names, token, count_dirs, count_files):
        """Calcola in background lo spazio occupato dalle cartelle con du."""
        if not names:
            return

        def work():
            sizes = {}
            chunk_size = 30
            for start in range(0, len(names), chunk_size):
                batch = names[start:start + chunk_size]
                batch_set = set(batch)
                paths = [remote_join(path, name) for name in batch]
                command = "du -sk -- " + " ".join(shlex.quote(p) for p in paths) + " 2>/dev/null"
                try:
                    _code, out, _err = self._ssh_exec(command)
                except Exception:
                    continue
                for line in out.splitlines():
                    if "\t" not in line:
                        continue
                    raw_size, raw_path = line.split("\t", 1)
                    try:
                        size_bytes = int(raw_size) * 1024
                    except ValueError:
                        continue
                    folder = posixpath.basename(raw_path.rstrip("/"))
                    if folder in batch_set:
                        sizes[folder] = size_bytes
            return sizes

        def finish(sizes):
            if token != self._files_token:
                return
            for name, size_bytes in sizes.items():
                self._folder_size_cache[(self.current_host, path, name)] = size_bytes
            for name, item_id in list(self._dir_items.items()):
                if not self.tree_files.exists(item_id):
                    continue
                values = list(self.tree_files.item(item_id, "values"))
                if len(values) < 3:
                    continue
                values[2] = human_size(sizes[name]) if name in sizes else "n/d"
                self.tree_files.item(item_id, values=values)
            self._files_info_base = (
                f"{path}  ·  {count_dirs} cartelle, {count_files} file"
            )
            self.lbl_files_info.config(text=self._files_info_base)
            self._update_file_action_buttons()

        def failed(_exc):
            finish({})

        self._run_async(work, finish, failed, show_error=False)

    def _selected_entry(self):
        selection = self.tree_files.selection()
        if not selection:
            return None
        item = self.tree_files.item(selection[0])
        values = item.get("values", [])
        if not values:
            return None
        name = str(values[0])
        is_dir = "dir" in item.get("tags", [])
        return name, is_dir

    def _selected_entries(self):
        """Restituisce tutte le voci selezionate, escludendo la riga '..'."""
        selected = []
        for item_id in self.tree_files.selection():
            item = self.tree_files.item(item_id)
            values = item.get("values", [])
            if not values:
                continue
            name = str(values[0])
            if name == "..":
                continue
            selected.append((name, "dir" in item.get("tags", [])))
        return selected

    def _schedule_file_filter(self, _event=None):
        if self._filter_after is not None:
            try:
                self.root.after_cancel(self._filter_after)
            except Exception:
                pass

        def apply_later():
            self._filter_after = None
            self._apply_file_filter()

        self._filter_after = self.root.after(120, apply_later)

    def _on_filter_escape(self, _event=None):
        self.clear_file_filter()
        return "break"

    def clear_file_filter(self):
        if not hasattr(self, "filter_var"):
            return
        if self._filter_after is not None:
            try:
                self.root.after_cancel(self._filter_after)
            except Exception:
                pass
            self._filter_after = None
        self.filter_var.set("")
        self._apply_file_filter()

    @staticmethod
    def _file_matches_filter(name, pattern):
        if not pattern:
            return True
        lowered_name = name.lower()
        lowered_pattern = pattern.lower()
        if any(char in pattern for char in "*?["):
            return fnmatch.fnmatchcase(lowered_name, lowered_pattern)
        return lowered_pattern in lowered_name

    def _apply_file_filter(self):
        """Mostra solo le righe che corrispondono al filtro corrente."""
        if not hasattr(self, "tree_files"):
            return
        if self._filter_after is not None:
            try:
                self.root.after_cancel(self._filter_after)
            except Exception:
                pass
            self._filter_after = None
        pattern = self.filter_var.get().strip()
        if pattern == self._last_filter_pattern:
            return

        try:
            selection = self.tree_files.selection()
            if selection:
                self.tree_files.selection_remove(*selection)
        except Exception:
            pass

        for item_id in self._file_item_order:
            try:
                self.tree_files.detach(item_id)
            except tk.TclError:
                pass

        visible = []
        for item_id in self._file_item_order:
            if not self.tree_files.exists(item_id):
                continue
            if item_id == self._file_up_item:
                self.tree_files.move(item_id, "", "end")
                continue
            item = self.tree_files.item(item_id)
            values = item.get("values", [])
            name = str(values[0]) if values else ""
            if not pattern or self._file_matches_filter(name, pattern):
                self.tree_files.move(item_id, "", "end")
                visible.append(item_id)

        self._filtered_item_ids = visible
        self._last_filter_pattern = pattern
        try:
            self.tree_files.yview_moveto(0)
        except Exception:
            pass
        if hasattr(self, "lbl_filter_count"):
            if pattern:
                count = len(visible)
                if count == 0:
                    label = "nessun risultato"
                elif count == 1:
                    label = "1 risultato"
                else:
                    label = f"{count} risultati"
                self.lbl_filter_count.config(text=label)
            else:
                self.lbl_filter_count.config(text="")
        if hasattr(self, "btn_filter_select"):
            state = tk.NORMAL if pattern and visible else tk.DISABLED
            try:
                self.btn_filter_select.config(state=state)
            except Exception:
                pass
        self._update_file_action_buttons()

    def select_filtered_files(self):
        if self._filter_after is not None:
            self._apply_file_filter()
        items = [
            item_id for item_id in self._filtered_item_ids
            if self.tree_files.exists(item_id)
        ]
        if not items:
            return
        self.tree_files.selection_set(items)
        self.tree_files.focus(items[0])
        self.tree_files.see(items[0])
        self._update_file_action_buttons()

    def select_all_visible(self, _event=None):
        if self._filter_after is not None:
            self._apply_file_filter()
        items = [
            item_id for item_id in self.tree_files.get_children()
            if item_id != self._file_up_item
        ]
        if not items:
            return "break"
        self.tree_files.selection_set(items)
        self.tree_files.focus(items[0])
        self.tree_files.see(items[0])
        self._update_file_action_buttons()
        return "break"

    def on_tree_double_click(self, _event=None):
        selected = self._selected_entry()
        if not selected:
            return
        name, is_dir = selected
        current = self._current_path()

        if is_dir:
            if name == "..":
                new_path = posixpath.dirname(current.rstrip("/")) or "/"
            else:
                new_path = remote_join(current, name)
            self.path_var.set(new_path)
            self.refresh_remote_files()
            return

        remote_path = remote_join(current, name)
        if name.lower().endswith(TEXT_EXTENSIONS):
            RemoteEditorWindow(
                self.root, self.sftp_client, remote_path, self._sftp_lock
            )
        else:
            self._open_file_natively(remote_path, name)

    def _open_file_natively(self, remote_path, filename):
        if not self.connected:
            return
        if not self._temp_dir:
            self._temp_dir = tempfile.mkdtemp(prefix="hpc_disi_")
        local_path = os.path.join(self._temp_dir, filename)

        def work():
            with self._sftp_lock:
                self.sftp_client.get(remote_path, local_path)
            return local_path

        def done(path):
            system = platform.system()
            if system == "Windows":
                os.startfile(path)
            elif system == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self._set_status(f"Aperto {filename} con l'app di sistema")

        self._run_async(work, done, busy_msg=f"Download di {filename}...")

    def show_context_menu(self, event):
        self._close_context_menus()
        if not self.connected:
            return
        row = self.tree_files.identify_row(event.y)
        if not row:
            return
        self.tree_files.selection_set(row)
        item = self.tree_files.item(row)
        name = str(item["values"][0])
        if name == "..":
            return
        is_dir = "dir" in item.get("tags", [])
        self.file_context_menu.entryconfigure(
            1, state=tk.DISABLED if is_dir else tk.NORMAL
        )
        self.file_context_menu.post(event.x_root, event.y_root)

    def download_selected(self):
        selected = self._selected_entries()
        if not selected:
            messagebox.showinfo(
                "Download", "Seleziona almeno un file o una cartella."
            )
            return
        if len(selected) == 1:
            _name, is_dir = selected[0]
            if is_dir:
                self.download_folder()
            else:
                self.download_file()
            return
        self._download_multiple(selected)

    def download_file(self):
        selected = self._selected_entries()
        if not selected:
            return
        name, is_dir = selected[0]
        if is_dir:
            self.download_folder()
            return

        remote_path = remote_join(self._current_path(), name)
        local_path = filedialog.asksaveasfilename(title="Salva con nome", initialfile=name)
        if not local_path:
            return

        def work():
            with self._sftp_lock:
                self.sftp_client.get(remote_path, local_path)
            return local_path

        def done(path):
            self._set_status(f"Scaricato · {path}")

        self._run_async(
            work, done,
            busy_msg=f"Download di {name}...",
        )

    def _download_multiple(self, selected):
        local_base = filedialog.askdirectory(
            title=f"Scegli dove salvare {len(selected)} elementi"
        )
        if not local_base:
            return

        current = self._current_path()
        targets = []
        existing = []
        for name, is_dir in selected:
            local_path = os.path.join(local_base, name)
            targets.append((name, is_dir, remote_join(current, name), local_path))
            if os.path.exists(local_path):
                existing.append(name)

        if existing:
            preview = ", ".join(existing[:5])
            if len(existing) > 5:
                preview += f" e altri {len(existing) - 5}"
            if not messagebox.askyesno(
                "Sovrascrivere?",
                f"Nella cartella scelta esistono gia:\n{preview}\n\n"
                "Continuare e sovrascrivere?",
                icon="warning",
            ):
                return

        def work():
            downloaded = 0

            def recurse(rem_path, loc_path):
                nonlocal downloaded
                os.makedirs(loc_path, exist_ok=True)
                for entry in self.sftp_client.listdir_attr(rem_path):
                    r_item = posixpath.join(rem_path, entry.filename)
                    l_item = os.path.join(loc_path, entry.filename)
                    if stat.S_ISDIR(entry.st_mode):
                        recurse(r_item, l_item)
                    else:
                        self.sftp_client.get(r_item, l_item)
                        downloaded += 1
                        if downloaded % 5 == 0:
                            self._call_main(
                                lambda d=downloaded: self._set_status(
                                    f"Download multiplo · {d} file..."
                                )
                            )

            errors = []
            with self._sftp_lock:
                for name, is_dir, remote_path, local_path in targets:
                    try:
                        if is_dir:
                            recurse(remote_path, local_path)
                        else:
                            self.sftp_client.get(remote_path, local_path)
                            downloaded += 1
                            if downloaded % 5 == 0:
                                self._call_main(
                                    lambda d=downloaded: self._set_status(
                                        f"Download multiplo · {d} file..."
                                    )
                                )
                    except Exception as exc:
                        errors.append((name, str(exc)))
            return downloaded, errors

        def done(result):
            downloaded, errors = result
            self._set_status(
                f"Download completato · {downloaded} file · "
                f"{len(targets)} elementi"
            )
            if errors:
                details = "\n".join(
                    f"· {name}: {error}" for name, error in errors[:5]
                )
                if len(errors) > 5:
                    details += f"\n… e altri {len(errors) - 5}"
                messagebox.showwarning(
                    "Download parziale",
                    f"Scaricati {downloaded} file.\n"
                    f"{len(errors)} elementi non sono stati scaricati:\n\n"
                    f"{details}",
                )

        self._run_async(
            work, done,
            busy_msg=f"Download di {len(targets)} elementi...",
        )

    def edit_remote_file(self):
        entries = self._selected_entries()
        if len(entries) > 1:
            messagebox.showinfo(
                "Editor", "Seleziona un solo file da modificare."
            )
            return
        if not entries:
            messagebox.showinfo("Editor", "Seleziona un file da modificare.")
            return
        name, is_dir = entries[0]
        if is_dir:
            messagebox.showwarning("Editor", "Seleziona un file, non una cartella.")
            return
        RemoteEditorWindow(
            self.root, self.sftp_client,
            remote_join(self._current_path(), name), self._sftp_lock,
        )

    def create_remote_folder(self):
        if not self.connected:
            return
        name = simpledialog.askstring("Nuova cartella", "Nome della nuova cartella:", parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name or "/" in name or name in (".", ".."):
            messagebox.showerror("Nome non valido", "Usa un nome semplice, senza '/'.")
            return
        remote_path = remote_join(self._current_path(), name)

        def work():
            with self._sftp_lock:
                self._ensure_remote_dir(self.sftp_client, remote_path)
            return remote_path

        def done(path):
            self._set_status(f"Cartella creata · {path}")
            self.refresh_remote_files()

        self._run_async(work, done, busy_msg="Creazione cartella...")

    def rename_remote_item(self):
        entries = self._selected_entries()
        if len(entries) > 1:
            messagebox.showinfo(
                "Rinomina", "Seleziona un solo file o una sola cartella."
            )
            return
        if not entries:
            messagebox.showinfo("Rinomina", "Seleziona un file o una cartella.")
            return
        name, _is_dir = entries[0]
        new_name = simpledialog.askstring(
            "Rinomina", f"Nuovo nome per '{name}':",
            initialvalue=name, parent=self.root,
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or "/" in new_name or new_name in (".", ".."):
            messagebox.showerror("Nome non valido", "Usa un nome semplice, senza '/'.")
            return
        if new_name == name:
            return

        current = self._current_path()
        old_path = remote_join(current, name)
        new_path = remote_join(current, new_name)

        def work():
            with self._sftp_lock:
                self.sftp_client.rename(old_path, new_path)
            return new_path

        def done(path):
            self._set_status(f"Rinominato in · {path}")
            self.refresh_remote_files()

        self._run_async(work, done, busy_msg="Rinomina in corso...")

    def delete_remote_item(self):
        selected = self._selected_entries()
        if not selected:
            messagebox.showinfo(
                "Elimina", "Seleziona almeno un file o una cartella."
            )
            return
        current = self._current_path()
        names = [name for name, _is_dir in selected]
        paths = [remote_join(current, name) for name in names]

        if len(names) == 1:
            name, is_dir = selected[0]
            kind = "la cartella" if is_dir else "il file"
            question = (
                f"Eliminare definitivamente {kind}:\n\n{paths[0]}\n\n"
                "L'operazione non puo essere annullata."
            )
        else:
            preview = "\n".join(f"  · {name}" for name in names[:8])
            if len(names) > 8:
                preview += f"\n  … e altri {len(names) - 8}"
            question = (
                f"Eliminare definitivamente {len(names)} elementi?\n\n"
                f"{preview}\n\nL'operazione non puo essere annullata."
            )

        if not messagebox.askyesno(
            "Conferma eliminazione", question, icon="warning"
        ):
            return

        def work():
            batch_size = 40
            for start in range(0, len(paths), batch_size):
                batch = paths[start:start + batch_size]
                command = "rm -rf -- " + " ".join(
                    shlex.quote(path) for path in batch
                )
                code, _out, err = self._ssh_exec(command)
                if code != 0:
                    raise RuntimeError(
                        err.strip() or f"rm ha restituito {code}"
                    )
            return len(paths)

        def done(count):
            if count == 1:
                self._set_status(f"Eliminato · {names[0]}")
            else:
                self._set_status(f"Eliminati {count} elementi")
            self.refresh_remote_files()
            self.update_quota_live()

        busy = (
            f"Eliminazione di {names[0]}..."
            if len(names) == 1
            else f"Eliminazione di {len(names)} elementi..."
        )
        self._run_async(work, done, busy_msg=busy)

    def upload_file(self):
        if not self.connected:
            return
        local_path = filedialog.askopenfilename(title="Seleziona file da caricare")
        if not local_path:
            return
        filename = os.path.basename(local_path)
        remote_path = remote_join(self._current_path(), filename)

        def work():
            with self._sftp_lock:
                self.sftp_client.put(local_path, remote_path)
            return remote_path

        def done(path):
            self._set_status(f"Caricato · {path}")
            self.refresh_remote_files()
            self.update_quota_live()

        self._run_async(work, done, busy_msg=f"Upload di {filename}...")

    def upload_folder(self):
        if not self.connected:
            return
        local_dir = filedialog.askdirectory(title="Seleziona la cartella da caricare")
        if not local_dir:
            return
        folder_name = os.path.basename(local_dir.rstrip(os.sep)) or "cartella"
        remote_base = remote_join(self._current_path(), folder_name)

        def work():
            total = sum(len(files) for _root, _dirs, files in os.walk(local_dir))
            uploaded = 0
            with self._sftp_lock:
                self._ensure_remote_dir(self.sftp_client, remote_base)
                for root, _dirs, files in os.walk(local_dir):
                    rel = os.path.relpath(root, local_dir)
                    target = remote_base if rel == "." else posixpath.join(
                        remote_base, rel.replace(os.sep, "/")
                    )
                    self._ensure_remote_dir(self.sftp_client, target)
                    for filename in files:
                        self.sftp_client.put(os.path.join(root, filename), posixpath.join(target, filename))
                        uploaded += 1
                        if uploaded % 3 == 0 or uploaded == total:
                            self._call_main(
                                lambda u=uploaded, t=total, f=filename: self._set_status(
                                    f"Upload {u}/{t} · {f}"
                                )
                            )
            return remote_base, uploaded

        def done(result):
            path, count = result
            self._set_status(f"Cartella caricata · {count} file · {path}")
            self.refresh_remote_files()
            self.update_quota_live()

        self._run_async(work, done, busy_msg=f"Upload cartella '{folder_name}'...")

    def download_folder(self):
        selected = self._selected_entries()
        if not selected:
            messagebox.showinfo("Download", "Seleziona una cartella.")
            return
        name, is_dir = selected[0]
        if not is_dir:
            messagebox.showwarning("Download", "Seleziona una cartella valida.")
            return

        remote_dir = remote_join(self._current_path(), name)
        local_base = filedialog.askdirectory(title="Scegli dove salvare la cartella")
        if not local_base:
            return
        local_target = os.path.join(local_base, name)

        def work():
            downloaded = 0

            def recurse(rem_path, loc_path):
                nonlocal downloaded
                os.makedirs(loc_path, exist_ok=True)
                for entry in self.sftp_client.listdir_attr(rem_path):
                    r_item = posixpath.join(rem_path, entry.filename)
                    l_item = os.path.join(loc_path, entry.filename)
                    if stat.S_ISDIR(entry.st_mode):
                        recurse(r_item, l_item)
                    else:
                        self.sftp_client.get(r_item, l_item)
                        downloaded += 1
                        if downloaded % 5 == 0:
                            self._call_main(
                                lambda d=downloaded: self._set_status(
                                    f"Download cartella · {d} file..."
                                )
                            )

            with self._sftp_lock:
                recurse(remote_dir, local_target)
            return local_target, downloaded

        def done(result):
            path, count = result
            self._set_status(f"Cartella scaricata · {count} file · {path}")

        self._run_async(work, done, busy_msg=f"Download cartella '{name}'...")

    # ----------------------------- quota -----------------------------
    def update_quota_live(self):
        if not self.connected:
            self.lbl_quota_text.config(
                text="Connettiti per calcolare lo spazio usato.", foreground=MUTED
            )
            return
        if self._quota_inflight:
            return
        self._quota_inflight = True
        self.lbl_quota_text.config(text="Calcolo spazio...", foreground=MUTED)
        self._update_file_action_buttons()

        def work():
            code, out, err = self._ssh_exec("du -sm ~")
            if code != 0:
                raise RuntimeError(err.strip() or "du non disponibile")
            if not out.strip():
                raise RuntimeError("Risposta vuota da du")
            return int(out.split()[0])

        def done(used_mb):
            self._quota_inflight = False
            if not self.connected:
                return
            self._refresh_quota_ui(used_mb)
            self._update_file_action_buttons()

        def failed(_exc):
            self._quota_inflight = False
            if not self.connected:
                return
            self.lbl_quota_text.config(
                text="Quota non disponibile su questo host.", foreground=MUTED
            )
            self._update_file_action_buttons()

        self._run_async(work, done, failed, show_error=False)

    def _refresh_quota_ui(self, used_mb):
        percent = (used_mb / HOME_QUOTA_MB) * 100
        self.progress_quota["value"] = min(used_mb, HOME_QUOTA_MB)
        remaining = max(0, HOME_QUOTA_MB - used_mb)
        if percent >= 95:
            color = RED
            bar_style = "QuotaRed.Horizontal.TProgressbar"
        elif percent >= 75:
            color = ORANGE
            bar_style = "QuotaOrange.Horizontal.TProgressbar"
        else:
            color = GREEN
            bar_style = "QuotaGreen.Horizontal.TProgressbar"
        self.progress_quota.configure(style=bar_style)
        suffix = " · limite superato" if used_mb > HOME_QUOTA_MB else f" · {remaining} MB liberi"
        self.lbl_quota_text.config(
            text=f"{used_mb} / {HOME_QUOTA_MB} MB ({percent:.1f}%){suffix}",
            foreground=color,
        )

    # ----------------------------- TAB 3: NUOVO JOB -----------------------------
    def _build_slurm_tab(self):
        tab = self.tab_slurm
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(tab, text=" Configurazione del job ", padding=14)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Tipo di programma").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self.combo_type = ttk.Combobox(
            form, values=JOB_TYPES, state="readonly", width=32
        )
        self.combo_type.current(0)
        self.combo_type.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        self.combo_type.bind("<<ComboboxSelected>>", self.on_job_type_change)

        self.lbl_type_hint = ttk.Label(
            form, text="", style="Muted.TLabel", wraplength=360, justify="left",
        )
        self.lbl_type_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        ttk.Label(form, text="Nome del job").grid(
            row=2, column=0, sticky="w", pady=4
        )
        self.ent_job_name = ttk.Entry(form, width=32)
        self.ent_job_name.insert(0, "esperimento_1")
        self.ent_job_name.grid(row=2, column=1, sticky="ew", pady=4)
        self.ent_job_name.bind("<KeyRelease>", lambda _e: self._refresh_script_preview())

        self.lbl_resources = ttk.Label(form, text="Nodi (min 1, max 4)")
        self.lbl_resources.grid(row=3, column=0, sticky="w", pady=4)
        self.spn_resources = ttk.Spinbox(
            form, from_=1, to=4, width=8, command=self._refresh_script_preview
        )
        self.spn_resources.set("1")
        self.spn_resources.grid(row=3, column=1, sticky="w", pady=4)
        self.spn_resources.bind("<KeyRelease>", lambda _e: self._refresh_script_preview())

        ttk.Label(form, text="Email per notifiche").grid(
            row=4, column=0, sticky="w", pady=4
        )
        self.ent_email = ttk.Entry(form, width=32)
        self.ent_email.grid(row=4, column=1, sticky="ew", pady=4)
        self.ent_email.bind("<KeyRelease>", lambda _e: self._refresh_script_preview())

        ttk.Label(form, text="Partizione GPU").grid(
            row=5, column=0, sticky="w", pady=4
        )
        self.combo_partition = ttk.Combobox(
            form, values=PARTITIONS, state="readonly", width=30
        )
        self.combo_partition.current(0)
        self.combo_partition.grid(row=5, column=1, sticky="ew", pady=4)
        self.combo_partition.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_script_preview()
        )

        ttk.Label(form, text="Cartella di lavoro").grid(
            row=7, column=0, sticky="nw", pady=4
        )
        self.lbl_job_dir_var = tk.StringVar(value=".")
        ttk.Label(
            form, textvariable=self.lbl_job_dir_var, style="Muted.TLabel",
            wraplength=320, justify="left",
        ).grid(row=7, column=1, sticky="w", pady=4)

        ttk.Label(
            form,
            text="Il job viene inviato nella cartella corrente della scheda File.",
            style="Muted.TLabel", wraplength=360, justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Button(
            form, text="Sottometti job (sbatch)", style="Accent.TButton",
            command=self.submit_slurm_job,
        ).grid(row=9, column=0, columnspan=2, sticky="ew", pady=(4, 4))

        ttk.Label(
            form, text="Suggerimento: Ctrl+Invio nell'area comandi invia il job.",
            style="Muted.TLabel", wraplength=360,
        ).grid(row=10, column=0, columnspan=2, sticky="w")

        # ---- comandi + anteprima ----
        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        cmd_card = ttk.LabelFrame(right, text=" Comandi da eseguire ", padding=10)
        cmd_card.grid(row=0, column=0, sticky="ew")
        self.txt_script_cmd = scrolledtext.ScrolledText(
            cmd_card, width=52, height=8, font=(MONO_FONT, 10),
            wrap=tk.NONE, undo=True, relief=tk.SOLID, borderwidth=1,
        )
        self.txt_script_cmd.pack(fill=tk.BOTH, expand=True)
        self.txt_script_cmd.bind("<<Modified>>", self._on_cmd_modified)
        self.txt_script_cmd.bind("<Control-Return>", lambda _e: self.submit_slurm_job())

        preview_card = ttk.LabelFrame(right, text=" Anteprima script SLURM ", padding=10)
        preview_card.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        preview_card.rowconfigure(0, weight=1)
        preview_card.columnconfigure(0, weight=1)
        self.txt_preview = scrolledtext.ScrolledText(
            preview_card, width=52, height=16, font=(MONO_FONT, 9),
            wrap=tk.NONE, bg="#0f1115", fg="#d4d4d4",
            insertbackground="#d4d4d4", relief=tk.FLAT, borderwidth=0,
            padx=8, pady=8,
        )
        self.txt_preview.grid(row=0, column=0, sticky="nsew")
        self.txt_preview.configure(state=tk.DISABLED)

        self.on_job_type_change(None)

    def _on_cmd_modified(self, _event=None):
        if self.txt_script_cmd.edit_modified():
            self.txt_script_cmd.edit_modified(False)
            self._refresh_script_preview()

    def _job_kind(self):
        job_type = self.combo_type.get()
        if job_type.startswith("Python"):
            return "python"
        if "OpenMP" in job_type:
            return "openmp"
        if "MPI" in job_type:
            return "mpi"
        if "CUDA" in job_type:
            return "cuda"
        return "python"

    def _job_limits(self):
        kind = self._job_kind()
        if kind == "openmp":
            return 1, 32, 4, "Core CPU (min 1, max 32)"
        if kind == "mpi":
            return 2, 128, 12, "Task MPI totali (min 2, max 128)"
        if kind == "cuda":
            return 1, 4, 1, "Nodi GPU (min 1, max 4)"
        return 1, 4, 1, "Nodi GPU (min 1, max 4)"

    def on_job_type_change(self, _event=None):
        kind = self._job_kind()
        presets = {
            "python": (
                "srun python3 -u script.py",
                "Avvia lo script Python su una GPU, dentro l'ambiente virtuale indicato.",
                0,
            ),
            "openmp": (
                "export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK\nsrun ./omp-program",
                "Programma C con OpenMP: imposta i thread dal numero di core richiesto.",
                2,
            ),
            "mpi": (
                "srun --mpi=pmix_v4 -n $SLURM_NTASKS ./mpi-program",
                "Programma C con MPI distribuito su piu task.",
                2,
            ),
            "cuda": (
                "nvcc cuda-program.cu -o cuda-program && srun ./cuda-program",
                "Compila ed esegue un programma CUDA su una GPU.",
                0,
            ),
        }
        command, hint, partition_index = presets[kind]
        _min, _max, default, label = self._job_limits()

        self.lbl_resources.config(text=label)
        self.spn_resources.config(from_=_min, to=_max)
        self.spn_resources.set(str(default))
        self.combo_partition.current(partition_index)
        self.lbl_type_hint.config(text=hint)

        self.txt_script_cmd.delete("1.0", tk.END)
        self.txt_script_cmd.insert("1.0", command)
        self.txt_script_cmd.edit_modified(False)
        self._refresh_script_preview()

    def _refresh_script_preview(self):
        if self._preview_after:
            try:
                self.root.after_cancel(self._preview_after)
            except Exception:
                pass
        self._preview_after = self.root.after(150, self._update_script_preview)

    def _update_script_preview(self):
        self._preview_after = None
        script = self._compose_sbatch()
        try:
            self.txt_preview.configure(state=tk.NORMAL)
            self.txt_preview.delete("1.0", tk.END)
            self.txt_preview.insert("1.0", script)
            self.txt_preview.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _compose_sbatch(self):
        kind = self._job_kind()
        job_name = self.ent_job_name.get().strip() or "job"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_name) or "job"
        email = self.ent_email.get().strip()
        partition = self.combo_partition.get()
        commands = self.txt_script_cmd.get("1.0", "end-1c").strip()
        work_dir = self._current_path()

        try:
            resources = int(self.spn_resources.get())
        except (TypeError, ValueError):
            resources = self._job_limits()[2]

        lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={shlex.quote(job_name)}",
            f"#SBATCH --output=logs/{safe_name}_%j.out",
        ]
        if email:
            lines.append("#SBATCH --mail-type=ALL")
            lines.append(f"#SBATCH --mail-user={email}")
        if work_dir not in ("", "."):
            lines.append(f"#SBATCH --chdir={shlex.quote(work_dir)}")

        if kind in ("python", "cuda"):
            if partition in PARTITIONS[:2]:
                lines.append(f"#SBATCH --partition={partition}")
            else:
                lines.append("# ATTENZIONE: seleziona una partizione GPU (rtx2080 o l40)")
            lines.append(f"#SBATCH --nodes={resources}")
            lines.append("#SBATCH --ntasks=1")
            lines.append("#SBATCH --gres=gpu:1")
        elif kind == "openmp":
            lines.append("#SBATCH --nodes=1")
            lines.append(f"#SBATCH --cpus-per-task={resources}")
        elif kind == "mpi":
            lines.append(f"#SBATCH --ntasks={resources}")

        lines.append("")
        lines.append('echo "# === Job ${SLURM_JOB_ID:-?} · $(hostname) · $(date) ==="')
        lines.append('echo "# Cartella: $(pwd)"')
        if kind == "python":
            lines.append('echo "# Python: $(python3 -V 2>&1)"')
            
        lines.append("")
        lines.append(commands)
        lines.append("")
        lines.append("code=$?")
        lines.append('echo "# === Fine: $(date) · exit $code ==="')
        lines.append("exit $code")
        return "\n".join(lines)

    def submit_slurm_job(self):
        if not self.connected:
            messagebox.showwarning("Job SLURM", "Connettiti prima al cluster.")
            return

        kind = self._job_kind()
        job_name = self.ent_job_name.get().strip()
        if not job_name:
            messagebox.showwarning("Nome job", "Inserisci un nome per il job.")
            self.ent_job_name.focus_set()
            return

        try:
            resources = int(self.spn_resources.get())
        except (TypeError, ValueError):
            messagebox.showwarning("Risorse", "Il numero di nodi/core deve essere un intero.")
            return
        min_res, max_res, _default, label = self._job_limits()
        if not (min_res <= resources <= max_res):
            messagebox.showwarning(
                "Risorse non valide", f"{label}: hai inserito {resources}."
            )
            return

        email = self.ent_email.get().strip()
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            messagebox.showwarning("Email", "L'indirizzo email non sembra valido.")
            return

        partition = self.combo_partition.get()
        if kind in ("python", "cuda") and partition not in PARTITIONS[:2]:
            messagebox.showwarning(
                "Partizione GPU",
                "Per un job GPU scegli la partizione rtx2080 o l40.",
            )
            return

        commands = self.txt_script_cmd.get("1.0", "end-1c").strip()
        if not commands:
            messagebox.showwarning("Comandi", "Inserisci il comando da eseguire.")
            return

        script = self._compose_sbatch() + "\n"
        remote_dir = self._current_path()
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_name) or "job"
        remote_name = f"gui_submit_{safe_name}.sbatch"
        remote_path = remote_join(remote_dir, remote_name)

        def work():
            with self._sftp_lock:
                with self.sftp_client.file(remote_path, "w") as fh:
                    fh.write(script.encode("utf-8"))
            command = (
                f"cd {shlex.quote(remote_dir)} && mkdir -p logs && "
                f"sbatch {shlex.quote(remote_name)}"
            )
            code, out, err = self._ssh_exec(command)
            return code, out, err

        def done(result):
            code, out, err = result
            if code != 0 or "Submitted batch job" not in out:
                messagebox.showerror(
                    "Errore SLURM",
                    (err or out or f"sbatch ha restituito {code}").strip(),
                )
                return
            job_id = out.strip().split()[-1]
            self._set_status(f"Job {job_id} inviato · {remote_name}")
            messagebox.showinfo(
                "Job inviato",
                f"{out.strip()}\n\nScript: {remote_path}\n"
                f"Output: logs/{safe_name}_{job_id}.out",
            )
            self.refresh_squeue(silent=True)
            self._open_output_path(
                remote_join(remote_join(remote_dir, "logs"), f"{safe_name}_{job_id}.out"),
                waiting=True,
            )

        self._run_async(work, done, busy_msg="Invio del job a SLURM...")

    # ----------------------------- TAB 4: JOB -----------------------------
    HISTORY_PERIODS = (
        ("24 ore", "now-1day"),
        ("7 giorni", "now-7days"),
        ("30 giorni", "now-30days"),
    )
    HISTORY_PERIOD_SECONDS = {
        "now-1day": 86400,
        "now-7days": 7 * 86400,
        "now-30days": 30 * 86400,
    }
    HISTORY_LIMIT = 300

    def _build_jobs_tab(self):
        tab = self.tab_jobs

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="⟳  Aggiorna", command=self._refresh_all_jobs).pack(
            side=tk.LEFT
        )
        self.auto_jobs_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar, text="Aggiorna automaticamente (10 s)",
            variable=self.auto_jobs_var, command=self._toggle_jobs_auto,
        ).pack(side=tk.LEFT, padx=12)

        self.show_all_gpu_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar, text="Tutti i job GPU",
            variable=self.show_all_gpu_var, command=self._on_gpu_filter,
        ).pack(side=tk.LEFT, padx=(0, 12))

        self.lbl_jobs_info = ttk.Label(toolbar, text="Nessun job.", style="Muted.TLabel")
        self.lbl_jobs_info.pack(side=tk.LEFT, padx=12)

        ttk.Button(
            toolbar, text="Cancella job selezionato", style="DangerOutline.TButton",
            command=self.cancel_job,
        ).pack(side=tk.RIGHT)
        details_btn = ttk.Button(
            toolbar, text="Dettagli job", command=self.show_selected_job_details
        )
        details_btn.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(details_btn, "CPU, memoria e GPU in tempo reale")

        sinfo_card = ttk.LabelFrame(tab, text=" Stato nodi GPU ", padding=8)
        sinfo_card.pack(fill=tk.X, pady=(8, 6))
        self.txt_sinfo = scrolledtext.ScrolledText(
            sinfo_card, height=4, bg="#0f1115", fg="#d4d4d4",
            font=(MONO_FONT, 10), relief=tk.FLAT, borderwidth=0,
            padx=8, pady=6, wrap=tk.NONE,
        )
        self.txt_sinfo.pack(fill=tk.BOTH, expand=True)
        self.txt_sinfo.tag_configure("title", foreground="#58a6ff", font=(MONO_FONT, 10, "bold"))
        self.txt_sinfo.tag_configure("ok", foreground="#7ee787")
        self.txt_sinfo.tag_configure("warn", foreground="#f0b72f")
        self.txt_sinfo.tag_configure("bad", foreground="#ff7b72")
        self.txt_sinfo.tag_configure("norm", foreground="#8b949e")

        paned = ttk.PanedWindow(tab, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ------------------------- job attivi -------------------------
        jobs_card = ttk.LabelFrame(paned, text=" Job attivi ", padding=8)
        self.jobs_card = jobs_card
        jobs_card.rowconfigure(0, weight=1)
        jobs_card.columnconfigure(0, weight=1)

        active_columns = (
            "jobid", "partition", "name", "user", "state", "time",
            "nodes", "gpu", "node",
        )
        self.tree_jobs = ttk.Treeview(
            jobs_card, columns=active_columns, show="headings",
            selectmode="browse", height=5,
        )
        active_headings = {
            "jobid": ("ID", 80), "partition": ("Partizione", 90),
            "name": ("Nome", 190), "user": ("Utente", 100),
            "state": ("Stato", 95), "time": ("Tempo", 85),
            "nodes": ("Nodi", 50), "gpu": ("GPU", 100),
            "node": ("Nodo", 170),
        }
        for column in active_columns:
            text, width = active_headings[column]
            self.tree_jobs.heading(column, text=text)
            self.tree_jobs.column(
                column, width=width, anchor="center",
                stretch=(column == "name"),
            )
        self._configure_job_tags(self.tree_jobs)

        vbar = ttk.Scrollbar(jobs_card, orient=tk.VERTICAL, command=self.tree_jobs.yview)
        self.tree_jobs.configure(yscrollcommand=vbar.set)
        self.tree_jobs.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")

        self.tree_jobs.bind("<Delete>", lambda _e: self.cancel_job())
        self.tree_jobs.bind("<Double-1>", self.open_selected_job_output)
        self.tree_jobs.bind("<Button-3>", self._show_jobs_menu)
        self.tree_jobs.bind("<Button-2>", self._show_jobs_menu)

        paned.add(jobs_card, weight=3)

        # ------------------------- storico -------------------------
        history_card = ttk.LabelFrame(paned, text=" Storico ", padding=8)
        history_card.rowconfigure(1, weight=1)
        history_card.columnconfigure(0, weight=1)

        hist_header = ttk.Frame(history_card)
        hist_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.btn_history_info = tk.Button(
            hist_header, text="ⓘ", command=self._show_history_info,
            bg=BASE_BG, fg=ACCENT, activebackground="#dfe8f5",
            activeforeground=ACCENT_HOVER, bd=0, relief=tk.FLAT,
            highlightthickness=0, font=(UI_FONT, 13), cursor="hand2",
            padx=2, pady=0,
        )
        self.btn_history_info.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(self.btn_history_info, "Informazioni sullo storico")
        ttk.Label(hist_header, text="Periodo:").pack(side=tk.LEFT)
        self.history_period_var = tk.StringVar(value=self._history_label)
        self.combo_history_period = ttk.Combobox(
            hist_header, textvariable=self.history_period_var,
            values=[label for label, _ in self.HISTORY_PERIODS],
            state="readonly", width=10,
        )
        self.combo_history_period.pack(side=tk.LEFT, padx=(6, 10))
        self.combo_history_period.bind(
            "<<ComboboxSelected>>", self._on_history_period
        )
        self.lbl_history_info = ttk.Label(
            hist_header, text="Nessun job.", style="Muted.TLabel"
        )
        self.lbl_history_info.pack(side=tk.LEFT, padx=12)

        history_columns = (
            "jobid", "name", "partition", "state",
            "start", "time", "nodes", "exit",
        )
        self.tree_history = ttk.Treeview(
            history_card, columns=history_columns, show="headings",
            selectmode="browse", height=4,
        )
        history_headings = {
            "jobid": ("ID", 90), "name": ("Nome", 230),
            "partition": ("Partizione", 110), "state": ("Stato", 110),
            "start": ("Inizio", 130), "time": ("Durata", 100),
            "nodes": ("Nodi", 60), "exit": ("Exit", 80),
        }
        for column in history_columns:
            text, width = history_headings[column]
            self.tree_history.heading(column, text=text)
            self.tree_history.column(
                column, width=width, anchor="center",
                stretch=(column == "name"),
            )
        self._configure_job_tags(self.tree_history)

        hvbar = ttk.Scrollbar(
            history_card, orient=tk.VERTICAL, command=self.tree_history.yview
        )
        self.tree_history.configure(yscrollcommand=hvbar.set)
        self.tree_history.grid(row=1, column=0, sticky="nsew")
        hvbar.grid(row=1, column=1, sticky="ns")

        self.tree_history.bind("<Double-1>", self.open_selected_job_output)
        self.tree_history.bind("<Button-3>", self._show_jobs_menu)
        self.tree_history.bind("<Button-2>", self._show_jobs_menu)

        paned.add(history_card, weight=2)

        # Menu contestuale condiviso dalle due tabelle.
        self.jobs_menu = tk.Menu(self.tree_jobs, tearoff=0)
        self.jobs_menu.add_command(
            label="Mostra output", command=self.open_selected_job_output
        )
        self.jobs_menu.add_command(
            label="Dettagli job", command=self.show_selected_job_details
        )
        self.jobs_menu.add_command(label="Copia Job ID", command=self._copy_job_id)
        self.jobs_menu.add_separator()
        self.jobs_menu.add_command(label="Cancella job", command=self.cancel_job)
        self._jobs_menu_cancel_index = self.jobs_menu.index("end")

    def _configure_job_tags(self, tree):
        tree.tag_configure("running", foreground=GREEN)
        tree.tag_configure("pending", foreground=ORANGE)
        tree.tag_configure("done", foreground=MUTED)
        tree.tag_configure("failed", foreground=RED)
        tree.tag_configure("log", foreground="#58a6ff")
        tree.tag_configure("other", foreground=MUTED)

    def _show_jobs_menu(self, event):
        self._close_context_menus()
        tree = event.widget
        row = tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        tree.focus(row)
        self._jobs_menu_tree = tree
        can_cancel = tree is self.tree_jobs
        if can_cancel:
            values = tree.item(row)["values"]
            owner = str(values[3]).strip() if len(values) > 3 else ""
            if owner and self.current_user and owner != self.current_user:
                can_cancel = False
        try:
            self.jobs_menu.entryconfigure(
                self._jobs_menu_cancel_index,
                state=tk.NORMAL if can_cancel else tk.DISABLED,
            )
        except Exception:
            pass
        self.jobs_menu.post(event.x_root, event.y_root)

    def show_selected_job_details(self):
        tree = self._selected_job_tree()
        selection = tree.selection()
        if not selection:
            messagebox.showinfo(
                "Dettagli job", "Seleziona un job dalla tabella."
            )
            return
        values = tree.item(selection[0])["values"]
        if not values:
            return
        job_id = str(values[0]).strip()
        if not job_id:
            return

        existing = getattr(self, "_details_win", None)
        if existing is not None:
            try:
                alive = bool(existing.winfo_exists())
            except Exception:
                alive = False
            if alive and existing.job_id == job_id:
                existing.lift()
                existing.focus_force()
                return
            try:
                existing.close()
            except Exception:
                pass

        try:
            self._details_win = JobDetailsWindow(self, job_id)
        except Exception as exc:
            self._details_win = None
            messagebox.showerror(
                "Dettagli job",
                f"Impossibile aprire i dettagli del job {job_id}:\n{exc}",
            )

    def _selected_job_tree(self):
        tree = getattr(self, "_jobs_menu_tree", None)
        if isinstance(tree, ttk.Treeview):
            return tree
        return self.tree_jobs

    def _copy_job_id(self):
        tree = self._selected_job_tree()
        selection = tree.selection()
        if not selection:
            return
        job_id = str(tree.item(selection[0])["values"][0])
        self.clipboard_clear()
        self.clipboard_append(job_id)
        self._set_status(f"Job ID {job_id} copiato negli appunti")

    def open_selected_job_output(self, event=None):
        if event is not None and hasattr(event, "y"):
            tree = event.widget
            row = tree.identify_row(event.y)
            if not row:
                return
            tree.selection_set(row)
        else:
            tree = self._selected_job_tree()
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Output job", "Seleziona un job dalla tabella.")
            return
        job_id = str(tree.item(selection[0])["values"][0]).strip()
        if not job_id:
            return
        if tree is self.tree_jobs:
            values = tree.item(selection[0])["values"]
            owner = str(values[3]).strip() if len(values) > 3 else ""
            if owner and self.current_user and owner != self.current_user:
                messagebox.showinfo(
                    "Output job",
                    f"Il job {job_id} appartiene a {owner}.\n"
                    "L'output di un altro utente non è accessibile.",
                )
                return
        if tree is self.tree_history:
            path = self._history_paths.get(job_id)
            if path:
                self._open_output_path(path, waiting=True)
                self._set_status(f"Output job {job_id} · {path}")
                return
        self._resolve_job_output(job_id)

    def _resolve_job_output(self, job_id):
        """Trova il file di output di un job tramite scontrol/sacct e lo apre."""

        def work():
            stdout_path = ""
            work_dir = ""
            job_name = ""

            code, out, _err = self._ssh_exec(
                f"scontrol show job {shlex.quote(job_id)} -o"
            )
            if code == 0:
                for token in out.split():
                    if token.startswith("StdOut="):
                        stdout_path = token.split("=", 1)[1]
                    elif token.startswith("WorkDir="):
                        work_dir = token.split("=", 1)[1]
                    elif token.startswith("JobName="):
                        job_name = token.split("=", 1)[1]

            if not stdout_path or stdout_path in ("None", "Unknown", "/dev/null"):
                code, out, _err = self._ssh_exec(
                    f"sacct -n -X -P -j {shlex.quote(job_id)} "
                    "-o 'StdOut%400,WorkDir%400,JobName%200'"
                )
                if code == 0 and out.strip():
                    parts = [p.strip() for p in out.splitlines()[0].split("|")]
                    if len(parts) >= 3:
                        stdout_path = "" if parts[0] in ("", "None", "Unknown") else parts[0]
                        work_dir = parts[1]
                        job_name = parts[2]

            if (
                stdout_path
                and not stdout_path.startswith("/")
                and work_dir
                and work_dir not in ("", "None", "Unknown")
            ):
                stdout_path = remote_join(work_dir, stdout_path)

            if not stdout_path or stdout_path in ("None", "Unknown"):
                candidates = []
                if work_dir and job_name:
                    candidates = [
                        remote_join(remote_join(work_dir, "logs"), f"{job_name}_{job_id}.out"),
                        remote_join(work_dir, f"{job_name}_job{job_id}.out"),
                        remote_join(work_dir, f"{job_name}_{job_id}.out"),
                    ]
                with self._sftp_lock:
                    for candidate in candidates:
                        try:
                            self.sftp_client.stat(candidate)
                            stdout_path = candidate
                            break
                        except IOError:
                            continue
            return stdout_path

        def done(path):
            if not path:
                messagebox.showinfo(
                    "Output job",
                    f"Non riesco a determinare il file di output del job {job_id}.\n"
                    "Apri la scheda «Output Job»: l'ultimo file .out della "
                    "cartella corrente verra caricato automaticamente.",
                )
                return
            self._open_output_path(path, waiting=True)
            self._set_status(f"Output job {job_id} · {path}")

        self._run_async(work, done, busy_msg=f"Ricerca output del job {job_id}...")

    def _history_period(self):
        label = "7 giorni"
        try:
            label = self.history_period_var.get() or label
        except Exception:
            pass
        for name, starttime in self.HISTORY_PERIODS:
            if name == label:
                return starttime, name
        return "now-7days", "7 giorni"

    def _on_history_period(self, _event=None):
        self.refresh_squeue(force_history=True)

    def _show_history_info(self):
        messagebox.showinfo(
            "Storico job",
            "Questo non è uno storico reale dei job.\n\n"
            "Su questo cluster l'accounting Slurm (sacct/slurmdbd) non è "
            "attualmente supportato, quindi la sezione mostra solo i job "
            "che hanno un file di output .out nella cartella corrente o "
            "nella sottocartella logs/.\n\n"
            "Lo storico può essere incompleto: non include i job eseguiti "
            "in altre cartelle o i job senza file di output.\n\n"
            "Aggiorna lo storico con il pulsante «Aggiorna» nella barra "
            "in alto.",
        )

    def _refresh_all_jobs(self):
        self.refresh_squeue(force_history=True)

    def _on_gpu_filter(self):
        self._update_jobs_mode_label()
        if self._squeue_inflight:
            self._squeue_reload = True
        else:
            self.refresh_squeue(silent=True)

    def _update_jobs_mode_label(self):
        if not hasattr(self, "jobs_card"):
            return
        if self.show_all_gpu_var.get():
            self.jobs_card.configure(
                text=" Job GPU attivi (tutti gli utenti) "
            )
        else:
            self.jobs_card.configure(text=" Job attivi ")

    @staticmethod
    def _job_tag(state):
        head = (state or "").upper().split()[0]
        if head in ("RUNNING", "COMPLETING", "STAGE_OUT"):
            return "running"
        if head in ("PENDING", "CONFIGURING", "REQUEUED", "RESIZING", "SUSPENDED"):
            return "pending"
        if head in (
            "FAILED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "BOOT_FAIL",
            "DEADLINE", "CANCELLED", "PREEMPTED",
        ):
            return "failed"
        if head == "COMPLETED":
            return "done"
        if head == "LOG":
            return "log"
        return "other"

    @staticmethod
    def _gpu_count(value):
        text = str(value or "")
        return sum(
            int(match.group(1))
            for match in re.finditer(
                r"gpu(?::[A-Za-z0-9_.-]+)?[:=](\d+)", text, re.IGNORECASE
            )
        )

    @staticmethod
    def _format_gres(value):
        text = str(value or "").strip()
        if not text or text.lower() in ("(null)", "n/a", "none"):
            return "-"
        parts = []
        for match in re.finditer(
            r"gpu(?::([A-Za-z0-9_.-]+))?[:=](\d+)", text, re.IGNORECASE
        ):
            gpu_type, count = match.group(1), match.group(2)
            parts.append(f"{count}× {gpu_type}" if gpu_type else count)
        return " + ".join(parts) if parts else text

    @staticmethod
    def _format_node(value):
        text = str(value or "").strip()
        if not text or text.lower() in ("(null)", "n/a", "none"):
            return "-"
        nodes = [node.strip() for node in text.split(",") if node.strip()]
        if not nodes:
            return "-"
        if len(nodes) == 1:
            return nodes[0]
        return f"{nodes[0]} +{len(nodes) - 1}"

    @staticmethod
    def _format_history_start(value):
        if not value or value in ("None", "Unknown"):
            return "-"
        try:
            return datetime.strptime(
                value, "%Y-%m-%dT%H:%M:%S"
            ).strftime("%d/%m %H:%M")
        except ValueError:
            return value.replace("T", " ")[:16]

    @staticmethod
    def _selected_job_id(tree):
        selection = tree.selection()
        if not selection:
            return None
        try:
            return str(tree.item(selection[0])["values"][0])
        except Exception:
            return None

    @staticmethod
    def _restore_job_selection(tree, job_id):
        if not job_id:
            return
        for item in tree.get_children():
            if str(tree.item(item)["values"][0]) == job_id:
                tree.selection_set(item)
                tree.focus(item)
                return

    def refresh_squeue(self, silent=False, force_history=False):
        if not self.connected or self._squeue_inflight:
            return
        now = time.monotonic()
        # Lo storico viene aggiornato solo su richiesta esplicita (pulsante
        # «Aggiorna», cambio periodo o apertura della scheda Job): il refresh
        # automatico dei job attivi non deve riscansionare i log.
        need_history = force_history
        attempt_sacct = need_history and (
            force_history
            or self._sacct_available is not False
            or now >= self._sacct_retry_at
        )
        keep_sacct_history = (
            need_history and not attempt_sacct
            and self._history_source == "sacct" and bool(self._history_rows)
        )
        self._squeue_inflight = True
        user = self.current_user
        show_gpu = bool(self.show_all_gpu_var.get())
        period_start, period_label = self._history_period()
        since_epoch = time.time() - self.HISTORY_PERIOD_SECONDS.get(
            period_start, 7 * 86400
        )
        try:
            base_dir = self._current_path()
        except Exception:
            base_dir = ""
        fallback_dirs = []
        if base_dir:
            fallback_dirs = [remote_join(base_dir, "logs"), base_dir]

        def work():
            user_q = shlex.quote(user)
            if show_gpu:
                queue_cmd = (
                    "squeue -h -t RUNNING,COMPLETING,CONFIGURING,"
                    "STAGE_OUT,SUSPENDED "
                    f"-p {','.join(GPU_PARTITIONS)} "
                    "-o '%i|%P|%j|%u|%T|%M|%D|%G|%N'"
                )
            else:
                queue_cmd = (
                    f"squeue -h -u {user_q} "
                    "-o '%i|%P|%j|%u|%T|%M|%D|%G|%N'"
                )
            q_code, q_out, q_err = self._ssh_exec(queue_cmd)
            s_code, s_out, _s_err = self._ssh_exec(
                f"sinfo -h -p {','.join(GPU_PARTITIONS)} -o '%P|%D|%T'"
            )
            h_code, h_out, h_err = 0, "", ""
            if attempt_sacct:
                sacct_cmd = (
                    f"sacct -n -X -P -u {user_q} --starttime {period_start} "
                    "-o 'JobID,Partition%60,JobName%200,State%60,"
                    "Elapsed,NNodes,ExitCode,Start'"
                )
                h_code, h_out, h_err = self._ssh_exec(sacct_cmd)

            # I file .out servono sia come storico di riserva (se l'accounting
            # Slurm non risponde) sia per aprire l'output con un doppio clic.
            scanned_logs = need_history and not keep_sacct_history
            log_rows, log_paths, log_truncated = [], {}, False
            if scanned_logs:
                log_rows, log_paths, log_truncated = self._scan_log_history(
                    fallback_dirs, since_epoch
                )

            err_text = (h_err or "").lower()
            sacct_failed = attempt_sacct and (
                h_code != 0
                or "_open_persist_conn" in err_text
                or "slurmdbd" in err_text
                or "problem talking to the database" in err_text
            )
            return {
                "q_code": q_code, "q_out": q_out, "q_err": q_err,
                "s_code": s_code, "s_out": s_out,
                "h_code": h_code, "h_out": h_out, "h_err": h_err,
                "period_label": period_label,
                "did_history": need_history,
                "asked_sacct": attempt_sacct,
                "sacct_failed": sacct_failed,
                "log_rows": log_rows,
                "log_paths": log_paths,
                "log_truncated": log_truncated,
                "scanned_logs": scanned_logs,
            }

        def done(result):
            self._squeue_inflight = False
            q_code = result["q_code"]
            q_out = result["q_out"]
            q_err = result["q_err"]
            s_code = result["s_code"]
            s_out = result["s_out"]
            h_code = result["h_code"]
            h_out = result["h_out"]
            req_label = result["period_label"]
            did_history = result["did_history"]
            asked_sacct = result["asked_sacct"]
            sacct_failed = result["sacct_failed"]

            active = []
            if q_code == 0:
                for line in q_out.splitlines():
                    parts = [part.strip() for part in line.split("|")]
                    if len(parts) >= 7:
                        while len(parts) < 9:
                            parts.append("")
                        active.append(parts[:9])

            history_updated = False
            if did_history:
                if asked_sacct and not sacct_failed:
                    rows_by_id = {}
                    for line in h_out.splitlines():
                        parts = [part.strip() for part in line.split("|")]
                        if len(parts) < 7 or not parts[0].isdigit():
                            continue
                        jobid, partition, name, state, elapsed, nodes, exitcode = parts[:7]
                        start = parts[7] if len(parts) > 7 else ""
                        # Un job riaccodato può comparire più volte: tiene l'ultima
                        # esecuzione (quella con l'orario di inizio più recente).
                        previous = rows_by_id.get(jobid)
                        if previous is not None and start < previous[0]:
                            continue
                        rows_by_id[jobid] = (start, [
                            jobid, name, partition,
                            state.split()[0] if state else "-",
                            self._format_history_start(start),
                            elapsed, nodes, exitcode,
                        ])
                    rows = [entry[1] for entry in rows_by_id.values()]
                    rows.sort(key=lambda row: int(row[0]), reverse=True)
                    self._history_truncated = len(rows) > self.HISTORY_LIMIT
                    self._history_rows = rows[: self.HISTORY_LIMIT]
                    self._history_paths = result["log_paths"]
                    self._history_label = req_label
                    self._history_source = "sacct"
                    self._history_fetched_at = time.monotonic()
                    self._history_loaded = True
                    self._sacct_available = True
                    history_updated = True
                else:
                    if asked_sacct and sacct_failed:
                        if self._sacct_available is not False:
                            self._set_status(
                                "accounting Slurm non disponibile: "
                                "storico ricostruito dai file di log"
                            )
                        self._sacct_available = False
                        self._sacct_retry_at = time.monotonic() + 300
                    if result["scanned_logs"]:
                        self._history_rows = result["log_rows"]
                        self._history_paths = result["log_paths"]
                        self._history_truncated = result["log_truncated"]
                        self._history_label = req_label
                        self._history_source = "logs"
                        self._history_fetched_at = time.monotonic()
                        self._history_loaded = True
                        history_updated = True

            sinfo_text = s_out if s_code == 0 else ""
            if show_gpu != bool(self.show_all_gpu_var.get()):
                self._squeue_reload = True
            self._update_job_ui(active, sinfo_text, show_gpu)
            if history_updated:
                self._update_history_ui(
                    self._history_rows, self._history_label,
                    self._history_truncated,
                )

            if q_code != 0:
                self.lbl_jobs_info.config(
                    text=(q_err.strip().splitlines()[0] if q_err.strip() else "squeue non disponibile")
                )
            if asked_sacct and sacct_failed and not history_updated:
                self.lbl_history_info.config(
                    text="Storico non aggiornato · accounting non disponibile"
                )

            # Il periodo è cambiato mentre la richiesta era in corso:
            # rifai subito la query con il nuovo intervallo.
            if history_updated and self._history_period()[1] != self._history_label:
                self.root.after(
                    100, lambda: self.refresh_squeue(silent=True, force_history=True)
                )

            if not silent:
                self._set_status(
                    f"Job aggiornati · {datetime.now().strftime('%H:%M:%S')}"
                )
            self._maybe_reload_jobs()

        def failed(exc):
            self._squeue_inflight = False
            if not silent:
                messagebox.showerror("Job", f"Impossibile leggere i job:\n{exc}")
            self.lbl_jobs_info.config(text="Coda non disponibile")
            self._maybe_reload_jobs()

        self._run_async(
            work, done, failed,
            busy_msg=None if silent else "Aggiornamento job...",
            show_error=False,
        )

    def _scan_log_history(self, dirs, since_epoch):
        """Storico di riserva ricavato dai file .out se sacct non è disponibile."""
        if getattr(self, "sftp_client", None) is None:
            return [], {}, False

        entries = {}
        seen_dirs = set()
        with self._sftp_lock:
            for base in dirs:
                for folder in (remote_join(base, "logs"), base):
                    if not folder or folder in seen_dirs:
                        continue
                    seen_dirs.add(folder)
                    try:
                        attrs = self.sftp_client.listdir_attr(folder)
                    except (IOError, OSError):
                        continue
                    for attr in attrs:
                        match = re.match(
                            r"^(.+?)_(?:job)?(\d+)\.out$", attr.filename
                        )
                        if not match:
                            continue
                        mtime = float(attr.st_mtime or 0)
                        if mtime and mtime < since_epoch:
                            continue
                        jobid = match.group(2)
                        previous = entries.get(jobid)
                        if previous is not None and previous["mtime"] >= mtime:
                            continue
                        entries[jobid] = {
                            "name": match.group(1),
                            "path": remote_join(folder, attr.filename),
                            "mtime": mtime,
                        }

        ordered = sorted(
            entries.items(), key=lambda item: item[1]["mtime"], reverse=True
        )
        truncated = len(ordered) > self.HISTORY_LIMIT
        rows = []
        paths = {}
        for jobid, entry in ordered[: self.HISTORY_LIMIT]:
            stamp = entry["mtime"]
            start = (
                datetime.fromtimestamp(stamp).strftime("%d/%m %H:%M")
                if stamp else "-"
            )
            rows.append([jobid, entry["name"], "-", "LOG", start, "-", "-", "-"])
            paths[jobid] = entry["path"]
        return rows, paths, truncated

    def _update_job_ui(self, active_jobs, sinfo_text, show_gpu=False):
        selected = self._selected_job_id(self.tree_jobs)
        for item in self.tree_jobs.get_children():
            self.tree_jobs.delete(item)

        for job in active_jobs:
            values = list(job[:9])
            while len(values) < 9:
                values.append("")
            values[7] = self._format_gres(values[7])
            values[8] = self._format_node(values[8])
            self.tree_jobs.insert(
                "", tk.END, values=values, tags=(self._job_tag(job[4]),)
            )
        self._restore_job_selection(self.tree_jobs, selected)

        def job_gpus(job):
            if len(job) <= 4:
                return 0
            state = str(job[4]).upper().split()[0]
            if state not in (
                "RUNNING", "COMPLETING", "CONFIGURING",
                "STAGE_OUT", "SUSPENDED",
            ):
                return 0
            return self._gpu_count(job[7] if len(job) > 7 else "")

        gpu_total = sum(job_gpus(job) for job in active_jobs)
        if show_gpu:
            if active_jobs:
                suffix = "attivo" if len(active_jobs) == 1 else "attivi"
                text = f"{len(active_jobs)} job GPU {suffix}"
                if gpu_total:
                    text += f" · {gpu_total} GPU in uso"
            else:
                text = "Nessun job GPU attivo."
        elif active_jobs:
            suffix = "attivo" if len(active_jobs) == 1 else "attivi"
            text = f"{len(active_jobs)} job {suffix}"
            if gpu_total:
                text += f" · {gpu_total} GPU in uso"
        else:
            text = "Nessun job attivo."
        self.lbl_jobs_info.config(text=text)

        self.txt_sinfo.delete("1.0", tk.END)
        if not sinfo_text.strip():
            self.txt_sinfo.insert(
                tk.END,
                "Nessuna informazione sulle partizioni GPU.\n"
                "Verifica di essere connesso a Giano.",
                "norm",
            )
            return

        stats = {}
        for line in sinfo_text.splitlines():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 3:
                continue
            partition = parts[0].replace("*", "").strip()
            try:
                nodes = int(parts[1])
            except ValueError:
                continue
            state = parts[2].lower()
            bucket = stats.setdefault(partition, {"idle": 0, "alloc": 0, "down": 0})
            if "idle" in state:
                bucket["idle"] += nodes
            elif "mix" in state or "alloc" in state:
                bucket["alloc"] += nodes
            else:
                bucket["down"] += nodes

        self.txt_sinfo.insert(tk.END, "DISPONIBILITA' GPU\n\n", "title")
        for partition, data in sorted(stats.items()):
            self.txt_sinfo.insert(tk.END, f"[{partition.upper()}]".ljust(12), "title")
            free = f"Liberi: {data['idle']}".ljust(15)
            self.txt_sinfo.insert(tk.END, free, "ok" if data["idle"] else "norm")
            busy = f"Occupati: {data['alloc']}".ljust(16)
            self.txt_sinfo.insert(tk.END, busy, "warn" if data["alloc"] else "norm")
            down = f"Offline: {data['down']}\n"
            self.txt_sinfo.insert(tk.END, down, "bad" if data["down"] else "norm")

    def _update_history_ui(self, rows, label, truncated):
        selected = self._selected_job_id(self.tree_history)
        for item in self.tree_history.get_children():
            self.tree_history.delete(item)

        for row in rows:
            self.tree_history.insert(
                "", tk.END, values=row, tags=(self._job_tag(row[3]),)
            )
        self._restore_job_selection(self.tree_history, selected)

        if not rows:
            if self._history_source == "logs":
                text = "Nessun log · accounting non disponibile"
            else:
                text = "Nessun job nello storico."
        else:
            extra = "+" if truncated else ""
            if self._history_source == "logs":
                text = (
                    f"{len(rows)}{extra} file di log · {label}"
                    " · accounting non disponibile"
                )
            else:
                text = f"{len(rows)}{extra} job · {label}"
        self.lbl_history_info.config(text=text)

    def _toggle_jobs_auto(self):
        if self.auto_jobs_var.get():
            self.refresh_squeue(silent=True)
            self._schedule_jobs_refresh()
        else:
            self._stop_jobs_auto_refresh()

    def _schedule_jobs_refresh(self):
        self._stop_jobs_auto_refresh()
        if self.auto_jobs_var.get() and self.connected:
            self._jobs_auto_id = self.root.after(10000, self._jobs_auto_tick)

    def _jobs_auto_tick(self):
        self._jobs_auto_id = None
        if self.connected and self.auto_jobs_var.get():
            self.refresh_squeue(silent=True)
            self._schedule_jobs_refresh()

    def _stop_jobs_auto_refresh(self):
        if self._jobs_auto_id:
            try:
                self.root.after_cancel(self._jobs_auto_id)
            except Exception:
                pass
            self._jobs_auto_id = None

    def _maybe_reload_jobs(self):
        if not self._squeue_reload:
            return
        self._squeue_reload = False
        if self.connected:
            self.root.after(50, lambda: self.refresh_squeue(silent=True))

    def cancel_job(self):
        selection = self.tree_jobs.selection()
        if not selection:
            messagebox.showinfo("Cancella job", "Seleziona un job attivo dalla lista.")
            return
        values = self.tree_jobs.item(selection[0])["values"]
        job_id = str(values[0])
        owner = str(values[3]).strip() if len(values) > 3 else ""
        if owner and self.current_user and owner != self.current_user:
            messagebox.showinfo(
                "Cancella job",
                f"Il job {job_id} appartiene a {owner}: "
                "puoi annullare solo i tuoi job.",
            )
            return
        state = str(values[4]).upper().split()[0] if len(values) > 4 else ""
        if state not in ("PENDING", "CONFIGURING", "RUNNING", "COMPLETING"):
            messagebox.showinfo(
                "Cancella job", f"Il job {job_id} è già terminato ({state or 'sconosciuto'})."
            )
            return
        if not messagebox.askyesno(
            "Cancella job", f"Annullare il job {job_id}?", icon="warning"
        ):
            return

        def work():
            code, _out, err = self._ssh_exec(f"scancel {shlex.quote(job_id)}")
            if code != 0:
                raise RuntimeError(err.strip() or f"scancel ha restituito {code}")
            return job_id

        def done(cancelled_id):
            self._set_status(f"Job {cancelled_id} annullato")
            self.root.after(
                800, lambda: self.refresh_squeue(force_history=True)
            )

        self._run_async(work, done, busy_msg=f"Annullamento job {job_id}...")

    # ----------------------------- TAB 5: OUTPUT -----------------------------
    def _build_output_tab(self):
        tab = self.tab_output

        top = ttk.Frame(tab)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Cartella:").pack(side=tk.LEFT)
        ttk.Label(
            top, textvariable=self.path_var, style="Muted.TLabel"
        ).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(
            top, text="● Aggiornamento automatico", style="Muted.TLabel"
        ).pack(side=tk.LEFT)

        path_row = ttk.Frame(tab)
        path_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(path_row, text="File aperto:").pack(side=tk.LEFT)
        self.lbl_log_path_var = tk.StringVar(value="nessuno")
        ttk.Label(
            path_row, textvariable=self.lbl_log_path_var, style="Muted.TLabel",
            wraplength=880, justify="left",
        ).pack(side=tk.LEFT, padx=(6, 0))

        bottom = ttk.Frame(tab)
        bottom.pack(fill=tk.X, pady=(8, 6))
        ttk.Label(bottom, text="File:").pack(side=tk.LEFT)
        self.combo_outputs = ttk.Combobox(bottom, width=42, state="readonly")
        self.combo_outputs.pack(side=tk.LEFT, padx=(6, 12))
        self.combo_outputs.bind("<<ComboboxSelected>>", self.read_output)

        self.log_follow_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bottom, text="Segui output (auto-aggiorna)",
            variable=self.log_follow_var, command=self._toggle_log_follow,
        ).pack(side=tk.LEFT)
        ttk.Button(
            bottom, text="Apri nell'editor", command=self.open_output_in_editor
        ).pack(side=tk.RIGHT)
        ttk.Button(
            bottom, text="Salva copia locale", command=self.save_output_copy
        ).pack(side=tk.RIGHT, padx=8)
        ttk.Button(
            bottom, text="Cerca (Ctrl+F)", command=self._show_log_search
        ).pack(side=tk.RIGHT, padx=8)

        text_box = ttk.Frame(tab)
        text_box.pack(fill=tk.BOTH, expand=True)
        text_box.rowconfigure(0, weight=1)
        text_box.columnconfigure(0, weight=1)

        self.txt_output_log = tk.Text(
            text_box, bg="#0f1115", fg="#d4d4d4", insertbackground="#d4d4d4",
            selectbackground="#264f78", font=(MONO_FONT, 10), wrap=tk.NONE,
            relief=tk.FLAT, borderwidth=0, padx=10, pady=8, state=tk.DISABLED,
        )
        vbar = ttk.Scrollbar(text_box, orient=tk.VERTICAL, command=self.txt_output_log.yview)
        hbar = ttk.Scrollbar(text_box, orient=tk.HORIZONTAL, command=self.txt_output_log.xview)
        self.txt_output_log.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.txt_output_log.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        self.txt_output_log.tag_configure("error", foreground="#ff7b72")
        self.txt_output_log.tag_configure("warn", foreground="#f0b72f")
        self.txt_output_log.tag_configure("meta", foreground="#58a6ff")

        self.log_search = TextSearchBar(
            tab, self.txt_output_log,
            pack_kwargs={"fill": tk.X, "pady": (0, 6), "before": text_box},
            on_status=self._set_status,
            on_show=self._on_log_search_shown,
            on_hide=self._on_log_search_hidden,
        )

        self.txt_output_log.bind("<Control-c>", self._copy_output_selection)
        self.txt_output_log.bind("<Control-f>", self._show_log_search)
        self.txt_output_log.bind("<F3>", lambda _e: self.log_search.next())
        self.txt_output_log.bind("<Shift-F3>", lambda _e: self.log_search.previous())
        self.txt_output_log.bind("<Button-3>", self._show_output_menu)
        self.txt_output_log.bind("<Button-2>", self._show_output_menu)

        self.output_menu = tk.Menu(self.txt_output_log, tearoff=0)
        self.output_menu.add_command(label="Copia selezione", command=self._copy_output_selection)
        self.output_menu.add_command(label="Seleziona tutto", command=lambda: (
            self.txt_output_log.tag_add(tk.SEL, "1.0", tk.END)
        ))

        self._set_output_text(
            "L'ultimo file .out della cartella corrente verra aperto e "
            "aggiornato automaticamente.\n"
            "Fai doppio clic su un job nella scheda «Job» per aprire un log "
            "specifico."
        )

    def _show_output_menu(self, event):
        self._close_context_menus()
        self.output_menu.post(event.x_root, event.y_root)

    def _copy_output_selection(self, _event=None):
        try:
            text = self.txt_output_log.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("Selezione copiata negli appunti")
        return "break"

    def _set_output_text(self, text):
        try:
            if text and not text.endswith("\n"):
                text += "\n"
            self.txt_output_log.configure(state=tk.NORMAL)
            self.txt_output_log.delete("1.0", tk.END)
            self.txt_output_log.insert("1.0", text)
            self.txt_output_log.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _append_output(self, text):
        if not text:
            return
        try:
            self.txt_output_log.configure(state=tk.NORMAL)
            start = self.txt_output_log.index("end-1c")
            self.txt_output_log.insert(tk.END, text)
            end = self.txt_output_log.index("end-1c")
            self._highlight_log_range(start, end)
            self.txt_output_log.configure(state=tk.DISABLED)
            if self.log_follow_var.get() and not self._log_search_active:
                self.txt_output_log.see(tk.END)
        except Exception:
            pass

    def _highlight_log_range(self, start_index, end_index):
        """Colora le righe di errore/avviso appena inserite nel log."""
        try:
            first = int(str(start_index).split(".")[0])
            last = int(str(end_index).split(".")[0])
        except (TypeError, ValueError):
            return
        error_re = re.compile(
            r"traceback|error|errore|exception|failed|failure|killed|"
            r"segmentation fault|fatal",
            re.IGNORECASE,
        )
        warn_re = re.compile(r"\bwarning\b|\bwarn\b|attenzione", re.IGNORECASE)
        try:
            chunk = self.txt_output_log.get(start_index, end_index)
        except tk.TclError:
            return
        if not (
            error_re.search(chunk)
            or warn_re.search(chunk)
            or "===" in chunk
            or "---" in chunk
        ):
            return
        for line_no in range(first, last + 1):
            try:
                line = self.txt_output_log.get(f"{line_no}.0", f"{line_no}.end")
            except tk.TclError:
                continue
            if not line:
                continue
            if line.startswith("===") or line.startswith("---"):
                tag = "meta"
            elif error_re.search(line):
                tag = "error"
            elif warn_re.search(line):
                tag = "warn"
            else:
                continue
            try:
                self.txt_output_log.tag_add(tag, f"{line_no}.0", f"{line_no}.end")
            except tk.TclError:
                continue

    def _show_log_search(self, _event=None):
        return self.log_search.show()

    def _hide_log_search(self, _event=None):
        return self.log_search.hide()

    def _on_log_search_shown(self):
        self._log_search_active = True

    def _on_log_search_hidden(self):
        self._log_search_active = False
        if self.log_follow_var.get():
            try:
                self.txt_output_log.see(tk.END)
            except tk.TclError:
                pass

    def _on_global_search(self, event=None):
        """Ctrl+F apre la ricerca solo quando è visibile la scheda Output."""
        try:
            if self.notebook.select() != str(self.tab_output):
                return None
        except Exception:
            return None
        if (
            event is not None
            and getattr(event, "widget", None) is self.log_search.entry
        ):
            return None
        return self._show_log_search(event)

    def _global_log_nav(self, forward):
        try:
            if self.notebook.select() != str(self.tab_output):
                return None
        except Exception:
            return None
        return self.log_search.next() if forward else self.log_search.previous()

    def _auto_load_output(self):
        """Aggiorna da solo l'elenco .out e segue il log aperto."""
        if not self.connected:
            return
        if not self.log_follow_var.get():
            self.log_follow_var.set(True)
            self._toggle_log_follow()
        self.find_outputs(auto=True)

    def _schedule_output_auto_retry(self):
        """Riprova a cercare un .out finché il job non inizia a scriverlo."""
        self._stop_output_auto_retry()
        if not self.connected or self.current_log_path:
            return
        try:
            if self.notebook.index(self.notebook.select()) != 4:
                return
        except Exception:
            return
        self._auto_output_retry_id = self.root.after(
            3000, self._retry_auto_load_output
        )

    def _retry_auto_load_output(self):
        self._auto_output_retry_id = None
        self._auto_load_output()

    def _stop_output_auto_retry(self):
        if self._auto_output_retry_id:
            try:
                self.root.after_cancel(self._auto_output_retry_id)
            except Exception:
                pass
            self._auto_output_retry_id = None

    def find_outputs(self, auto=False):
        if not self.connected:
            if not auto:
                messagebox.showwarning("Output", "Connettiti prima a un host.")
            return
        path = self._current_path()
        if not auto:
            self._stop_output_auto_retry()

        def work():
            found = []
            directories = [(path, "")]
            if posixpath.basename(path.rstrip("/")) != "logs":
                directories.append((remote_join(path, "logs"), "logs/"))
            with self._sftp_lock:
                for directory, prefix in directories:
                    try:
                        entries = self.sftp_client.listdir_attr(directory)
                    except IOError:
                        continue
                    for entry in entries:
                        if (
                            entry.filename.endswith(".out")
                            and not stat.S_ISDIR(entry.st_mode)
                        ):
                            found.append((
                                entry.st_mtime or 0,
                                prefix + entry.filename,
                                remote_join(directory, entry.filename),
                            ))
            found.sort(key=lambda item: item[0], reverse=True)
            return [(name, full_path) for _mtime, name, full_path in found]

        def done(items):
            files = [name for name, _full_path in items]
            self.combo_outputs["values"] = files
            self._log_paths.update(dict(items))

            if auto and self.current_log_path:
                # Il log già aperto resta selezionato: aggiorno solo l'elenco.
                current_name = posixpath.basename(self.current_log_path)
                self._log_paths.setdefault(current_name, self.current_log_path)
                values = [current_name] + [
                    v for v in files
                    if v != current_name
                    and self._log_paths.get(v) != self.current_log_path
                ]
                self.combo_outputs["values"] = values
                self.combo_outputs.set(current_name)
                return

            if not files:
                if auto:
                    self._set_output_text(
                        f"--- In attesa di un file .out ---\n"
                        f"Cartella: {path}\n"
                        "Il log apparira qui appena il job inizia a scrivere."
                    )
                    self._set_status(
                        "In attesa di un file .out · aggiornamento automatico"
                    )
                    self._schedule_output_auto_retry()
                else:
                    self._set_output_text(f"Nessun file .out trovato in:\n{path}")
                    self._set_status("Nessun file .out trovato")
                return

            self.combo_outputs.current(0)
            self.read_output()
            self._set_status(f"Trovati {len(files)} file .out · {path}")

        self._run_async(
            work, done,
            busy_msg=None if auto else "Ricerca file .out...",
        )

    def _open_output_path(self, path, waiting=False):
        if not path:
            return
        self.notebook.select(self.tab_output)
        self._start_log(path, waiting=waiting)

    def _start_log(self, path, waiting=False):
        name = posixpath.basename(path)
        self.current_log_path = path
        self.current_log_size = 0
        self._stop_log_polling()
        self._log_paths[name] = path
        values = [
            v for v in (self.combo_outputs["values"] or [])
            if v != name and self._log_paths.get(v) != path
        ]
        values.insert(0, name)
        self.combo_outputs["values"] = values
        self.combo_outputs.set(name)
        self.lbl_log_path_var.set(path)
        self._log_waiting = waiting
        if waiting:
            self._set_output_text(
                f"--- In attesa di {name} ---\n"
                "Il file apparira qui appena il job inizia a scrivere.\n"
            )
        else:
            self._set_output_text(f"--- Lettura output: {name} ---\n")
        self.log_follow_var.set(True)
        self._poll_log_file(self._log_token)

    def read_output(self, _event=None):
        if not self.connected:
            return
        filename = self.combo_outputs.get().strip()
        if not filename:
            return
        path = self._log_paths.get(filename) or remote_join(self._current_path(), filename)
        self._start_log(path)
        self._set_status(f"Apertura {filename}...")

    def _poll_log_file(self, token):
        if (
            not self.connected
            or token != self._log_token
            or not self.current_log_path
        ):
            return
        path = self.current_log_path
        offset = self.current_log_size

        def work():
            start = offset
            with self._sftp_lock:
                attr = self.sftp_client.stat(path)
                size = attr.st_size
                reset = False
                if size < start:
                    start = 0
                    reset = True
                data = ""
                if size > start:
                    with self.sftp_client.file(path, "r") as fh:
                        fh.seek(start)
                        data = fh.read().decode("utf-8", errors="replace")
                return size, data, reset

        def done(result):
            if token != self._log_token:
                return
            size, data, reset = result
            if reset:
                self._set_output_text(
                    f"--- Lettura output: {os.path.basename(path)} ---\n"
                )
                self._log_waiting = False
            elif self._log_waiting and data:
                self._set_output_text(
                    f"--- Lettura output: {os.path.basename(path)} ---\n"
                )
                self._log_waiting = False
            self.current_log_size = size
            self._append_output(data)
            if data:
                self._set_status(
                    f"{os.path.basename(path)} · {human_size(size)} · "
                    f"{datetime.now().strftime('%H:%M:%S')}"
                )
            self._schedule_log_poll(token)

        def failed(_exc):
            if token == self._log_token:
                if self.log_follow_var.get() and self.current_log_size == 0:
                    self._set_status(
                        f"In attesa di {os.path.basename(path)}..."
                    )
                self._schedule_log_poll(token)

        self._run_async(work, done, failed, show_error=False)

    def _schedule_log_poll(self, token):
        self._stop_log_polling_timer()
        if (
            token != self._log_token
            or not self.connected
            or not self.current_log_path
            or not self.log_follow_var.get()
        ):
            return
        self._log_poll_id = self.root.after(
            2000, lambda: self._poll_log_file(token)
        )

    def _stop_log_polling_timer(self):
        if self._log_poll_id:
            try:
                self.root.after_cancel(self._log_poll_id)
            except Exception:
                pass
            self._log_poll_id = None

    def _stop_log_polling(self):
        self._log_token += 1
        self._stop_log_polling_timer()
        self._stop_output_auto_retry()

    def _toggle_log_follow(self):
        if self.log_follow_var.get():
            if self.connected and self.current_log_path:
                self._log_token += 1
                self._poll_log_file(self._log_token)
        else:
            self._stop_log_polling_timer()

    def open_output_in_editor(self):
        if not self.connected or not self.current_log_path:
            messagebox.showinfo("Output", "Seleziona prima un file di output.")
            return
        RemoteEditorWindow(
            self.root, self.sftp_client, self.current_log_path, self._sftp_lock
        )

    def save_output_copy(self):
        content = self.txt_output_log.get("1.0", "end-1c").strip()
        if not content:
            messagebox.showinfo("Output", "Non c'e contenuto da salvare.")
            return
        initial = os.path.basename(self.current_log_path) if self.current_log_path else "output.txt"
        local_path = filedialog.asksaveasfilename(
            title="Salva copia locale", initialfile=initial,
            defaultextension=".txt",
        )
        if not local_path:
            return
        try:
            with open(local_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self._set_status(f"Copia salvata · {local_path}")
        except Exception as exc:
            messagebox.showerror("Salvataggio", str(exc))

    # ----------------------------- impostazioni / chiusura -----------------------------
    def _save_current_settings(self):
        data = {
            "username": self.ent_user.get().strip() if self.remember_var.get() else "",
            "remember": bool(self.remember_var.get()),
            "mode": self.conn_mode.get(),
            "manual_host": self.combo_manual_host.get(),
            "show_hidden": bool(self.show_hidden_var.get()),
        }
        save_settings(data)

    def _on_close(self):
        if self._closing:
            return
        try:
            self._save_current_settings()
        except Exception:
            pass
        self._closing = True

        self._stop_log_polling()
        self._stop_jobs_auto_refresh()
        details = getattr(self, "_details_win", None)
        if details is not None:
            try:
                details.close()
            except Exception:
                pass
        if self._preview_after:
            try:
                self.root.after_cancel(self._preview_after)
            except Exception:
                pass
        if self._filter_after is not None:
            try:
                self.root.after_cancel(self._filter_after)
            except Exception:
                pass

        try:
            if self.sftp_client:
                self.sftp_client.close()
        except Exception:
            pass
        try:
            if self.ssh_client:
                self.ssh_client.close()
        except Exception:
            pass

        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self.dispatcher.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _report_exception(self, exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb)
        if self._closing:
            return
        try:
            messagebox.showerror(
                "Errore inatteso",
                "Si e verificato un errore imprevisto:\n\n"
                + "".join(traceback.format_exception_only(exc_type, exc_value)).strip(),
            )
        except Exception:
            pass


class JobDetailsWindow:
    """Finestra con informazioni statiche e utilizzo live di un job SLURM."""

    REFRESH_MS = 3000

    def __init__(self, app, job_id):
        self.app = app
        self.job_id = str(job_id)
        self._closed = False
        self._inflight = False
        self._after_id = None
        self._info_vars = {}
        self._diag = []

        self.win = tk.Toplevel(app.root)
        self.win.title(f"Dettagli job {self.job_id}")
        self.win.geometry("940x720")
        self.win.minsize(820, 560)
        self.win.configure(bg=BASE_BG)
        try:
            self.win.transient(app.root)
        except Exception:
            pass
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.refresh()

    # ----------------------------- costruzione UI -----------------------------
    def _build(self):
        header = ttk.Frame(self.win, style="Card.TFrame", padding=(14, 10))
        header.pack(fill=tk.X)
        self.title_var = tk.StringVar(value=f"Job {self.job_id}")
        ttk.Label(
            header, textvariable=self.title_var, style="CardSection.TLabel",
            font=(UI_FONT, 13, "bold"),
        ).pack(side=tk.LEFT)
        self.state_var = tk.StringVar(value="…")
        self.lbl_state = tk.Label(
            header, textvariable=self.state_var, bg=CARD_BG, fg=MUTED,
            font=(UI_FONT, 9, "bold"),
        )
        self.lbl_state.pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(
            header, text="Chiudi", command=self.close
        ).pack(side=tk.RIGHT)
        ttk.Button(
            header, text="Aggiorna ora", command=self.refresh
        ).pack(side=tk.RIGHT, padx=(0, 8))

        info = ttk.LabelFrame(
            self.win, text=" Informazioni job ", padding=10,
            style="Card.TLabelframe",
        )
        info.pack(fill=tk.X, padx=12, pady=(8, 0))
        info.columnconfigure(1, weight=1)
        info.columnconfigure(3, weight=1)
        self._info_row(info, 0, "Job ID", "jobid", "Nome", "name")
        self._info_row(info, 1, "Utente", "owner", "Partizione", "partition")
        self._info_row(info, 2, "Nodi", "nodes", "CPU", "cpus")
        self._info_row(info, 3, "Task", "tasks", "GPU", "gpu")
        self._info_row(info, 4, "Tempo", "runtime", "Limite", "timelimit")
        self._info_row(info, 5, "Inizio", "start", "Fine", "end")
        self._wide_info_row(info, 6, "TRES", "tres")
        self._wide_info_row(info, 7, "Nodo/i", "nodelist")
        self._wide_info_row(info, 8, "Work dir", "workdir")
        self._wide_info_row(info, 9, "Output", "stdout")
        self._wide_info_row(info, 10, "Comando", "command")

        live = ttk.LabelFrame(
            self.win, text=" Utilizzo in tempo reale ", padding=10,
            style="Card.TLabelframe",
        )
        live.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 0))

        self.cpu_var = tk.StringVar(value="CPU: in attesa di dati…")
        ttk.Label(
            live, textvariable=self.cpu_var, style="CardValueMono.TLabel",
            wraplength=860, justify="left",
        ).pack(anchor="w")

        ttk.Label(
            live, text="GPU allocate", style="CardSection.TLabel"
        ).pack(anchor="w", pady=(8, 2))
        self.gpu_note_var = tk.StringVar(value="GPU: in attesa di dati…")
        ttk.Label(
            live, textvariable=self.gpu_note_var, style="CardMuted.TLabel",
            wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 4))

        gpu_box = ttk.Frame(live, style="Card.TFrame")
        gpu_box.pack(fill=tk.X)
        gpu_box.columnconfigure(0, weight=1)
        gpu_columns = ("node", "gpu", "model", "util", "mem", "temp", "power")
        self.tree_gpu = ttk.Treeview(
            gpu_box, columns=gpu_columns, show="headings",
            selectmode="none", height=4,
        )
        gpu_headings = {
            "node": ("Nodo", 190), "gpu": ("GPU", 50),
            "model": ("Modello", 230), "util": ("Util.", 70),
            "mem": ("Memoria", 150), "temp": ("Temp.", 70),
            "power": ("Potenza", 85),
        }
        for column in gpu_columns:
            text, width = gpu_headings[column]
            self.tree_gpu.heading(column, text=text)
            self.tree_gpu.column(
                column, width=width, anchor="center",
                stretch=(column == "model"),
            )
        gpu_scroll = ttk.Scrollbar(
            gpu_box, orient=tk.VERTICAL, command=self.tree_gpu.yview
        )
        self.tree_gpu.configure(yscrollcommand=gpu_scroll.set)
        self.tree_gpu.grid(row=0, column=0, sticky="nsew")
        gpu_scroll.grid(row=0, column=1, sticky="ns")

        ttk.Label(
            live, text="Step / processi", style="CardSection.TLabel"
        ).pack(anchor="w", pady=(8, 2))
        steps_box = ttk.Frame(live, style="Card.TFrame")
        steps_box.pack(fill=tk.X)
        steps_box.columnconfigure(0, weight=1)
        step_columns = ("step", "tasks", "cputime", "rss")
        self.tree_steps = ttk.Treeview(
            steps_box, columns=step_columns, show="headings",
            selectmode="none", height=3,
        )
        step_headings = {
            "step": ("Step", 180), "tasks": ("Task", 70),
            "cputime": ("CPU time", 120), "rss": ("RSS max", 120),
        }
        for column in step_columns:
            text, width = step_headings[column]
            self.tree_steps.heading(column, text=text)
            self.tree_steps.column(column, width=width, anchor="center")
        steps_scroll = ttk.Scrollbar(
            steps_box, orient=tk.VERTICAL, command=self.tree_steps.yview
        )
        self.tree_steps.configure(yscrollcommand=steps_scroll.set)
        self.tree_steps.grid(row=0, column=0, sticky="nsew")
        steps_scroll.grid(row=0, column=1, sticky="ns")

        footer = ttk.Frame(self.win, padding=(12, 6))
        footer.pack(fill=tk.X)
        self.status_var = tk.StringVar(
            value=f"Aggiornamento automatico ogni {self.REFRESH_MS // 1000} s."
        )
        ttk.Label(
            footer, textvariable=self.status_var, style="Muted.TLabel"
        ).pack(side=tk.LEFT)

    def _info_row(self, parent, row, left_text, left_key, right_text, right_key):
        ttk.Label(
            parent, text=left_text, style="CardMuted.TLabel"
        ).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
        left_var = tk.StringVar(value="…")
        self._info_vars[left_key] = left_var
        ttk.Label(
            parent, textvariable=left_var, style="CardValue.TLabel",
            wraplength=250, justify="left",
        ).grid(row=row, column=1, sticky="nw", padx=(0, 18), pady=2)

        ttk.Label(
            parent, text=right_text, style="CardMuted.TLabel"
        ).grid(row=row, column=2, sticky="nw", padx=(0, 8), pady=2)
        right_var = tk.StringVar(value="…")
        self._info_vars[right_key] = right_var
        ttk.Label(
            parent, textvariable=right_var, style="CardValue.TLabel",
            wraplength=250, justify="left",
        ).grid(row=row, column=3, sticky="nw", pady=2)

    def _wide_info_row(self, parent, row, label, key):
        ttk.Label(
            parent, text=label, style="CardMuted.TLabel"
        ).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
        var = tk.StringVar(value="…")
        self._info_vars[key] = var
        ttk.Label(
            parent, textvariable=var, style="CardValue.TLabel",
            wraplength=840, justify="left",
        ).grid(
            row=row, column=1, columnspan=3, sticky="w", pady=2
        )

    # ----------------------------- ciclo di aggiornamento -----------------------------
    def winfo_exists(self):
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    def lift(self):
        try:
            self.win.lift()
        except Exception:
            pass

    def focus_force(self):
        try:
            self.win.focus_force()
        except Exception:
            pass

    def refresh(self):
        if self._closed:
            return
        if self._after_id is not None:
            try:
                self.win.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._inflight:
            return
        self._inflight = True
        self.status_var.set("Lettura dati dal cluster…")
        self.app._run_async(
            self._query, self._on_data, self._on_error, show_error=False
        )

    def _schedule(self):
        if self._closed:
            return
        self._after_id = self.win.after(self.REFRESH_MS, self.refresh)

    def _on_data(self, data):
        self._inflight = False
        if self._closed:
            return
        self._apply(data)
        self._schedule()

    def _on_error(self, exc):
        self._inflight = False
        if self._closed:
            return
        message = str(exc).strip() or exc.__class__.__name__
        self.status_var.set(
            f"Errore: {message.splitlines()[0][:180]} · "
            f"nuovo tentativo tra {self.REFRESH_MS // 1000} s"
        )
        self._schedule()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._after_id is not None:
            try:
                self.win.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if getattr(self.app, "_details_win", None) is self:
            self.app._details_win = None
        try:
            self.win.destroy()
        except Exception:
            pass

    # ----------------------------- raccolta dati -----------------------------
    def _query(self):
        fields = self._read_job()
        result = {
            "job": fields, "owner": "", "state": "", "num_cpus": 0,
            "num_nodes": 0, "gpu_count": 0, "cpu": {}, "gpu_rows": [],
            "gpu_note": "", "error": "",
        }
        if not fields:
            result["error"] = (
                "Job non presente in SLURM (terminato o rimosso). "
                "Per lo storico locale apri il file .out."
            )
            result["cpu"] = {"text": "CPU: non disponibile per un job non più in SLURM."}
            result["gpu_note"] = "GPU: non disponibile."
            return result

        owner = self._owner(fields.get("UserId", ""))
        state = (fields.get("JobState", "") or "").split()[0]
        num_cpus = self._as_int(fields.get("NumCPUs"))
        num_nodes = self._as_int(fields.get("NumNodes"))
        if not num_nodes:
            node_list = fields.get("NodeList", "")
            if node_list and node_list.lower() not in ("(null)", "none", "unknown"):
                num_nodes = len([n for n in node_list.split(",") if n.strip()])
        gpu_count = self._gpu_count(fields.get("TRES", ""))
        gres_gpu = self._gpu_count(fields.get("Gres", "")) * max(1, num_nodes)
        gpu_count = max(gpu_count, gres_gpu)

        result.update({
            "owner": owner,
            "state": state,
            "num_cpus": num_cpus,
            "num_nodes": num_nodes,
            "gpu_count": gpu_count,
        })

        live_states = {
            "RUNNING", "COMPLETING", "STAGE_OUT", "SUSPENDED",
        }
        if state not in live_states:
            result["cpu"] = {
                "text": (
                    f"CPU: job in stato {state or 'sconosciuto'} · "
                    "statistiche live non disponibili."
                )
            }
            result["gpu_note"] = "GPU: statistiche live non disponibili."
            return result

        if not owner or owner != self.app.current_user:
            result["cpu"] = {
                "text": "CPU: statistiche live disponibili solo per i tuoi job."
            }
            result["gpu_note"] = (
                "GPU: statistiche live disponibili solo per i tuoi job."
            )
            return result

        result["cpu"] = self._sample_cpu(num_cpus)
        if gpu_count > 0 and num_nodes > 0:
            rows, note = self._sample_gpu(num_nodes)
            result["gpu_rows"] = rows
            result["gpu_note"] = note
        else:
            result["gpu_note"] = "Nessuna GPU allocata a questo job."
        return result

    def _read_job(self):
        code, out, err = self.app._ssh_exec(
            f"scontrol show job {shlex.quote(self.job_id)} -o"
        )
        if "JobId=" not in out:
            return {}
        line = next(
            (candidate for candidate in out.splitlines() if "JobId=" in candidate),
            "",
        )
        return self._parse_scontrol_fields(line)

    @staticmethod
    def _parse_scontrol_fields(text):
        fields = {}
        for token in re.split(
            r"\s+(?=[A-Za-z][A-Za-z0-9_]*=)", str(text).strip()
        ):
            key, sep, value = token.partition("=")
            if sep:
                fields[key] = value.strip()
        return fields

    @staticmethod
    def _owner(value):
        return str(value or "").split("(", 1)[0].strip()

    @staticmethod
    def _as_int(value):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _gpu_count(value):
        text = str(value or "")
        return sum(
            int(match.group(1))
            for match in re.finditer(
                r"gpu(?::[A-Za-z0-9_.-]+)?[:=](\d+)", text, re.IGNORECASE
            )
        )

    def _sample_cpu(self, num_cpus):
        fmt = "JobID,NTasks,AveCPU,MaxRSS,AveRSS"
        quoted_fmt = shlex.quote(fmt)
        job = shlex.quote(self.job_id)
        command = (
            f"sstat -j {job} -P -o {quoted_fmt} 2>&1; "
            "echo __HPC_SPLIT__; sleep 1; "
            f"sstat -j {job} -P -o {quoted_fmt} 2>&1"
        )
        start = time.monotonic()
        code, out, err = self.app._ssh_exec(command)
        wall = max(1.0, time.monotonic() - start)

        chunks = out.split("__HPC_SPLIT__")
        first_rows = self._parse_stat_rows(chunks[0] if chunks else "")
        second_rows = self._parse_stat_rows(chunks[1] if len(chunks) > 1 else "")
        rows = second_rows or first_rows
        if not rows:
            detail = (err or out).strip()
            detail = detail.splitlines()[0] if detail else f"sstat ha restituito {code}"
            return {
                "text": f"CPU: non disponibile · {detail}",
                "rows": [], "cores": None, "percent": None,
                "cpu_time": None, "rss_total": 0, "rss_max": 0,
            }

        total_first = self._total_cpu(first_rows)
        total_second = self._total_cpu(second_rows)
        cpu_time = total_second if total_second is not None else total_first
        cores = None
        percent = None
        if (
            total_first is not None and total_second is not None
            and total_second >= total_first
        ):
            cores = max(0.0, (total_second - total_first) / wall)
            if num_cpus > 0:
                # sstat può conteggiare più CPU del richiesto in casi di
                # oversubscription o step concorrenti: per la percentuale
                # consideriamo al massimo le CPU allocate al job.
                cores = min(cores, float(num_cpus))
                percent = cores / num_cpus * 100.0

        rss_total = sum(
            (row["ave_rss"] or 0) * max(1, row["ntasks"]) for row in rows
        )
        rss_max = max((row["max_rss"] or 0) for row in rows)

        pieces = []
        if percent is not None:
            pieces.append(f"{percent:.1f}% di {num_cpus} CPU")
        if cores is not None:
            pieces.append(f"{cores:.2f} core")
        if cpu_time is not None:
            pieces.append(f"CPU time {self._format_duration(cpu_time)}")
        if rss_total:
            pieces.append(f"RSS ~{self._format_mb(rss_total)}")
        elif rss_max:
            pieces.append(f"RSS max {self._format_mb(rss_max)}")
        if not pieces:
            pieces.append("nessun dato disponibile")
        return {
            "text": "CPU: " + " · ".join(pieces),
            "rows": rows,
            "cores": cores,
            "percent": percent,
            "cpu_time": cpu_time,
            "rss_total": rss_total,
            "rss_max": rss_max,
        }

    @staticmethod
    def _parse_stat_rows(text):
        rows = []
        for line in str(text).splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 5:
                continue
            if not re.match(r"^\d+(?:[._].*)?$", parts[0]):
                continue
            try:
                ntasks = int(float(parts[1])) if parts[1] not in ("", "N/A") else 1
            except ValueError:
                ntasks = 1
            cpu_time = JobDetailsWindow._parse_slurm_time(parts[2])
            max_rss = JobDetailsWindow._parse_size_mb(parts[3])
            ave_rss = JobDetailsWindow._parse_size_mb(parts[4])
            rows.append({
                "step": parts[0],
                "ntasks": max(1, ntasks),
                "cpu_time": cpu_time,
                "cpu_total": (
                    (cpu_time or 0.0) * max(1, ntasks)
                    if cpu_time is not None else None
                ),
                "max_rss": max_rss,
                "ave_rss": ave_rss,
            })
        return rows

    @staticmethod
    def _total_cpu(rows):
        total = 0.0
        found = False
        for row in rows:
            if row.get("cpu_total") is None:
                continue
            total += row["cpu_total"]
            found = True
        return total if found else None

    def _sample_gpu(self, num_nodes):
        script = (
            "H=$(hostname); "
            'G="${SLURM_JOB_GPUS:-};${CUDA_VISIBLE_DEVICES:-}"; '
            "nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,"
            "memory.used,memory.total,temperature.gpu,power.draw "
            '--format=csv,noheader,nounits | sed "s|^|$H;$G;|"'
        )
        ntasks = max(1, int(num_nodes))
        base = (
            f"timeout 8 srun --jobid={shlex.quote(self.job_id)} --overlap "
            f"--ntasks={ntasks} --ntasks-per-node=1 bash -c "
            f"{shlex.quote(script)}"
        )
        code, out, err = self.app._ssh_exec(base)
        rows = self._parse_gpu_output(out)
        if code != 0 and not rows:
            retry = (
                f"timeout 8 srun --jobid={shlex.quote(self.job_id)} "
                f"--ntasks={ntasks} --ntasks-per-node=1 bash -c "
                f"{shlex.quote(script)}"
            )
            code2, out2, err2 = self.app._ssh_exec(retry)
            if out2.strip() or code2 == 0:
                code, out, err = code2, out2, err2
                rows = self._parse_gpu_output(out)

        if code != 0 and not rows and ntasks > 1:
            # Se lo step multi-nodo non è consentito (per esempio perché il job
            # ha un solo task), prova almeno a leggere la GPU del primo nodo.
            one_task = (
                f"timeout 8 srun --jobid={shlex.quote(self.job_id)} --overlap "
                f"--ntasks=1 bash -c {shlex.quote(script)}"
            )
            code3, out3, err3 = self.app._ssh_exec(one_task)
            rows = self._parse_gpu_output(out3)
            if not rows:
                one_task = (
                    f"timeout 8 srun --jobid={shlex.quote(self.job_id)} "
                    f"--ntasks=1 bash -c {shlex.quote(script)}"
                )
                code3, out3, err3 = self.app._ssh_exec(one_task)
                rows = self._parse_gpu_output(out3)
            if rows:
                return rows, (
                    f"{len(rows)} GPU sul primo nodo · step multi-nodo non "
                    "disponibile"
                )
            code, out, err = code3, out3, err3

        if rows:
            return rows, (
                f"{len(rows)} GPU rilevate · aggiornamento ogni "
                f"{self.REFRESH_MS // 1000} s"
            )
        detail = (err or out).strip()
        detail = detail.splitlines()[0] if detail else (
            "timeout: srun non ha ottenuto risorse in tempo"
            if code == 124 else f"srun/nvidia-smi ha restituito {code}"
        )
        return [], f"GPU: non disponibile · {detail}"

    @staticmethod
    def _parse_gpu_output(text):
        rows = []
        all_rows = []
        for line in str(text).splitlines():
            line = line.strip()
            if not line or line.startswith("srun:"):
                continue
            parts = line.split(";", 3)
            if len(parts) < 4:
                continue
            node, job_gpus, cuda_devices, payload = parts
            gpu_parts = [part.strip() for part in payload.split(",")]
            if len(gpu_parts) < 8:
                continue
            index, uuid, model, util, used, total, temp, power = gpu_parts[:8]
            env_ids = set()
            for token in (job_gpus + "," + cuda_devices).split(","):
                token = token.strip()
                if token:
                    env_ids.add(token)
            row = {
                "node": node.strip() or "?",
                "gpu": index.strip() or "?",
                "model": model.strip() or "?",
                "util": JobDetailsWindow._format_percent(util),
                "mem": JobDetailsWindow._format_gpu_memory(used, total),
                "temp": JobDetailsWindow._format_temp(temp),
                "power": JobDetailsWindow._format_power(power),
            }
            all_rows.append(row)
            if not env_ids or index in env_ids or uuid in env_ids:
                rows.append(row)
        # Se il filtro SLURM_JOB_GPUS/CUDA_VISIBLE_DEVICES non è riconoscibile
        # (per esempio contiene UUID o nomi inattesi), mostra tutte le GPU del
        # nodo invece di lasciare la tabella vuota.
        return rows or all_rows

    @staticmethod
    def _parse_slurm_time(value):
        text = str(value or "").strip()
        if not text or text.lower() in ("n/a", "none", "unknown"):
            return None
        days = 0
        if "-" in text:
            day_text, text = text.split("-", 1)
            try:
                days = int(day_text)
            except ValueError:
                days = 0
        parts = text.split(":")
        try:
            if len(parts) == 3:
                hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
            elif len(parts) == 2:
                hours, minutes, seconds = 0, int(parts[0]), float(parts[1])
            else:
                hours, minutes, seconds = 0, 0, float(text)
        except ValueError:
            return None
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _parse_size_mb(value):
        text = str(value or "").strip()
        if not text or text.lower() in ("n/a", "none", "unknown"):
            return None
        match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?)", text, re.I)
        if not match:
            return None
        number = float(match.group(1))
        unit = match.group(2).upper()
        factors = {
            "": 1.0 / 1024.0, "K": 1.0 / 1024.0, "M": 1.0,
            "G": 1024.0, "T": 1024.0 * 1024.0,
            "P": 1024.0 * 1024.0 * 1024.0,
        }
        return number * factors.get(unit, 1.0 / 1024.0)

    @staticmethod
    def _format_duration(value):
        if value is None:
            return "-"
        seconds = max(0, int(round(float(value))))
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        if days:
            return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_mb(value):
        if value is None:
            return "-"
        value = float(value)
        if value >= 1024:
            return f"{value / 1024.0:.1f} GB"
        return f"{value:.0f} MB"

    @staticmethod
    def _format_percent(value):
        text = str(value or "").strip()
        if not text or text.lower() in ("n/a", "[n/a]", "none"):
            return "-"
        try:
            return f"{float(text):.0f}%"
        except ValueError:
            return text

    @staticmethod
    def _format_temp(value):
        text = str(value or "").strip()
        if not text or text.lower() in ("n/a", "[n/a]", "none"):
            return "-"
        try:
            return f"{float(text):.0f} °C"
        except ValueError:
            return text

    @staticmethod
    def _format_power(value):
        text = str(value or "").strip()
        if not text or text.lower() in ("n/a", "[n/a]", "none"):
            return "-"
        try:
            return f"{float(text):.1f} W"
        except ValueError:
            return text

    @staticmethod
    def _format_gpu_memory(used, total):
        try:
            used_value = float(str(used).strip())
            total_value = float(str(total).strip())
        except (TypeError, ValueError):
            return f"{used} / {total} MiB"
        if total_value > 0:
            percent = used_value / total_value * 100.0
            return (
                f"{used_value:.0f} / {total_value:.0f} MiB "
                f"({percent:.0f}%)"
            )
        return f"{used_value:.0f} MiB"

    # ----------------------------- aggiornamento UI -----------------------------
    def _apply(self, data):
        fields = data.get("job") or {}
        state = data.get("state") or fields.get("JobState") or "sconosciuto"
        state_word = str(state).split()[0] if state else "sconosciuto"
        self.state_var.set(state_word)
        state_colors = {
            "RUNNING": GREEN, "COMPLETING": GREEN, "STAGE_OUT": GREEN,
            "PENDING": ORANGE, "CONFIGURING": ORANGE, "SUSPENDED": ORANGE,
            "FAILED": RED, "CANCELLED": RED, "TIMEOUT": RED,
            "OUT_OF_MEMORY": RED, "NODE_FAIL": RED, "PREEMPTED": RED,
        }
        self.lbl_state.configure(fg=state_colors.get(state_word, MUTED))

        name = self._display(fields.get("JobName", ""))
        self.title_var.set(
            f"Job {self.job_id}" + (f" · {name}" if name != "—" else "")
        )

        values = {
            "jobid": self._display(fields.get("JobId", self.job_id)),
            "name": name,
            "owner": self._display(
                data.get("owner") or fields.get("UserId", "")
            ),
            "partition": self._display(fields.get("Partition", "")),
            "nodes": self._display(fields.get("NumNodes", "")),
            "cpus": self._display(fields.get("NumCPUs", "")),
            "tasks": self._display(fields.get("NumTasks", "")),
            "gpu": str(data.get("gpu_count") or 0),
            "runtime": self._display(fields.get("RunTime", "")),
            "timelimit": self._display(fields.get("TimeLimit", "")),
            "start": self._format_timestamp(fields.get("StartTime", "")),
            "end": self._format_timestamp(fields.get("EndTime", "")),
            "tres": self._display(fields.get("TRES", "")),
            "nodelist": self._display(fields.get("NodeList", "")),
            "workdir": self._display(fields.get("WorkDir", "")),
            "stdout": self._display(fields.get("StdOut", "")),
            "command": self._display(fields.get("Command", "")),
        }
        for key, var in self._info_vars.items():
            var.set(values.get(key, "—"))

        cpu = data.get("cpu") or {}
        self.cpu_var.set(cpu.get("text", "CPU: nessun dato disponibile."))
        self.gpu_note_var.set(
            data.get("gpu_note", "GPU: nessun dato disponibile.")
        )

        for tree in (self.tree_gpu, self.tree_steps):
            for item in tree.get_children():
                tree.delete(item)

        for row in data.get("gpu_rows", []):
            self.tree_gpu.insert("", tk.END, values=(
                row.get("node", "-"), row.get("gpu", "-"),
                row.get("model", "-"), row.get("util", "-"),
                row.get("mem", "-"), row.get("temp", "-"),
                row.get("power", "-"),
            ))

        for row in cpu.get("rows", []):
            self.tree_steps.insert("", tk.END, values=(
                row.get("step", "-"), row.get("ntasks", "-"),
                self._format_duration(row.get("cpu_total")),
                self._format_mb(row.get("max_rss")),
            ))

        if data.get("error"):
            self.status_var.set(
                f"{data['error']} · nuovo tentativo tra "
                f"{self.REFRESH_MS // 1000} s"
            )
        else:
            self.status_var.set(
                f"Aggiornamento automatico ogni {self.REFRESH_MS // 1000} s "
                f"· ultimo: {time.strftime('%H:%M:%S')}"
            )

    @staticmethod
    def _display(value):
        text = str(value or "").strip()
        if not text or text.lower() in (
            "(null)", "null", "none", "unknown", "n/a", "not available",
        ):
            return "—"
        return text

    @staticmethod
    def _format_timestamp(value):
        text = str(value or "").strip()
        if not text or text.lower() in (
            "(null)", "null", "none", "unknown", "n/a", "not available",
        ):
            return "—"
        try:
            return datetime.strptime(
                text, "%Y-%m-%dT%H:%M:%S"
            ).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            return text.replace("T", " ")[:19]


def main():
    root = tk.Tk()
    choose_fonts()
    HPCManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()







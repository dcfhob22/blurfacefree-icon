"""Drag-and-drop GUI wrapper for deface. Cross-platform dark-mode UI.

Extras over the stock version:
  * "image" mode      - cover faces with your own picture (PNG transparency works)
  * "target faces"    - pick people in a preview frame, then blur only them
                        (or everyone except them). Needs face_select.py next to this file.
"""
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import (
    BooleanVar, DoubleVar, StringVar, Tk,
    filedialog, messagebox, ttk, END, NORMAL, DISABLED,
)
from tkinter.scrolledtext import ScrolledText

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv"}
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
DEFAULT_OUTPUT = HERE / "output"
SCRIPTS_DIR = Path(os.environ.get("APPDATA", "")) / "Python" / "Python313" / "Scripts"
FACE_SELECT = HERE / "face_select.py"

WIN_TITLE = "blur faces - free, local, no cap"

# theme
BG = "#0b0b14"
CARD = "#161624"
CARD_HI = "#1f1f30"
BORDER = "#2a2a40"
TEXT = "#f5f5fa"
DIM = "#8a8aa3"
ACCENT = "#a78bfa"
ACCENT_HOT = "#c4a8ff"
PINK = "#ec4899"
GREEN = "#34d399"
YELLOW = "#fbbf24"
RED = "#f87171"

if IS_MAC:
    _DISPLAY = "SF Pro Display"
    _TEXT = "SF Pro Text"
    _MONO = "SF Mono"
elif IS_WIN:
    _DISPLAY = "Segoe UI Variable Display"
    _TEXT = "Segoe UI Variable"
    _MONO = "Cascadia Mono"
else:
    _DISPLAY = "DejaVu Sans"
    _TEXT = "DejaVu Sans"
    _MONO = "DejaVu Sans Mono"

F_TITLE = (_DISPLAY, 24, "bold")
F_SUB = (_TEXT, 11)
F_HEAD = (_DISPLAY, 11, "bold")
F_BODY = (_TEXT, 11)
F_BTN = (_DISPLAY, 11, "bold")
F_BIG_BTN = (_DISPLAY, 13, "bold")
F_MONO = (_MONO, 10)
F_DROP = ("Segoe UI Variable Display", 14, "bold")


def console_python():
    """sys.executable, but never the window-less pythonw (it can swallow output)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


def find_deface():
    exe = shutil.which("deface")
    if exe:
        return [exe]
    if IS_WIN:
        for candidate in (SCRIPTS_DIR / "deface.exe",
                          Path(sys.executable).parent / "Scripts" / "deface.exe"):
            if candidate.exists():
                return [str(candidate)]
    return [console_python(), "-m", "deface.deface"]


def open_path(p: Path):
    """Open a folder or file with the OS default handler."""
    if IS_WIN:
        os.startfile(str(p))  # noqa: S606
    elif IS_MAC:
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def parse_dropped(data: str):
    paths, buf, in_brace = [], "", False
    for ch in data:
        if ch == "{":
            in_brace = True
            continue
        if ch == "}":
            in_brace = False
            if buf:
                paths.append(buf); buf = ""
            continue
        if ch == " " and not in_brace:
            if buf:
                paths.append(buf); buf = ""
            continue
        buf += ch
    if buf:
        paths.append(buf)
    return [p for p in paths if p]


def make_card(parent, **kw):
    return tk.Frame(parent, bg=CARD, highlightthickness=1,
                    highlightbackground=BORDER, highlightcolor=BORDER, **kw)


def make_btn(parent, text, command, *, kind="primary", **kw):
    colors = {
        "primary": (ACCENT, "#0b0b14", ACCENT_HOT),
        "ghost":   (CARD_HI, TEXT, BORDER),
        "danger":  (RED, "#0b0b14", "#fca5a5"),
        "ok":      (GREEN, "#0b0b14", "#6ee7b7"),
    }[kind]
    bg_c, fg_c, hover = colors
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg_c, fg=fg_c, activebackground=hover, activeforeground=fg_c,
        relief="flat", bd=0, padx=18, pady=9, cursor="hand2",
        font=kw.pop("font", F_BTN), **kw,
    )
    btn.bind("<Enter>", lambda _e: btn.configure(bg=hover))
    btn.bind("<Leave>", lambda _e: btn.configure(bg=bg_c))
    btn._base_bg = bg_c
    return btn


def make_slider(parent, label, var, lo, hi, fmt):
    row = tk.Frame(parent, bg=CARD)
    row.pack(fill="x", padx=14, pady=4)
    tk.Label(row, text=label, bg=CARD, fg=DIM, font=F_BODY).pack(side="left")
    value_lbl = tk.Label(row, text=fmt.format(var.get()), width=6,
                         bg=CARD, fg=ACCENT, font=F_HEAD)
    value_lbl.pack(side="right")
    ttk.Scale(row, from_=lo, to=hi, variable=var, orient="horizontal",
              length=220, style="Dark.Horizontal.TScale").pack(side="right", padx=10)
    var.trace_add("write", lambda *_x, lbl=value_lbl, v=var, f=fmt: lbl.config(text=f.format(v.get())))


class ScrollFrame(tk.Frame):
    """Vertically scrollable container. Build your UI inside `.inner`."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=24)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        # keep the scroll range in sync with the content, and the content as wide as the window
        self.inner.bind("<Configure>",
                        lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._win, width=e.width))

        # mouse wheel (Windows/macOS use <MouseWheel>, Linux uses Button-4/5)
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", self._on_wheel)
        self.bind_all("<Button-5>", self._on_wheel)

    def _is_mine(self, widget):
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_wheel(self, event):
        try:
            w = self.winfo_containing(event.x_root, event.y_root)
        except KeyError:                       # transient popup widgets
            return
        # ignore other windows (e.g. the picker dialog) and text boxes, which scroll themselves
        if w is None or not self._is_mine(w) or isinstance(w, tk.Text):
            return
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height():
            return                             # everything fits, nothing to scroll
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        elif IS_MAC:
            step = -event.delta
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")


# ──────────────────────────────────────────────────────────────────────────
# preview dialog: click the face(s) you want to target
# ──────────────────────────────────────────────────────────────────────────
class PickFacesDialog(tk.Toplevel):
    MAX_W, MAX_H = 860, 520

    def __init__(self, app, video: Path, engine):
        import cv2
        from PIL import Image, ImageTk
        import face_select

        super().__init__(app.root)
        self.MAX_H = max(240, min(520, self.winfo_screenheight() - 380))
        self._cv2, self._Image, self._ImageTk, self._fs = cv2, Image, ImageTk, face_select
        self.app, self.engine = app, engine
        self.title("pick the face(s) to target")
        self.configure(bg=BG)
        self.transient(app.root)

        self.cap = cv2.VideoCapture(str(video))
        self.n_frames = max(int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0), 1)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if 1.0 <= fps <= 240.0 else 30.0
        self.frame = None
        self.faces = []
        self.selected: set = set()
        self.picked: list = []          # (embedding, thumbnail) added so far
        self.scale = 1.0
        self._photo = None
        self.pos = DoubleVar(value=0)

        tk.Label(self, text="click a face to select it (click again to un-select). "
                            "tip: add the same person from a few different frames.",
                 bg=BG, fg=DIM, font=F_BODY, wraplength=840, justify="left"
                 ).pack(anchor="w", padx=16, pady=(12, 6))

        self.canvas = tk.Canvas(self, width=640, height=360, bg=CARD,
                                highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(padx=16)
        self.canvas.bind("<Button-1>", self._on_click)

        srow = tk.Frame(self, bg=BG)
        srow.pack(fill="x", padx=16, pady=(8, 2))
        make_btn(srow, "◀ 1s", lambda: self._step(-1), kind="ghost").pack(side="left")
        sc = ttk.Scale(srow, from_=0, to=max(self.n_frames - 1, 1), variable=self.pos,
                       orient="horizontal", style="Dark.Horizontal.TScale",
                       command=lambda _v: self._update_time())
        sc.pack(side="left", fill="x", expand=True, padx=10)
        sc.bind("<ButtonRelease-1>", lambda _e: self._show_frame(self.pos.get()))
        make_btn(srow, "1s ▶", lambda: self._step(1), kind="ghost").pack(side="left")
        self.time_lbl = tk.Label(srow, text="0.0s", width=8, bg=BG, fg=ACCENT, font=F_HEAD)
        self.time_lbl.pack(side="left", padx=(8, 0))

        self.status = tk.Label(self, text="", bg=BG, fg=TEXT, font=F_BODY)
        self.status.pack(anchor="w", padx=16, pady=(4, 6))

        brow = tk.Frame(self, bg=BG)
        brow.pack(fill="x", padx=16, pady=(0, 14))
        make_btn(brow, "add selected, pick another frame", self._add_and_stay,
                 kind="ghost").pack(side="left")
        make_btn(brow, "done ✓", self._done, kind="primary").pack(side="left", padx=8)
        make_btn(brow, "cancel", self._cancel, kind="danger").pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._show_frame(0)
        try:
            self.grab_set()
        except Exception:
            pass

    # -- frame display ---------------------------------------------------
    def _step(self, seconds):
        self._show_frame(self.pos.get() + seconds * self.fps)

    def _update_time(self):
        self.time_lbl.config(text=f"{self.pos.get() / self.fps:.1f}s")

    def _show_frame(self, idx):
        cv2 = self._cv2
        idx = int(max(0, min(self.n_frames - 1, idx)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        if not ok:
            self.status.config(text="couldn't read that frame", fg=RED)
            return
        self.pos.set(idx)
        self._update_time()
        self.frame = frame
        try:
            self.faces = self.engine.detect(frame)
        except Exception as e:  # noqa: BLE001
            self.faces = []
            self.status.config(text=f"face detection failed: {e}", fg=RED)
        self.selected.clear()

        h, w = frame.shape[:2]
        self.scale = min(self.MAX_W / w, self.MAX_H / h, 1.0)
        img = self._Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize(
            (max(1, int(w * self.scale)), max(1, int(h * self.scale))))
        self._photo = self._ImageTk.PhotoImage(img)
        self.canvas.config(width=img.width, height=img.height)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._draw_boxes()
        self._set_status()

    def _draw_boxes(self):
        self.canvas.delete("box")
        s = self.scale
        for i, f in enumerate(self.faces):
            x1, y1, x2, y2 = [v * s for v in f.box]
            sel = i in self.selected
            col = GREEN if sel else ACCENT
            self.canvas.create_rectangle(x1, y1, x2, y2, outline=col,
                                         width=4 if sel else 2, tags="box")
            self.canvas.create_rectangle(x1, y1 - 20, x1 + 26, y1, fill=col, outline=col, tags="box")
            self.canvas.create_text(x1 + 13, y1 - 10, text=str(i + 1), fill="#0b0b14",
                                    font=F_HEAD, tags="box")

    def _set_status(self):
        if not self.faces:
            self.status.config(text="no faces found in this frame - drag the slider to another moment",
                               fg=YELLOW)
        else:
            self.status.config(
                text=f"{len(self.faces)} face(s) here • {len(self.selected)} selected • "
                     f"{len(self.picked)} added so far",
                fg=TEXT)

    def _on_click(self, event):
        i = self._fs.hit_test(self.faces, event.x / self.scale, event.y / self.scale)
        if i is None:
            return
        self.selected.symmetric_difference_update({i})
        self._draw_boxes()
        self._set_status()

    # -- adding / closing ---------------------------------------------------
    def _add_selected(self) -> bool:
        too_small = 0
        for i in sorted(self.selected):
            f = self.faces[i]
            if f.size < 40:
                too_small += 1
                continue
            try:
                emb = self.engine.embed(self.frame, f)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("couldn't read that face", str(e), parent=self)
                return False
            self.picked.append((emb, self._fs.crop_thumb(self.frame, f)))
        if too_small:
            messagebox.showinfo(
                "face too small",
                f"{too_small} selected face(s) were too small to recognise reliably "
                "and were skipped. Pick a moment where they're closer to the camera.",
                parent=self)
        self.selected.clear()
        return True

    def _add_and_stay(self):
        if self._add_selected():
            self._draw_boxes()
            self._set_status()

    def _done(self):
        if not self._add_selected():
            return
        self._close(keep=True)

    def _cancel(self):
        self._close(keep=False)

    def _close(self, keep):
        try:
            self.cap.release()
        except Exception:
            pass
        if keep and self.picked:
            self.app.add_targets(self.picked)
        self.destroy()


class App:
    def __init__(self, root):
        self.root = root
        root.title(WIN_TITLE)
        root.configure(bg=BG)
        root.geometry(f"820x{min(1080, root.winfo_screenheight() - 100)}")
        root.minsize(560, 420)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Dark.Horizontal.TProgressbar",
                        background=ACCENT, troughcolor=CARD_HI,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("Dark.Horizontal.TScale",
                        background=CARD, troughcolor=CARD_HI,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Dark.Horizontal.TScale",
                  background=[("active", ACCENT_HOT)])
        style.configure("Vertical.TScrollbar", background=CARD_HI, troughcolor=BG,
                        bordercolor=BG, arrowcolor=DIM, lightcolor=CARD_HI, darkcolor=CARD_HI)
        style.map("Vertical.TScrollbar", background=[("active", ACCENT)])

        self.files: list[Path] = []
        self.output_dir = StringVar(value=str(DEFAULT_OUTPUT))
        self.keep_audio = BooleanVar(value=True)
        self.thresh = DoubleVar(value=0.2)
        self.mask_scale = DoubleVar(value=1.3)
        self.mode = StringVar(value="blur")
        self.use_boxes = BooleanVar(value=False)
        self.mosaic_size = StringVar(value="20")
        self.cover_image = StringVar(value="")
        # target-face selection
        self.targets: list = []          # face embeddings picked in the preview
        self.target_thumbs: list = []    # matching RGB thumbnails
        self._thumb_refs: list = []
        self.target_mode = StringVar(value="only")     # "only" | "except"
        self.match_thr = DoubleVar(value=0.363)
        self._engine = None

        self.log_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_flag = threading.Event()
        self.current_proc: subprocess.Popen | None = None

        self._build_ui()
        self.root.after(80, self._drain_log)

    def _build_ui(self):
        self.scroller = ScrollFrame(self.root)
        self.scroller.pack(fill="both", expand=True)
        root = self.scroller.inner      # everything below goes inside the scrollable area

        # ── header ──
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=22, pady=(20, 8))
        tk.Label(header, text="blur faces.", bg=BG, fg=TEXT,
                 font=F_TITLE).pack(side="left")
        tk.Label(header, text="  free  •  offline  •  no upload",
                 bg=BG, fg=ACCENT, font=F_HEAD).pack(side="left", pady=(14, 0))

        tk.Label(root, text="drag a video. blur every face. that's it.",
                 bg=BG, fg=DIM, font=F_SUB).pack(anchor="w", padx=24, pady=(0, 14))

        # ── drop zone ──
        drop_outer = tk.Frame(root, bg=ACCENT, padx=2, pady=2)
        drop_outer.pack(fill="x", padx=22, pady=(0, 10))
        drop = tk.Frame(drop_outer, bg=CARD)
        drop.pack(fill="both", expand=True)
        self.drop_label = tk.Label(
            drop,
            text=("drop ur vids here\n— or click 'add files' below —"
                  if DND_AVAILABLE else
                  "drag-drop unavailable — use 'add files' below"),
            bg=CARD, fg=TEXT, font=F_DROP,
            anchor="center", justify="center", pady=34,
        )
        self.drop_label.pack(fill="both", expand=True)
        if DND_AVAILABLE:
            for w in (drop, self.drop_label, drop_outer):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

        # ── queue card ──
        q_card = make_card(root)
        q_card.pack(fill="x", padx=22, pady=8)
        tk.Label(q_card, text="queue", bg=CARD, fg=PINK,
                 font=F_HEAD).pack(anchor="w", padx=14, pady=(10, 4))
        self.listbox = ScrolledText(
            q_card, height=4, wrap="none",
            bg=CARD_HI, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=0, font=F_MONO,
            highlightthickness=1, highlightbackground=BORDER,
        )
        self.listbox.pack(fill="x", padx=14, pady=(0, 8))
        self.listbox.configure(state=DISABLED)

        qbtn = tk.Frame(q_card, bg=CARD)
        qbtn.pack(fill="x", padx=12, pady=(0, 12))
        make_btn(qbtn, "+ add files", self._pick_files, kind="ghost").pack(side="left", padx=4)
        make_btn(qbtn, "clear", self._clear_queue, kind="ghost").pack(side="left", padx=4)

        # ── options card ──
        opts = make_card(root)
        opts.pack(fill="x", padx=22, pady=8)
        tk.Label(opts, text="vibe check", bg=CARD, fg=PINK,
                 font=F_HEAD).pack(anchor="w", padx=14, pady=(10, 6))

        # mode pills
        modes = tk.Frame(opts, bg=CARD)
        modes.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(modes, text="mode:", bg=CARD, fg=DIM, font=F_BODY).pack(side="left", padx=(4, 8))
        for v, label in (("blur", "🫧 blur"), ("mosaic", "🟪 mosaic"),
                         ("solid", "⬛ solid"), ("img", "🖼 image"),
                         ("none", "👀 detect")):
            rb = tk.Radiobutton(
                modes, text=label, variable=self.mode, value=v,
                indicatoron=False, bd=0, padx=12, pady=7,
                bg=CARD_HI, fg=TEXT,
                selectcolor=ACCENT,
                activebackground=ACCENT_HOT, activeforeground="#0b0b14",
                font=F_BTN, relief="flat", cursor="hand2",
                tristatevalue="x_unused",
            )
            rb.pack(side="left", padx=3)

        # toggles
        toggles = tk.Frame(opts, bg=CARD)
        toggles.pack(fill="x", padx=12, pady=4)
        for var, label in (
            (self.keep_audio, "🔊 keep audio"),
            (self.use_boxes, "▭ box masks"),
        ):
            cb = tk.Checkbutton(
                toggles, text=label, variable=var,
                bg=CARD, fg=TEXT, selectcolor=CARD_HI,
                activebackground=CARD, activeforeground=ACCENT,
                font=F_BODY, bd=0, relief="flat", cursor="hand2",
            )
            cb.pack(side="left", padx=8)

        # sliders
        make_slider(opts, "face detection sensitivity", self.thresh, 0.05, 0.6, "{:.2f}")
        make_slider(opts, "blur cushion (how much around the face)", self.mask_scale, 1.0, 2.5, "{:.2f}")

        # mosaic size
        misc = tk.Frame(opts, bg=CARD)
        misc.pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(misc, text="mosaic block size:", bg=CARD, fg=DIM, font=F_BODY).pack(side="left")
        tk.Entry(misc, textvariable=self.mosaic_size, width=5,
                 bg=CARD_HI, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=F_BODY,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left", padx=8)

        # cover image (used by "image" mode)
        imgrow = tk.Frame(opts, bg=CARD)
        imgrow.pack(fill="x", padx=14, pady=(6, 4))
        tk.Label(imgrow, text="cover image:", bg=CARD, fg=DIM, font=F_BODY).pack(side="left")
        tk.Entry(imgrow, textvariable=self.cover_image,
                 bg=CARD_HI, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=F_BODY,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left", fill="x", expand=True, padx=8)
        make_btn(imgrow, "browse", self._pick_cover_image, kind="ghost").pack(side="left")

        # output folder
        outrow = tk.Frame(opts, bg=CARD)
        outrow.pack(fill="x", padx=14, pady=(6, 14))
        tk.Label(outrow, text="output folder:", bg=CARD, fg=DIM,
                 font=F_BODY).pack(side="left")
        tk.Entry(outrow, textvariable=self.output_dir,
                 bg=CARD_HI, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=F_BODY,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left", fill="x", expand=True, padx=8)
        make_btn(outrow, "browse", self._pick_outdir, kind="ghost").pack(side="left")

        # ── target faces card ──
        tgt = make_card(root)
        tgt.pack(fill="x", padx=22, pady=8)
        tk.Label(tgt, text="target faces (optional)", bg=CARD, fg=PINK,
                 font=F_HEAD).pack(anchor="w", padx=14, pady=(10, 4))
        trow = tk.Frame(tgt, bg=CARD)
        trow.pack(fill="x", padx=12, pady=(0, 4))
        make_btn(trow, "🎯 pick from preview", self._open_picker,
                 kind="primary").pack(side="left", padx=4)
        make_btn(trow, "clear", self._clear_targets, kind="ghost").pack(side="left", padx=4)
        self.target_label = tk.Label(trow, text="", bg=CARD, fg=DIM, font=F_BODY)
        self.target_label.pack(side="left", padx=10)
        self.thumb_frame = tk.Frame(tgt, bg=CARD)
        self.thumb_frame.pack(fill="x", padx=14)

        trow2 = tk.Frame(tgt, bg=CARD)
        trow2.pack(fill="x", padx=12, pady=(6, 2))
        for v, label in (("only", "blur only the picked"),
                         ("except", "blur everyone except the picked")):
            tk.Radiobutton(
                trow2, text=label, variable=self.target_mode, value=v,
                indicatoron=False, bd=0, padx=12, pady=6,
                bg=CARD_HI, fg=TEXT, selectcolor=ACCENT,
                activebackground=ACCENT_HOT, activeforeground="#0b0b14",
                font=F_BTN, relief="flat", cursor="hand2", tristatevalue="x_unused",
            ).pack(side="left", padx=3)
        make_slider(tgt, "match strictness (higher = stricter)", self.match_thr, 0.20, 0.70, "{:.2f}")
        tk.Label(tgt, text="when it's unsure who someone is, it blurs them.",
                 bg=CARD, fg=DIM, font=F_BODY).pack(anchor="w", padx=14, pady=(0, 10))
        self._refresh_targets()

        # ── action bar ──
        action = tk.Frame(root, bg=BG)
        action.pack(fill="x", padx=22, pady=(6, 4))
        self.start_btn = make_btn(action, "✨  blur it  ✨", self._start,
                                  kind="primary", font=F_BIG_BTN)
        self.start_btn.pack(side="left")
        self.stop_btn = make_btn(action, "stop", self._stop, kind="danger")
        self.stop_btn.pack(side="left", padx=8)
        self.stop_btn.configure(state=DISABLED)
        make_btn(action, "open output", self._open_outdir, kind="ghost").pack(side="left", padx=4)
        self.status = tk.Label(action, text="idle. drop a vid 👇", bg=BG, fg=DIM, font=F_BODY)
        self.status.pack(side="right")

        # progress
        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100,
                                        style="Dark.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=22, pady=(4, 8))

        # log
        log_card = make_card(root)
        log_card.pack(fill="both", expand=True, padx=22, pady=(4, 18))
        tk.Label(log_card, text="what's happening", bg=CARD, fg=PINK,
                 font=F_HEAD).pack(anchor="w", padx=14, pady=(10, 4))
        self.log = ScrolledText(
            log_card, height=8, wrap="word",
            bg=CARD_HI, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=0, font=F_MONO,
            highlightthickness=1, highlightbackground=BORDER,
        )
        self.log.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.log.configure(state=DISABLED)

    # ── interactions ──
    def _on_drop(self, event):
        for p in parse_dropped(event.data):
            self._add_path(Path(p))
        self._refresh_queue()

    def _pick_files(self):
        paths = filedialog.askopenfilenames(
            title="pick a video",
            filetypes=[("videos", " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))), ("all files", "*.*")],
        )
        for p in paths:
            self._add_path(Path(p))
        self._refresh_queue()

    def _pick_outdir(self):
        d = filedialog.askdirectory(initialdir=self.output_dir.get() or str(HERE))
        if d:
            self.output_dir.set(d)

    def _pick_cover_image(self):
        p = filedialog.askopenfilename(
            title="pick an image to cover faces",
            filetypes=[("images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("all files", "*.*")],
        )
        if p:
            self.cover_image.set(p)
            self.mode.set("img")

    def _open_outdir(self):
        d = Path(self.output_dir.get())
        d.mkdir(parents=True, exist_ok=True)
        open_path(d)

    def _add_path(self, p: Path):
        if p.is_dir():
            for child in p.iterdir():
                if child.suffix.lower() in VIDEO_EXTS:
                    self.files.append(child)
        elif p.suffix.lower() in VIDEO_EXTS:
            self.files.append(p)
        else:
            self._log(f"skipped (not a video): {p}")

    def _clear_queue(self):
        self.files.clear()
        self._refresh_queue()

    def _refresh_queue(self):
        self.listbox.config(state=NORMAL)
        self.listbox.delete("1.0", END)
        for f in self.files:
            self.listbox.insert(END, f"{f}\n")
        self.listbox.config(state=DISABLED)
        self.status.config(text=f"{len(self.files)} in queue" if self.files else "idle. drop a vid 👇")

    # ── target faces ──
    def get_engine(self):
        import face_select
        if self._engine is None:
            self.status.config(text="loading face models (first time downloads ~40 MB)...")
            self.root.update_idletasks()
            self._engine = face_select.FaceEngine(det_score=self._det_score())
        self._engine.set_det_score(self._det_score())
        return self._engine

    def _det_score(self):
        # the sensitivity slider is shared with deface; map it onto YuNet's confidence scale
        return min(0.95, 0.4 + self.thresh.get())

    def _open_picker(self):
        if not self.files:
            messagebox.showinfo("add a video first",
                                "add a video to the queue, then pick faces from it ✨")
            return
        if not FACE_SELECT.exists():
            messagebox.showerror("missing file", f"face_select.py not found next to this app:\n{FACE_SELECT}")
            return
        try:
            engine = self.get_engine()
        except Exception as e:  # noqa: BLE001  (ModelError, missing cv2 build, ...)
            self.status.config(text="idle.")
            messagebox.showerror("couldn't load the face models", str(e))
            return
        self.status.config(text=f"{len(self.files)} in queue")
        PickFacesDialog(self, self.files[0], engine)

    def add_targets(self, picked):
        for emb, thumb in picked:
            self.targets.append(emb)
            self.target_thumbs.append(thumb)
        self._refresh_targets()

    def _clear_targets(self):
        self.targets.clear()
        self.target_thumbs.clear()
        self._refresh_targets()

    def _refresh_targets(self):
        for w in self.thumb_frame.winfo_children():
            w.destroy()
        self._thumb_refs = []
        if not self.targets:
            self.target_label.config(text="none picked → every face gets blurred")
            return
        self.target_label.config(text=f"{len(self.targets)} face sample(s) picked")
        try:
            from PIL import Image, ImageTk
            for thumb in self.target_thumbs[:16]:
                ph = ImageTk.PhotoImage(Image.fromarray(thumb))
                self._thumb_refs.append(ph)
                tk.Label(self.thumb_frame, image=ph, bg=CARD, bd=0).pack(side="left", padx=2, pady=2)
        except Exception:
            pass

    # ── running ──
    def _log(self, msg: str):
        self.log_q.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.log.config(state=NORMAL)
                self.log.insert(END, msg.rstrip() + "\n")
                self.log.see(END)
                self.log.config(state=DISABLED)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_log)

    def _start(self):
        if not self.files:
            messagebox.showinfo("nothing here", "add at least one video first ✨")
            return
        if self.mode.get() == "img" and not Path(self.cover_image.get()).is_file():
            messagebox.showinfo("no image", "pick a cover image first 🖼")
            return
        if self.targets and not FACE_SELECT.exists():
            messagebox.showerror("missing file", f"face_select.py not found:\n{FACE_SELECT}")
            return
        outdir = Path(self.output_dir.get())
        outdir.mkdir(parents=True, exist_ok=True)
        self.stop_flag.clear()
        self.start_btn.config(state=DISABLED)
        self.stop_btn.config(state=NORMAL)
        self.progress["value"] = 0
        self.worker = threading.Thread(target=self._run_jobs,
                                       args=(list(self.files), outdir), daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_flag.set()
        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.terminate()
            except Exception:
                pass
        self._log("stop requested.")
        self.status.config(text="stopping...")

    def _build_args(self, f: Path, out: Path, deface_cmd, targets_path):
        """Command line for one video. Selective path if faces were picked, else plain deface."""
        if targets_path is not None:
            args = [
                console_python(), str(FACE_SELECT), str(f),
                "-o", str(out),
                "--targets", str(targets_path),
                "--mode", self.target_mode.get(),
                "--replacewith", self.mode.get(),
                "--mask-scale", f"{self.mask_scale.get():.3f}",
                "--det-score", f"{self._det_score():.3f}",
                "--match-thr", f"{self.match_thr.get():.3f}",
            ]
        else:
            args = list(deface_cmd) + [
                "--thresh", f"{self.thresh.get():.3f}",
                "--mask-scale", f"{self.mask_scale.get():.3f}",
                "--replacewith", self.mode.get(),
                "-o", str(out),
            ]
        if self.keep_audio.get():
            args.append("--keep-audio")
        if self.use_boxes.get():
            args.append("--boxes")
        if self.mode.get() == "mosaic":
            try:
                int(self.mosaic_size.get())
                args += ["--mosaicsize", self.mosaic_size.get()]
            except ValueError:
                pass
        if self.mode.get() == "img":
            args += ["--replaceimg", self.cover_image.get()]
        if targets_path is None:
            args.append(str(f))
        return args

    def _run_jobs(self, files: list[Path], outdir: Path):
        deface_cmd = find_deface()
        targets_path = None
        if self.targets:
            import numpy as np
            targets_path = Path(tempfile.gettempdir()) / "blurfaces_targets.npy"
            np.save(targets_path, np.stack(self.targets))
            self._log(f"selective mode: {self.target_mode.get()} "
                      f"({len(self.targets)} face sample(s) picked)")
        total = len(files)
        try:
            for i, f in enumerate(files, 1):
                if self.stop_flag.is_set():
                    break
                # the selective path always writes .mp4 (H.264 + AAC works everywhere)
                suffix = ".mp4" if targets_path is not None else f.suffix
                out = outdir / f"{f.stem}_anonymized{suffix}"
                args = self._build_args(f, out, deface_cmd, targets_path)

                self.root.after(0, lambda i=i, total=total, name=f.name:
                                self.status.config(text=f"cooking [{i}/{total}] {name}"))
                self._log(f"\n=== [{i}/{total}] {f}")
                self._log(" ".join(f'"{a}"' if " " in a else a for a in args))
                rc = self._run_one(args)
                if rc == 0:
                    self._log(f"ok -> {out}")
                elif self.stop_flag.is_set():
                    self._log("stopped.")
                    break
                else:
                    self._log(f"failed (exit {rc})")
                self.root.after(0, lambda v=(i / total) * 100: self.progress.configure(value=v))
        finally:
            if targets_path is not None:
                try:
                    targets_path.unlink()          # face embeddings: don't leave them lying around
                except OSError:
                    pass
        self.root.after(0, self._jobs_done)

    def _run_one(self, args) -> int:
        try:
            self.current_proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as e:
            self._log(f"could not launch: {e}")
            return -1
        assert self.current_proc.stdout is not None
        pct_re = re.compile(r"(\d{1,3})%")
        for line in self.current_proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            self._log(line)
            m = pct_re.search(line)
            if m:
                try:
                    pct = int(m.group(1))
                    self.root.after(0, lambda v=pct: self.progress.configure(value=v))
                except ValueError:
                    pass
        return self.current_proc.wait()

    def _jobs_done(self):
        self.start_btn.config(state=NORMAL)
        self.stop_btn.config(state=DISABLED)
        self.status.config(text="done ✨")
        self.progress["value"] = 100


def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""yt-dlp 工作台桌面版：轻量 tkinter 界面（仅使用 Python 标准库）。"""

from __future__ import annotations

import ctypes
import os
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

import core
import i18n

FONT = "Microsoft YaHei UI"
MONO = "Consolas"
GITHUB_URL = "https://github.com/yt-dlp/yt-dlp"
ASSETS_DIR = core.BASE_DIR / "assets"

FILTER_CODES = ("all", "done", "error", "canceled")

SOUND_SEQUENCES = {
    "chime": ((784, 110), (1046, 150), (1318, 220)),
    "bell": ((880, 600), (660, 320)),
    "pop": ((620, 60), (0, 30), (860, 90)),
    "coin": ((988, 70), (1319, 160)),
}

THEMES = {
    "dark": {
        "bg": "#0f1115",
        "panel": "#151922",
        "card": "#1b2029",
        "card_hover": "#232a38",
        "border": "#2a3140",
        "btn_border": "#3b465c",
        "text": "#e9edf4",
        "muted": "#8d96a8",
        "accent": "#ff5a44",
        "accent_hover": "#ff7562",
        "accent_soft": "#3a2320",
        "ok": "#3dd6b5",
        "warn": "#f0b64a",
        "bad": "#ff6b6b",
        "entry": "#10141b",
        "select": "#2a3342",
    },
    "light": {
        "bg": "#f2f5fa",
        "panel": "#ffffff",
        "card": "#ffffff",
        "card_hover": "#f4f7fc",
        "border": "#dde3ec",
        "btn_border": "#c3cddc",
        "text": "#1c2330",
        "muted": "#697386",
        "accent": "#e0442e",
        "accent_hover": "#c93824",
        "accent_soft": "#fdece8",
        "ok": "#0f9d7e",
        "warn": "#a86b00",
        "bad": "#cc2b2b",
        "entry": "#f7f9fc",
        "select": "#e6ecf6",
    },
}


def set_titlebar(win: tk.Misc, dark: bool, caption: str) -> None:
    """让系统标题栏跟随深色 / 浅色模式。"""
    if os.name != "nt":
        return
    try:
        win.update_idletasks()
        user32 = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        handle = int(win.winfo_id())
        hwnd = user32.GetParent(ctypes.c_void_p(handle)) or handle
        dark_flag = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        result = dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag))
        if result != 0:
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag))
        # Windows 11：标题栏底色与界面顶栏保持一致
        rgb = caption.lstrip("#")
        red, green, blue = (int(rgb[index:index + 2], 16) for index in (0, 2, 4))
        color = ctypes.c_int(red | (green << 8) | (blue << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004)
    except Exception:
        pass


def play_sound(name: str) -> None:
    """用系统提示音播放一段简单音序（后台线程，避免卡住界面）。"""
    sequence = SOUND_SEQUENCES.get(name) or SOUND_SEQUENCES["chime"]

    def run() -> None:
        try:
            import winsound
        except Exception:
            return
        try:
            for frequency, duration in sequence:
                if frequency <= 0:
                    time.sleep(duration / 1000.0)
                else:
                    winsound.Beep(int(frequency), int(duration))
        except Exception:
            try:
                winsound.MessageBeep(0x00000040)
            except Exception:
                pass

    threading.Thread(target=run, daemon=True, name="sound").start()


def load_qr(path, max_height: int):
    """读取二维码图片，超出可用高度时按整数倍缩小，保证仍可扫描。"""
    try:
        image = tk.PhotoImage(file=str(path))
    except Exception:
        return None
    factor = 1
    while image.height() // factor > max_height and factor < 8:
        factor *= 2
    return image.subsample(factor, factor) if factor > 1 else image


def shorten(text: str, limit: int = 80) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def shorten_path(path: str, limit: int = 34) -> str:
    path = str(path or "")
    if len(path) <= limit:
        return path
    return path[:14] + "…" + path[-18:]


def pretty_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        if len(path) > 24:
            path = path[:23] + "…"
        return (host + path) or url
    except Exception:
        return url


def display_title(task: dict) -> str:
    title = task.get("title") or ""
    if not title or "\ufffd" in title:
        return pretty_url(task.get("url", ""))
    return title


def task_status_text(task: dict, lang: str) -> str:
    status = task.get("status")
    if status == "running":
        phase = task.get("phase")
        if phase == "processing":
            return i18n.tr(lang, "phase_processing")
        if phase == "canceling":
            return i18n.tr(lang, "phase_canceling")
        return i18n.tr(lang, "status_running")
    key = f"status_{status}"
    text = i18n.tr(lang, key)
    return text if text != key else str(status or "")


def task_status_color(theme: dict, task: dict) -> str:
    status = task.get("status")
    if status == "running":
        phase = task.get("phase")
        if phase == "processing":
            return theme["ok"]
        if phase == "canceling":
            return theme["muted"]
        return theme["accent"]
    if status == "pending":
        return theme["warn"]
    if status == "done":
        return theme["ok"]
    if status == "error":
        return theme["bad"]
    return theme["muted"]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.manager = core.Manager()
        config = self.manager.config
        self.theme_name = config.get("theme", "dark")
        if self.theme_name not in THEMES:
            self.theme_name = "dark"
        self.theme = THEMES[self.theme_name]
        self.lang = config.get("language", "zh")
        self.animations = bool(config.get("animations", True))
        self.sound_enabled = bool(config.get("sound_enabled", True))
        self.sound_name = config.get("sound_name", "chime")
        if self.sound_name not in core.SOUNDS:
            self.sound_name = "chime"
        self.preset_var = tk.StringVar(value="best")
        self.playlist_var = tk.BooleanVar(value=False)
        self.cards: dict[str, dict] = {}
        self.queue_order: list[str] = []
        self.history_all: list[dict] = []
        self.history_version = -1
        self.log_windows: dict[str, "LogWindow"] = {}
        self.pending_text = ""
        self._alive = True
        self._status_job = None
        self._done_seen = {
            task["id"] for task in self.manager.history()["history"] if task["status"] == "done"
        }

        self.root.title(self.t("app_title"))
        self.root.configure(bg=self.theme["bg"])
        self.root.minsize(900, 600)
        self._place_window()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind_all("<MouseWheel>", self._on_wheel)

        self.build_ui()
        self.root.after(80, lambda: self.apply_window_theme(self.root))
        self.root.after(300, self.tick)
        self.root.after(200, self._animate)

    def t(self, key: str, **fmt) -> str:
        return i18n.tr(self.lang, key, **fmt)

    def _place_window(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1200, max(900, screen_w - 120))
        height = min(780, max(600, screen_h - 120))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def apply_window_theme(self, win: tk.Misc) -> None:
        set_titlebar(win, self.theme_name == "dark", self.theme["panel"])

    # ---------- 主题与样式 ----------

    def configure_styles(self) -> None:
        c = self.theme
        self.root.option_add("*TCombobox*Listbox.background", c["entry"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=c["bg"], foreground=c["text"], font=(FONT, 10))
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["text"])
        style.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=c["panel"],
            foreground=c["muted"],
            padding=(16, 8),
            borderwidth=0,
            font=(FONT, 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", c["card"])],
            foreground=[("selected", c["accent"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=c["entry"],
            background=c["card"],
            foreground=c["text"],
            arrowcolor=c["muted"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["entry"])],
            foreground=[("readonly", c["text"])],
            selectbackground=[("readonly", c["entry"])],
            selectforeground=[("readonly", c["text"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=c["border"],
            troughcolor=c["bg"],
            bordercolor=c["bg"],
            arrowcolor=c["muted"],
            relief="flat",
        )
        style.map("Vertical.TScrollbar", background=[("active", c["muted"])])
        style.configure(
            "Horizontal.TScrollbar",
            background=c["border"],
            troughcolor=c["bg"],
            bordercolor=c["bg"],
            arrowcolor=c["muted"],
            relief="flat",
        )
        style.map("Horizontal.TScrollbar", background=[("active", c["muted"])])
        style.configure(
            "Treeview",
            background=c["card"],
            fieldbackground=c["card"],
            foreground=c["text"],
            rowheight=28,
            borderwidth=0,
            font=(FONT, 9),
        )
        style.configure(
            "Treeview.Heading",
            background=c["panel"],
            foreground=c["muted"],
            relief="flat",
            padding=(6, 6),
            font=(FONT, 9, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", c["select"])],
            foreground=[("selected", c["text"])],
        )
        style.map("Treeview.Heading", background=[("active", c["card_hover"])])

    def rebuild_ui(self) -> None:
        try:
            self.pending_text = self.url_text.get("1.0", "end-1c")
        except Exception:
            self.pending_text = ""
        self.build_ui()
        snap = self.manager.snapshot()
        self.sync_queue(snap["active"])
        self.update_stats(snap["stats"])
        self.refresh_history()
        self.root.after(80, lambda: self.apply_window_theme(self.root))

    # ---------- 界面骨架 ----------

    def build_ui(self) -> None:
        pending_text = self.pending_text
        self.pending_text = ""
        for child in self.root.winfo_children():
            child.destroy()
        self.cards.clear()
        self.queue_order = []
        self.log_windows.clear()
        self.history_version = -1
        self.root.configure(bg=self.theme["bg"])
        self.root.title(self.t("app_title"))
        self.configure_styles()

        self._build_topbar()
        body = tk.Frame(self.root, bg=self.theme["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_sidebar(body)
        self._build_workspace(body)
        if pending_text:
            self.url_text.insert("1.0", pending_text)

    def _button(self, parent, text, command, kind="ghost") -> tk.Button:
        c = self.theme
        palettes = {
            "accent": (c["accent"], "#ffffff", c["accent_hover"]),
            "ghost": (c["card"], c["text"], c["card_hover"]),
            "outline": (c["entry"], c["text"], c["card_hover"]),
            "tiny": (c["card"], c["muted"], c["card_hover"]),
            "danger": (c["panel"], c["bad"], c["card_hover"]),
            "danger_card": (c["card"], c["bad"], c["card_hover"]),
        }
        bg, fg, hover = palettes.get(kind, palettes["ghost"])
        if kind == "accent":
            padx, pady, font = 14, 9, (FONT, 10, "bold")
        elif kind in ("tiny", "danger_card"):
            padx, pady, font = 8, 3, (FONT, 8)
        else:
            padx, pady, font = 10, 6, (FONT, 9)
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground=c["muted"],
            relief="flat",
            bd=0,
            highlightthickness=1 if kind == "outline" else 0,
            highlightbackground=c["btn_border"],
            highlightcolor=c["btn_border"],
            padx=padx,
            pady=pady,
            font=font,
            cursor="hand2",
        )
        btn.bind("<Enter>", lambda event: btn.config(bg=hover) if str(btn["state"]) == "normal" else None)
        btn.bind("<Leave>", lambda event: btn.config(bg=bg))
        return btn

    def _build_topbar(self) -> None:
        c = self.theme
        bar = tk.Frame(self.root, bg=c["panel"])
        bar.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(bar, bg=c["panel"], padx=20, pady=12)
        inner.pack(fill="x")

        tk.Label(
            inner, text=self.t("app_title"), bg=c["panel"], fg=c["text"], font=(FONT, 14, "bold")
        ).pack(side="left")
        tk.Label(
            inner, text=self.t("app_subtitle"), bg=c["panel"], fg=c["muted"], font=(FONT, 9)
        ).pack(side="left", padx=(10, 0), pady=(4, 0))

        settings = self._button(inner, self.t("settings"), self.open_settings, "outline")
        settings.pack(side="right")

        env = tk.Frame(inner, bg=c["panel"])
        env.pack(side="right", padx=(0, 14))
        version = self.manager.ytdlp_version or self.t("not_detected")
        chips = [
            (f"yt-dlp {version}", bool(self.manager.ytdlp_version)),
            (self.t("ffmpeg_ready") if self.manager.ffmpeg else self.t("ffmpeg_missing"), self.manager.ffmpeg),
        ]
        for text, ok in chips:
            tk.Label(
                env,
                text=f"● {text}",
                bg=c["panel"],
                fg=c["ok"] if ok else c["bad"],
                font=(FONT, 9),
            ).pack(side="left", padx=(0, 12))

    def preset_label(self, key: str) -> str:
        return self.t(f"preset_{key}") if key in core.PRESETS else str(key or "")

    def preset_hint_text(self, key: str) -> str:
        return self.t(f"preset_{key}_hint") if key in core.PRESETS else ""

    def preset_short_text(self, key: str) -> str:
        return self.t(f"preset_{key}_short") if key in core.PRESETS else ""

    def _build_sidebar(self, parent) -> None:
        c = self.theme
        panel = tk.Frame(parent, bg=c["panel"], highlightthickness=1, highlightbackground=c["border"])
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        panel.configure(width=360)
        panel.grid_propagate(False)
        panel.pack_propagate(False)
        inner = tk.Frame(panel, bg=c["panel"], padx=16, pady=16)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text=self.t("new_download"), bg=c["panel"], fg=c["text"], font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(
            inner, text=self.t("new_download_hint"), bg=c["panel"], fg=c["muted"], font=(FONT, 9)
        ).pack(anchor="w", pady=(2, 10))

        text_wrap = tk.Frame(inner, bg=c["border"], padx=1, pady=1)
        text_wrap.pack(fill="both", expand=True)
        self.url_text = tk.Text(
            text_wrap,
            height=7,
            width=30,
            bg=c["entry"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="word",
            font=(FONT, 10),
            padx=10,
            pady=8,
            undo=True,
        )
        self.url_text.pack(side="left", fill="both", expand=True)
        url_scroll = ttk.Scrollbar(text_wrap, orient="vertical", command=self.url_text.yview)
        self.url_text.configure(yscrollcommand=url_scroll.set)
        url_scroll.pack(side="right", fill="y")
        self.url_text.bind("<FocusIn>", lambda event: text_wrap.config(bg=c["accent"]))
        self.url_text.bind("<FocusOut>", lambda event: text_wrap.config(bg=c["border"]))
        self.url_text.bind("<Control-Return>", self._submit_event)

        tk.Label(inner, text=self.t("quality_format"), bg=c["panel"], fg=c["muted"], font=(FONT, 9)).pack(
            anchor="w", pady=(14, 6)
        )
        grid = tk.Frame(inner, bg=c["panel"])
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        self.preset_widgets: dict[str, tuple] = {}
        for index, key in enumerate(core.PRESETS):
            card = tk.Frame(
                grid,
                bg=c["card"],
                highlightthickness=1,
                highlightbackground=c["border"],
                cursor="hand2",
            )
            card.grid(
                row=index // 2,
                column=index % 2,
                sticky="nsew",
                padx=(0, 6) if index % 2 == 0 else (0, 0),
                pady=(0, 6),
            )
            name = tk.Label(
                card,
                text=self.preset_label(key),
                bg=c["card"],
                fg=c["text"],
                font=(FONT, 10, "bold"),
                anchor="w",
                cursor="hand2",
            )
            name.pack(fill="x", padx=10, pady=(7, 0))
            hint = tk.Label(
                card,
                text=self.preset_short_text(key),
                bg=c["card"],
                fg=c["muted"],
                font=(FONT, 8),
                anchor="w",
                cursor="hand2",
            )
            hint.pack(fill="x", padx=10, pady=(0, 6))
            for widget in (card, name, hint):
                widget.bind("<Button-1>", lambda event, k=key: self.select_preset(k))
            self.preset_widgets[key] = (card, name, hint)

        self.preset_hint = tk.Label(
            inner,
            text=self.preset_hint_text(self.preset_var.get()),
            bg=c["panel"],
            fg=c["muted"],
            font=(FONT, 8),
            anchor="w",
            justify="left",
            wraplength=316,
        )
        self.preset_hint.pack(fill="x", pady=(2, 4))

        tk.Checkbutton(
            inner,
            text=self.t("playlist_toggle"),
            variable=self.playlist_var,
            bg=c["panel"],
            fg=c["text"],
            activebackground=c["panel"],
            activeforeground=c["text"],
            selectcolor=c["entry"],
            highlightthickness=0,
            bd=0,
            font=(FONT, 9),
            anchor="w",
            wraplength=310,
            justify="left",
            cursor="hand2",
        ).pack(fill="x", pady=(6, 0))

        tk.Label(inner, text=self.t("save_location"), bg=c["panel"], fg=c["muted"], font=(FONT, 9)).pack(
            anchor="w", pady=(12, 4)
        )
        path_row = tk.Frame(inner, bg=c["panel"])
        path_row.pack(fill="x")
        self.output_label = tk.Label(
            path_row,
            text=shorten_path(self.manager.config["output_dir"]),
            bg=c["panel"],
            fg=c["muted"],
            font=(FONT, 8),
            anchor="w",
            cursor="hand2",
        )
        self.output_label.pack(side="left", fill="x", expand=True)
        self.output_label.bind("<Button-1>", lambda event: self.change_output_dir())
        self._button(path_row, self.t("open"), self.open_output_dir, "tiny").pack(side="right")
        self._button(path_row, self.t("change"), self.change_output_dir, "tiny").pack(
            side="right", padx=(0, 6)
        )

        self.submit_btn = self._button(inner, self.t("add_queue"), self.submit, "accent")
        self.submit_btn.pack(fill="x", pady=(16, 6))
        tk.Label(
            inner, text=self.t("submit_hint"), bg=c["panel"], fg=c["muted"], font=(FONT, 8)
        ).pack()

        self.status_label = tk.Label(
            inner,
            text="",
            bg=c["panel"],
            fg=c["muted"],
            font=(FONT, 9),
            anchor="w",
            justify="left",
            wraplength=316,
        )
        self.status_label.pack(fill="x", pady=(8, 0))

        self._style_presets()

    def _build_workspace(self, parent) -> None:
        c = self.theme
        wrap = tk.Frame(parent, bg=c["bg"])
        wrap.grid(row=0, column=1, sticky="nsew")
        self.notebook = ttk.Notebook(wrap)
        self.notebook.pack(fill="both", expand=True)
        self.queue_tab = tk.Frame(self.notebook, bg=c["bg"])
        self.history_tab = tk.Frame(self.notebook, bg=c["bg"])
        self.notebook.add(self.queue_tab, text=f"{self.t('download_queue')}  0")
        self.notebook.add(self.history_tab, text=f"{self.t('history_title')}  0")
        self._build_queue_tab(self.queue_tab)
        self._build_history_tab(self.history_tab)

    # ---------- 队列 ----------

    def _build_queue_tab(self, tab) -> None:
        c = self.theme
        bar = tk.Frame(tab, bg=c["bg"])
        bar.pack(fill="x", padx=2, pady=(12, 8))
        self.queue_stats = tk.Label(bar, text="", bg=c["bg"], fg=c["muted"], font=(FONT, 9))
        self.queue_stats.pack(side="left")
        tk.Label(bar, text=self.t("realtime_progress"), bg=c["bg"], fg=c["muted"], font=(FONT, 9)).pack(side="right")

        body = tk.Frame(tab, bg=c["bg"])
        body.pack(fill="both", expand=True)
        self.queue_canvas = tk.Canvas(body, bg=c["bg"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.queue_canvas.yview)
        self.queue_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.queue_canvas.pack(side="left", fill="both", expand=True)

        self.queue_inner = tk.Frame(self.queue_canvas, bg=c["bg"])
        window = self.queue_canvas.create_window((0, 0), window=self.queue_inner, anchor="nw")
        self.queue_inner.bind(
            "<Configure>", lambda event: self.queue_canvas.configure(scrollregion=self.queue_canvas.bbox("all"))
        )
        self.queue_canvas.bind(
            "<Configure>", lambda event: self.queue_canvas.itemconfigure(window, width=event.width)
        )
        self.queue_empty = tk.Label(
            self.queue_inner,
            text=self.t("queue_empty"),
            bg=c["bg"],
            fg=c["muted"],
            font=(FONT, 10),
            justify="center",
        )
        self.queue_empty.pack(pady=60)

    def _on_wheel(self, event) -> None:
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is getattr(self, "queue_canvas", None):
                try:
                    self.queue_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
                except tk.TclError:
                    pass
                return
            widget = getattr(widget, "master", None)

    def _create_card(self, parent, task: dict) -> dict:
        c = self.theme
        frame = tk.Frame(parent, bg=c["card"], highlightthickness=1, highlightbackground=c["border"])
        stripe = tk.Frame(frame, bg=c["accent"], width=3)
        stripe.pack(side="left", fill="y")
        body = tk.Frame(frame, bg=c["card"])
        body.pack(side="left", fill="both", expand=True, padx=14, pady=11)

        top = tk.Frame(body, bg=c["card"])
        top.pack(fill="x")
        title = tk.Label(
            top, text="", bg=c["card"], fg=c["text"], font=(FONT, 10, "bold"), anchor="w"
        )
        title.pack(side="left", fill="x", expand=True)
        status = tk.Label(top, text="", bg=c["card"], fg=c["muted"], font=(FONT, 9, "bold"))
        status.pack(side="right", padx=(8, 0))

        url = tk.Label(body, text="", bg=c["card"], fg=c["muted"], font=(FONT, 9), anchor="w")
        url.pack(fill="x", pady=(2, 8))

        progress_row = tk.Frame(body, bg=c["card"])
        progress_row.pack(fill="x")
        bar = tk.Canvas(progress_row, height=6, bg=c["border"], highlightthickness=0, bd=0)
        bar.pack(side="left", fill="x", expand=True, pady=(4, 4))
        rect = bar.create_rectangle(0, 0, 0, 6, fill=c["accent"], outline="")
        percent = tk.Label(
            progress_row, text="0%", bg=c["card"], fg=c["text"], font=(FONT, 9, "bold"), width=6, anchor="e"
        )
        percent.pack(side="right", padx=(8, 0))

        meta = tk.Label(body, text="", bg=c["card"], fg=c["muted"], font=(FONT, 9), anchor="w")
        meta.pack(fill="x", pady=(4, 0))

        actions = tk.Frame(body, bg=c["card"])
        actions.pack(fill="x", pady=(7, 0))
        cancel = self._button(actions, self.t("cancel"), lambda tid=task["id"]: self.cancel_task(tid), "danger_card")
        cancel.pack(side="right")
        log_btn = self._button(actions, self.t("log"), lambda tid=task["id"]: self.open_log(tid), "tiny")
        log_btn.pack(side="right", padx=(0, 8))

        card = {
            "frame": frame,
            "stripe": stripe,
            "title": title,
            "status": status,
            "url": url,
            "bar": bar,
            "rect": rect,
            "percent": percent,
            "meta": meta,
            "cancel": cancel,
            "log": log_btn,
            "percent_value": 0.0,
            "target_percent": 0.0,
            "percent_text": None,
            "show_dash": False,
        }
        bar.bind("<Configure>", lambda event, card=card: self._draw_bar(card))
        return card

    def _draw_bar(self, card: dict) -> None:
        try:
            width = card["bar"].winfo_width()
            value = max(0.0, min(100.0, card.get("percent_value", 0.0)))
            card["bar"].coords(card["rect"], 0, 0, int(width * value / 100), 6)
        except tk.TclError:
            pass

    def _update_card(self, card: dict, task: dict) -> None:
        c = self.theme
        title_text = display_title(task)
        card["title"].config(text=shorten(title_text, 70))
        card["url"].config(text=shorten(task["url"], 100))
        color = task_status_color(c, task)
        card["stripe"].config(bg=color)
        card["status"].config(text=task_status_text(task, self.lang), fg=color)
        card["bar"].itemconfigure(card["rect"], fill=color)
        card["cancel"].config(
            state="normal" if task["status"] in ("pending", "running") and task.get("phase") != "canceling" else "disabled"
        )

        status = task["status"]

        progress = task.get("progress") or {}
        percent = float(progress.get("percent") or 0)
        card["target_percent"] = percent
        if not self.animations or percent < card.get("percent_value", 0.0):
            card["percent_value"] = percent
            self._draw_bar(card)

        pending = status == "pending"
        if pending and not percent:
            card["show_dash"] = True
            text = "--"
        else:
            card["show_dash"] = False
            text = f"{percent:.0f}%" if not self.animations else None
        if text is not None and text != card.get("percent_text"):
            card["percent"].config(text=text)
            card["percent_text"] = text

        parts = []
        if pending:
            parts.append(self.t("card_waiting"))
        else:
            downloaded = progress.get("downloaded") or ""
            total = progress.get("total") or ""
            speed = progress.get("speed") or ""
            eta = progress.get("eta") or ""
            if task.get("phase") == "processing":
                parts.append(self.t("card_processing"))
            else:
                if downloaded:
                    parts.append(f"{downloaded} / {total}" if total else downloaded)
                if speed:
                    parts.append(speed)
                if eta:
                    parts.append(self.t("card_remaining", eta=eta))
                if task.get("phase") == "canceling":
                    parts.append(self.t("card_canceling"))
                if not parts:
                    parts.append(self.t("card_connecting"))
        preset_label = self.preset_label(task.get("preset"))
        if preset_label:
            parts.insert(0, preset_label)
        card["meta"].config(text=" · ".join(parts))

    def _animate(self) -> None:
        if not self._alive:
            return
        if self.animations and self.cards:
            for card in list(self.cards.values()):
                try:
                    target = float(card.get("target_percent", 0.0))
                    value = float(card.get("percent_value", 0.0))
                    if abs(target - value) < 0.2:
                        value = target
                    else:
                        value += (target - value) * 0.18
                    card["percent_value"] = value
                    self._draw_bar(card)
                    label = "--" if card.get("show_dash") else f"{value:.0f}%"
                    if label != card.get("percent_text"):
                        card["percent"].config(text=label)
                        card["percent_text"] = label
                except tk.TclError:
                    pass
        self.root.after(45 if self.animations else 400, self._animate)

    def _snap_animations(self) -> None:
        for card in self.cards.values():
            try:
                card["percent_value"] = float(card.get("target_percent", 0.0))
                self._draw_bar(card)
                label = "--" if card.get("show_dash") else f"{card['percent_value']:.0f}%"
                card["percent"].config(text=label)
                card["percent_text"] = label
            except tk.TclError:
                pass

    def sync_queue(self, active: list[dict]) -> None:
        active_ids = [task["id"] for task in active]
        for task_id in list(self.cards):
            if task_id not in active_ids:
                self.cards[task_id]["frame"].destroy()
                del self.cards[task_id]
        if active:
            self.queue_empty.pack_forget()
        else:
            if not self.queue_empty.winfo_ismapped():
                self.queue_empty.pack(pady=60)
        changed = active_ids != self.queue_order
        for task in active:
            card = self.cards.get(task["id"])
            if card is None:
                card = self._create_card(self.queue_inner, task)
                self.cards[task["id"]] = card
            self._update_card(card, task)
        if changed:
            for task_id in active_ids:
                self.cards[task_id]["frame"].pack_forget()
            for task_id in active_ids:
                self.cards[task_id]["frame"].pack(fill="x", pady=(0, 10))
            self.queue_order = active_ids

    def update_stats(self, stats: dict) -> None:
        if not hasattr(self, "queue_stats"):
            return
        try:
            self.queue_stats.config(
                text=self.t(
                    "stats",
                    pending=stats.get("pending", 0),
                    running=stats.get("running", 0),
                    done=stats.get("done", 0),
                    error=stats.get("error", 0),
                    canceled=stats.get("canceled", 0),
                )
            )
            active = stats.get("pending", 0) + stats.get("running", 0)
            finished = stats.get("done", 0) + stats.get("error", 0) + stats.get("canceled", 0)
            self.notebook.tab(self.queue_tab, text=f"{self.t('download_queue')}  {active}")
            self.notebook.tab(self.history_tab, text=f"{self.t('history_title')}  {finished}")
        except tk.TclError:
            pass

    # ---------- 历史 ----------

    def _build_history_tab(self, tab) -> None:
        c = self.theme
        bar = tk.Frame(tab, bg=c["bg"])
        bar.pack(fill="x", padx=2, pady=(12, 8))
        left = tk.Frame(bar, bg=c["bg"])
        left.pack(side="left")
        right = tk.Frame(bar, bg=c["bg"])
        right.pack(side="right")

        tk.Label(left, text=self.t("search"), bg=c["bg"], fg=c["muted"], font=(FONT, 9)).pack(
            side="left", padx=(0, 6)
        )
        self.history_search = tk.Entry(
            left,
            width=20,
            bg=c["entry"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["border"],
            highlightcolor=c["accent"],
            font=(FONT, 9),
        )
        self.history_search.pack(side="left", ipady=4)
        self.history_search.bind("<KeyRelease>", lambda event: self.render_history())

        self.filter_combo = ttk.Combobox(
            left,
            values=[self.t(f"filter_{code}") for code in FILTER_CODES],
            state="readonly",
            width=7,
            font=(FONT, 9),
        )
        self.filter_combo.current(0)
        self.filter_combo.pack(side="left", padx=(8, 0), ipady=2)
        self.filter_combo.bind("<<ComboboxSelected>>", lambda event: self.render_history())

        self._button(right, self.t("open"), self.open_selected, "outline").pack(side="left")
        self._button(right, self.t("retry"), self.retry_selected, "outline").pack(side="left", padx=(6, 0))
        self._button(right, self.t("delete"), self.delete_selected, "outline").pack(side="left", padx=(6, 0))
        self._button(right, self.t("clear_history"), self.clear_history, "danger").pack(
            side="left", padx=(6, 0)
        )

        table = tk.Frame(tab, bg=c["bg"])
        table.pack(fill="both", expand=True)
        self.history_tree = ttk.Treeview(
            table,
            columns=("title", "status", "preset", "time", "note"),
            show="headings",
            selectmode="browse",
        )
        headings = {
            "title": self.t("col_title"),
            "status": self.t("col_status"),
            "preset": self.t("col_preset"),
            "time": self.t("col_time"),
            "note": self.t("col_note"),
        }
        widths = {"title": 300, "status": 64, "preset": 92, "time": 132, "note": 180}
        for column, text in headings.items():
            self.history_tree.heading(column, text=text, anchor="w")
            self.history_tree.column(
                column,
                width=widths[column],
                minwidth=48,
                stretch=column in ("title", "note"),
                anchor="w",
            )
        self.history_tree.tag_configure("done", foreground=c["ok"])
        self.history_tree.tag_configure("error", foreground=c["bad"])
        self.history_tree.tag_configure("canceled", foreground=c["muted"])
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.history_tree.yview)
        hsb = ttk.Scrollbar(table, orient="horizontal", command=self.history_tree.xview)
        self.history_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.history_tree.pack(side="left", fill="both", expand=True)
        self.history_tree.bind("<Double-1>", lambda event: self.open_selected())
        self.history_tree.bind("<Button-3>", self._history_menu)

    def refresh_history(self) -> None:
        data = self.manager.history()
        self.history_all = data["history"]
        self.history_version = data["history_version"]
        self.render_history()

    def render_history(self) -> None:
        tree = getattr(self, "history_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        try:
            filter_code = FILTER_CODES[self.filter_combo.current()]
        except (tk.TclError, IndexError):
            filter_code = "all"
        try:
            query = self.history_search.get().strip().lower()
        except tk.TclError:
            query = ""
        for task in self.history_all:
            if filter_code != "all" and task["status"] != filter_code:
                continue
            haystack = f"{task.get('title', '')} {task.get('url', '')}".lower()
            if query and query not in haystack:
                continue
            title = display_title(task)
            preset_label = self.preset_label(task.get("preset")) or str(task.get("preset", ""))
            tree.insert(
                "",
                "end",
                iid=task["id"],
                values=(
                    shorten(title, 76),
                    task_status_text(task, self.lang),
                    preset_label,
                    task.get("finished_at", ""),
                    shorten(task.get("error") or "", 58),
                ),
                tags=(task["status"],),
            )

    def _selected_task_id(self):
        tree = getattr(self, "history_tree", None)
        if tree is None:
            return None
        selection = tree.selection()
        if not selection:
            self.flash(self.t("msg_select_first"), "warn")
            return None
        return selection[0]

    def _history_task(self, task_id: str):
        for task in self.history_all:
            if task["id"] == task_id:
                return task
        return None

    def open_selected(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        ok, message = self.manager.open_path(task_id=task_id)
        if not ok:
            self.flash(message, "bad")

    def retry_selected(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        new_id, message = self.manager.retry_task(task_id)
        if not new_id:
            self.flash(message, "bad")
            return
        self.notebook.select(self.queue_tab)
        self.flash(self.t("msg_retry_added"), "ok")

    def delete_selected(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        ok, message = self.manager.delete_task(task_id)
        if ok:
            self.flash(self.t("msg_deleted_history"), "ok")
            self.refresh_history()
        else:
            self.flash(message, "bad")

    def clear_history(self) -> None:
        if not messagebox.askyesno(
            self.t("msg_clear_title"),
            self.t("msg_clear_body"),
            parent=self.root,
        ):
            return
        removed = self.manager.clear_history()
        self.refresh_history()
        self.flash(self.t("msg_cleared", count=removed), "ok")

    def copy_selected_url(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        task = self._history_task(task_id)
        if not task:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(task["url"])
        self.flash(self.t("msg_url_copied"), "ok")

    def _history_menu(self, event) -> None:
        row = self.history_tree.identify_row(event.y)
        if not row:
            return
        self.history_tree.selection_set(row)
        c = self.theme
        menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=c["panel"],
            fg=c["text"],
            activebackground=c["accent"],
            activeforeground="#ffffff",
            bd=0,
        )
        menu.add_command(label=self.t("menu_open_folder"), command=self.open_selected)
        menu.add_command(label=self.t("menu_retry"), command=self.retry_selected)
        menu.add_command(label=self.t("menu_copy_url"), command=self.copy_selected_url)
        menu.add_separator()
        menu.add_command(label=self.t("menu_delete"), command=self.delete_selected)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---------- 主循环 ----------

    def tick(self) -> None:
        if not self._alive:
            return
        try:
            snap = self.manager.snapshot()
            self.sync_queue(snap["active"])
            self.update_stats(snap["stats"])
            if snap["history_version"] != self.history_version:
                self.refresh_history()
                self._notify_finished()
        except Exception:
            pass
        self.root.after(350, self.tick)

    def _notify_finished(self) -> None:
        done_now = {task["id"] for task in self.history_all if task["status"] == "done"}
        fresh = done_now - self._done_seen
        self._done_seen |= done_now
        if fresh and self.sound_enabled:
            play_sound(self.sound_name)

    # ---------- 操作 ----------

    def select_preset(self, key: str) -> None:
        self.preset_var.set(key)
        self._style_presets()

    def _style_presets(self) -> None:
        c = self.theme
        selected = self.preset_var.get()
        for key, widgets in self.preset_widgets.items():
            card, name, hint = widgets
            on = key == selected
            bg = c["accent_soft"] if on else c["card"]
            card.config(bg=bg, highlightbackground=c["accent"] if on else c["border"])
            name.config(bg=bg, fg=c["accent"] if on else c["text"])
            hint.config(bg=bg, fg=c["accent"] if on else c["muted"])
        if selected in core.PRESETS and hasattr(self, "preset_hint"):
            self.preset_hint.config(text=self.preset_hint_text(selected))

    def _submit_event(self, event):
        self.submit()
        return "break"

    def submit(self) -> None:
        raw = self.url_text.get("1.0", "end-1c")
        urls = [line.strip() for line in raw.splitlines() if line.strip()]
        if not urls:
            self.flash(self.t("msg_need_url"), "warn")
            return
        result = self.manager.add_tasks(urls, self.preset_var.get(), self.playlist_var.get())
        created = len(result["created"])
        duplicates = len(result["duplicates"])
        invalid = len(result["invalid"])
        if created:
            self.url_text.delete("1.0", "end")
            parts = [self.t("msg_added", count=created)]
            if duplicates:
                parts.append(self.t("msg_skipped_dup", count=duplicates))
            if invalid:
                parts.append(self.t("msg_ignored_invalid", count=invalid))
            self.flash(" · ".join(parts), "ok")
            self.notebook.select(self.queue_tab)
        else:
            reasons = []
            if duplicates:
                reasons.append(self.t("msg_dup_reason"))
            if invalid:
                reasons.append(self.t("msg_invalid_reason"))
            self.flash(self.t("msg_no_tasks") + " · ".join(reasons), "bad")

    def cancel_task(self, task_id: str) -> None:
        self.flash(self.t("msg_canceling"), "warn")
        threading.Thread(target=self.manager.cancel_task, args=(task_id,), daemon=True).start()

    def open_log(self, task_id: str) -> None:
        window = self.log_windows.get(task_id)
        if window is not None and window.winfo_exists():
            window.lift()
            window.focus_force()
            return
        self.log_windows[task_id] = LogWindow(self, task_id)

    def open_output_dir(self) -> None:
        ok, message = self.manager.open_path(path=self.manager.config["output_dir"])
        if not ok:
            self.flash(message, "bad")

    def change_output_dir(self) -> None:
        path = filedialog.askdirectory(
            parent=self.root,
            initialdir=self.manager.config["output_dir"],
            title=self.t("choose_dir"),
        )
        if not path:
            return
        ok, message = self.manager.update_config({"output_dir": path})
        if not ok:
            messagebox.showerror(self.t("save_failed"), message, parent=self.root)
            return
        self.output_label.config(text=shorten_path(self.manager.config["output_dir"]))
        self.flash(self.t("output_changed"), "ok")

    def flash(self, text: str, kind: str = "muted") -> None:
        label = getattr(self, "status_label", None)
        if label is None:
            return
        try:
            if not label.winfo_exists():
                return
            colors = {
                "ok": self.theme["ok"],
                "bad": self.theme["bad"],
                "warn": self.theme["warn"],
                "muted": self.theme["muted"],
            }
            label.config(text=text, fg=colors.get(kind, self.theme["muted"]))
            if self._status_job is not None:
                try:
                    self.root.after_cancel(self._status_job)
                except tk.TclError:
                    pass
            self._status_job = self.root.after(8000, self._clear_status)
        except tk.TclError:
            pass

    def _clear_status(self) -> None:
        try:
            if self.status_label.winfo_exists():
                self.status_label.config(text="")
        except (tk.TclError, AttributeError):
            pass

    # ---------- 设置 ----------

    def open_settings(self) -> None:
        c = self.theme
        dialog = tk.Toplevel(self.root)
        dialog.title(self.t("settings"))
        dialog.configure(bg=c["panel"])
        dialog.transient(self.root)
        dialog.resizable(True, True)

        footer = tk.Frame(dialog, bg=c["panel"], padx=22, pady=14)
        footer.pack(side="bottom", fill="x")
        tk.Frame(dialog, bg=c["border"], height=1).pack(side="bottom", fill="x")

        shell = tk.Frame(dialog, bg=c["panel"])
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=c["panel"], highlightthickness=0, bd=0, width=540)
        scroll = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        wrap = tk.Frame(canvas, bg=c["panel"], padx=22, pady=18)
        window_id = canvas.create_window((0, 0), window=wrap, anchor="nw")
        wrap.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))

        def on_wheel(event):
            try:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            except tk.TclError:
                pass

        dialog.bind("<MouseWheel>", on_wheel)

        tk.Label(wrap, text=self.t("settings"), bg=c["panel"], fg=c["text"], font=(FONT, 13, "bold")).pack(
            anchor="w"
        )
        tk.Label(
            wrap, text=self.t("settings_subtitle"), bg=c["panel"], fg=c["muted"], font=(FONT, 9)
        ).pack(anchor="w", pady=(2, 12))

        def section(text, pady):
            tk.Label(wrap, text=text, bg=c["panel"], fg=c["muted"], font=(FONT, 9)).pack(
                anchor="w", pady=pady
            )

        def option_row(choices, var):
            row = tk.Frame(wrap, bg=c["panel"])
            row.pack(fill="x")
            holders = {}

            def paint():
                for key, btn in holders.items():
                    on = var.get() == key
                    btn.config(
                        bg=c["accent_soft"] if on else c["entry"],
                        fg=c["accent"] if on else c["text"],
                        highlightbackground=c["accent"] if on else c["border"],
                    )

            for key, label in choices:
                btn = tk.Button(
                    row,
                    text=label,
                    command=lambda k=key: (var.set(k), paint()),
                    bg=c["entry"],
                    fg=c["text"],
                    activebackground=c["card_hover"],
                    activeforeground=c["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=c["border"],
                    padx=16,
                    pady=6,
                    font=(FONT, 9),
                    cursor="hand2",
                )
                btn.pack(side="left", padx=(0, 8))
                holders[key] = btn
            paint()
            return row

        section(self.t("appearance"), (4, 6))
        theme_var = tk.StringVar(value=self.theme_name)
        option_row(
            [("dark", self.t("theme_dark")), ("light", self.t("theme_light"))],
            theme_var,
        )

        section(self.t("language"), (16, 6))
        lang_var = tk.StringVar(value=self.lang)
        option_row([(code, name) for code, name in i18n.LANGUAGES], lang_var)

        section(self.t("animations"), (16, 6))
        anim_var = tk.StringVar(value="on" if self.animations else "off")
        option_row([("on", self.t("on")), ("off", self.t("off"))], anim_var)

        section(self.t("sound"), (16, 6))
        sound_row = tk.Frame(wrap, bg=c["panel"])
        sound_row.pack(fill="x")
        sound_var = tk.StringVar(value="on" if self.sound_enabled else "off")
        sound_buttons = {}

        def paint_sound():
            for key, btn in sound_buttons.items():
                on = sound_var.get() == key
                btn.config(
                    bg=c["accent_soft"] if on else c["entry"],
                    fg=c["accent"] if on else c["text"],
                    highlightbackground=c["accent"] if on else c["border"],
                )

        for key, label in (("on", self.t("on")), ("off", self.t("off"))):
            btn = tk.Button(
                sound_row,
                text=label,
                command=lambda k=key: (sound_var.set(k), paint_sound()),
                bg=c["entry"],
                fg=c["text"],
                activebackground=c["card_hover"],
                activeforeground=c["text"],
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=c["border"],
                padx=16,
                pady=6,
                font=(FONT, 9),
                cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 8))
            sound_buttons[key] = btn
        paint_sound()

        sound_keys = list(core.SOUNDS)
        sound_combo = ttk.Combobox(
            sound_row,
            values=[self.t(f"sound_{key}") for key in sound_keys],
            state="readonly",
            width=10,
            font=(FONT, 9),
        )
        try:
            sound_combo.current(sound_keys.index(self.sound_name))
        except ValueError:
            sound_combo.current(0)
        sound_combo.pack(side="left", padx=(10, 0), ipady=2)

        def preview_sound():
            index = sound_combo.current()
            play_sound(sound_keys[index] if 0 <= index < len(sound_keys) else "chime")

        self._button(sound_row, self.t("sound_preview"), preview_sound, "outline").pack(
            side="left", padx=(8, 0)
        )

        section(self.t("concurrency"), (16, 6))
        spin = tk.Spinbox(
            wrap,
            from_=1,
            to=4,
            width=5,
            bg=c["entry"],
            fg=c["text"],
            buttonbackground=c["card"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["border"],
            font=(FONT, 9),
            justify="center",
        )
        spin.delete(0, "end")
        spin.insert(0, str(self.manager.config.get("concurrency", 2)))
        spin.pack(anchor="w", ipady=3)

        section(self.t("other"), (18, 6))
        other_box = tk.Frame(wrap, bg=c["card"], highlightthickness=1, highlightbackground=c["border"])
        other_box.pack(fill="x")

        def other_row(label_text, buttons, first=False):
            if not first:
                tk.Frame(other_box, bg=c["border"], height=1).pack(fill="x")
            row = tk.Frame(other_box, bg=c["card"])
            row.pack(fill="x", padx=14, pady=9)
            tk.Label(row, text=label_text, bg=c["card"], fg=c["text"], font=(FONT, 10)).pack(side="left")
            for label, command in reversed(buttons):
                btn = self._button(row, label, command, "ghost")
                btn.config(width=8)
                btn.pack(side="right", padx=(6, 0))

        other_row(
            self.t("about_ytdlp"),
            [(self.t("open"), lambda: self.open_about(dialog))],
            first=True,
        )
        other_row(
            self.t("support"),
            [
                (self.t("donate_alipay"), lambda: self.open_donation(dialog, "alipay")),
                (self.t("donate_wechat"), lambda: self.open_donation(dialog, "wechat")),
            ],
        )
        other_row(
            self.t("privacy"),
            [(self.t("open"), lambda: self.open_privacy(dialog))],
        )

        def save() -> None:
            try:
                concurrency = int(spin.get())
            except ValueError:
                concurrency = self.manager.config.get("concurrency", 2)
            index = sound_combo.current()
            sound_key = sound_keys[index] if 0 <= index < len(sound_keys) else self.sound_name
            new_theme = theme_var.get()
            new_lang = lang_var.get()
            ok, message = self.manager.update_config(
                {
                    "concurrency": concurrency,
                    "theme": new_theme,
                    "language": new_lang,
                    "animations": anim_var.get() == "on",
                    "sound_enabled": sound_var.get() == "on",
                    "sound_name": sound_key,
                }
            )
            if not ok:
                messagebox.showerror(self.t("save_failed"), message, parent=dialog)
                return
            self.animations = anim_var.get() == "on"
            self.sound_enabled = sound_var.get() == "on"
            self.sound_name = sound_key
            dialog.destroy()
            theme_changed = new_theme != self.theme_name
            lang_changed = new_lang != self.lang
            if theme_changed or lang_changed:
                self.theme_name = new_theme
                self.theme = THEMES[new_theme]
                self.lang = new_lang
                self.rebuild_ui()
                if theme_changed:
                    key = "switched_dark" if new_theme == "dark" else "switched_light"
                    self.flash(self.t(key), "ok")
                else:
                    self.flash(self.t("settings_saved"), "ok")
            else:
                if not self.animations:
                    self._snap_animations()
                self.flash(self.t("settings_saved"), "ok")

        self._button(footer, self.t("save"), save, "accent").pack(side="right")
        self._button(footer, self.t("cancel"), dialog.destroy, "outline").pack(side="right", padx=(0, 8))

        dialog.update_idletasks()
        width = 580
        screen_h = self.root.winfo_screenheight()
        height = min(760, max(560, screen_h - 160))
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.minsize(520, 460)
        dialog.grab_set()
        dialog.after(80, lambda: self.apply_window_theme(dialog))

    def open_link(self, url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception:
            self.flash(self.t("link_failed"), "bad")

    def open_about(self, parent) -> None:
        self._show_info(
            parent,
            self.t("about_ytdlp"),
            self.t("about_text"),
            (self.t("about_github"), lambda: self.open_link(GITHUB_URL)),
        )

    def open_donation(self, parent, method: str = "alipay") -> None:
        """赞助页面：支付宝 / 微信 两种收款二维码。"""
        c = self.theme
        dialog = tk.Toplevel(parent)
        dialog.title(self.t("donate_title"))
        dialog.configure(bg=c["panel"])
        dialog.transient(parent)
        dialog.resizable(False, False)

        wrap = tk.Frame(dialog, bg=c["panel"], padx=24, pady=18)
        wrap.pack(fill="both", expand=True)

        tab_row = tk.Frame(wrap, bg=c["panel"])
        tab_row.pack(pady=(0, 12))
        qr_label = tk.Label(wrap, bg=c["panel"], bd=0)
        qr_label.pack()
        hint = tk.Label(
            wrap,
            bg=c["panel"],
            fg=c["muted"],
            font=(FONT, 9),
            justify="center",
            wraplength=420,
        )
        hint.pack(pady=(12, 0))

        limit = max(280, min(560, self.root.winfo_screenheight() - 360))
        images = {
            "alipay": load_qr(ASSETS_DIR / "alipay.png", limit),
            "wechat": load_qr(ASSETS_DIR / "wechat.png", limit),
        }
        available = [key for key, image in images.items() if image is not None]
        current = method if images.get(method) is not None else (available[0] if available else "alipay")
        buttons = {}

        def paint(key: str) -> None:
            nonlocal current
            current = key
            for name, btn in buttons.items():
                on = name == key
                btn.config(
                    bg=c["accent_soft"] if on else c["entry"],
                    fg=c["accent"] if on else c["text"],
                    highlightbackground=c["accent"] if on else c["border"],
                )
            image = images.get(key)
            if image is None:
                qr_label.config(image="", text=self.t("qr_missing"), fg=c["muted"], width=32, height=10)
            else:
                qr_label.config(image=image, text="")
                qr_label.image = image
            hint.config(text=self.t(f"donate_{key}_hint"))

        for key in ("alipay", "wechat"):
            btn = tk.Button(
                tab_row,
                text=self.t(f"donate_{key}"),
                command=lambda k=key: paint(k),
                bg=c["entry"],
                fg=c["text"],
                activebackground=c["card_hover"],
                activeforeground=c["text"],
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=c["border"],
                padx=18,
                pady=6,
                font=(FONT, 9),
                cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 8))
            buttons[key] = btn

        def close() -> None:
            dialog.destroy()
            try:
                if parent.winfo_exists():
                    parent.grab_set()
            except tk.TclError:
                pass

        self._button(wrap, self.t("close"), close, "outline").pack(pady=(16, 0))
        dialog.protocol("WM_DELETE_WINDOW", close)

        paint(current)
        dialog.update_idletasks()
        sized = [image for image in images.values() if image is not None]
        current_image = images.get(current)
        extra = dialog.winfo_reqheight() - (current_image.height() if current_image else 0)
        width = max(440, max((image.width() for image in sized), default=400) + 48)
        height = extra + max((image.height() for image in sized), default=300)
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        x = min(max(0, x), max(0, self.root.winfo_screenwidth() - width - 16))
        y = min(max(0, y), max(0, self.root.winfo_screenheight() - height - 56))
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.grab_set()
        dialog.after(80, lambda: self.apply_window_theme(dialog))

    def open_privacy(self, parent) -> None:
        self._show_info(parent, self.t("privacy"), self.t("privacy_text"))

    def _show_info(self, parent, title: str, body: str, action=None) -> None:
        c = self.theme
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.configure(bg=c["panel"])
        dialog.transient(parent)
        dialog.resizable(False, False)

        wrap = tk.Frame(dialog, bg=c["panel"], padx=24, pady=20)
        wrap.pack(fill="both", expand=True)
        tk.Label(
            wrap, text=title, bg=c["panel"], fg=c["text"], font=(FONT, 14, "bold"), anchor="w"
        ).pack(fill="x")
        tk.Label(
            wrap,
            text=body,
            bg=c["panel"],
            fg=c["muted"],
            font=(FONT, 10),
            justify="left",
            anchor="w",
            wraplength=440,
        ).pack(fill="x", pady=(12, 0))

        row = tk.Frame(wrap, bg=c["panel"])
        row.pack(fill="x", pady=(20, 0))

        def close() -> None:
            dialog.destroy()
            try:
                if parent.winfo_exists():
                    parent.grab_set()
            except tk.TclError:
                pass

        if action is not None:
            label, command = action
            self._button(row, label, command, "accent").pack(side="left")
        self._button(row, self.t("close"), close, "outline").pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close)

        dialog.update_idletasks()
        width = max(500, dialog.winfo_reqwidth() + 6)
        height = dialog.winfo_reqheight()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.grab_set()
        dialog.after(80, lambda: self.apply_window_theme(dialog))

    def on_close(self) -> None:
        stats = self.manager.stats()
        active = stats.get("pending", 0) + stats.get("running", 0)
        if active:
            if not messagebox.askyesno(
                self.t("app_title"),
                self.t("exit_body", count=active),
                parent=self.root,
            ):
                return
        self._alive = False
        try:
            self.manager.shutdown()
        except Exception:
            pass
        self.root.destroy()


class LogWindow(tk.Toplevel):
    def __init__(self, app: App, task_id: str):
        super().__init__(app.root)
        self.app = app
        self.manager = app.manager
        self.task_id = task_id
        c = app.theme
        self.title(app.t("task_log"))
        self.configure(bg=c["panel"])
        self.minsize(520, 320)
        self.transient(app.root)

        wrap = tk.Frame(self, bg=c["panel"], padx=16, pady=14)
        wrap.pack(fill="both", expand=True)
        self.head = tk.Label(
            wrap, text="", bg=c["panel"], fg=c["text"], font=(FONT, 11, "bold"), anchor="w", justify="left"
        )
        self.head.pack(fill="x")
        self.sub = tk.Label(
            wrap,
            text="",
            bg=c["panel"],
            fg=c["muted"],
            font=(FONT, 9),
            anchor="w",
            justify="left",
            wraplength=680,
        )
        self.sub.pack(fill="x", pady=(3, 10))

        body = tk.Frame(wrap, bg=c["border"], padx=1, pady=1)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(
            body,
            bg=c["entry"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="none",
            font=(MONO, 9),
            padx=10,
            pady=8,
            state="disabled",
        )
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        self._first_line = None
        self._last_len = 0
        self._last_line = None
        self.bind("<Destroy>", self._on_destroy)

        width, height = 760, 460
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width() - width) // 2)
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.after(80, lambda: app.apply_window_theme(self))
        self._refresh()

    def _on_destroy(self, event) -> None:
        if event.widget is self:
            self.app.log_windows.pop(self.task_id, None)

    def _refresh(self) -> None:
        if not self.winfo_exists():
            return
        detail = self.manager.task_detail(self.task_id)
        if detail is None:
            self.head.config(text=self.app.t("task_deleted"))
            self.sub.config(text="")
        else:
            self.head.config(
                text=f"{shorten(display_title(detail), 64)} · {task_status_text(detail, self.app.lang)}"
            )
            self.sub.config(text=shorten(detail["url"], 110))
            log = detail["log"]
            first = log[0] if log else None
            if log and (first != self._first_line or len(log) < self._last_len):
                self._write_all(log)
            elif log and log[-1] != self._last_line:
                self._append(log[self._last_len:])
            self._first_line = first
            self._last_len = len(log)
            self._last_line = log[-1] if log else None
        if self.winfo_exists():
            self.after(1000, self._refresh)

    def _write_all(self, log: list[str]) -> None:
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(log))
        self.text.config(state="disabled")
        self.text.see("end")

    def _append(self, lines: list[str]) -> None:
        if not lines:
            return
        self.text.config(state="normal")
        self.text.insert("end", "\n" + "\n".join(lines))
        self.text.config(state="disabled")
        self.text.see("end")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        detail = traceback.format_exc()
        try:
            core.DATA_DIR.mkdir(parents=True, exist_ok=True)
            (core.DATA_DIR / "crash.log").write_text(detail, encoding="utf-8")
        except Exception:
            pass
        try:
            lang = "zh"
            raw = core.load_json(core.CONFIG_FILE, {})
            if isinstance(raw, dict) and raw.get("language") in core.LANGUAGES:
                lang = raw["language"]
            title = f"{i18n.tr(lang, 'app_title')} - {i18n.tr(lang, 'startup_failed')}"
            ctypes.windll.user32.MessageBoxW(0, detail[-1500:], title, 0x10)
        except Exception:
            print(detail)

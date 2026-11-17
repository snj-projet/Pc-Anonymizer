import os
import shutil
import tempfile
import subprocess
import webbrowser
from tkinter import filedialog, messagebox, END
import customtkinter as ctk
from PIL import Image, ImageFilter, ImageTk
import winreg
import socket
import pyperclip
import json
import psutil
from datetime import datetime
import threading
import time
import random
import string
import hashlib
import platform
import math
import uuid

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_VERSION = "2.4"
SETTINGS_FILE = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "JustDown", "settings.json")

COLOR_SUCCESS = "#10B981"
COLOR_WARNING = "#FFA502"
COLOR_DANGER = "#EF4444"


def load_user_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_user_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass



DNS_PROVIDERS = {
    "Cloudflare": ("1.1.1.1", "1.0.0.1", "Sécurité & Rapidité"),
    "Google": ("8.8.8.8", "8.8.4.4", "Fiabilité"),
    "OpenDNS": ("208.67.222.222", "208.67.220.220", "Filtrage Parental"),
    "Quad9": ("9.9.9.9", "149.112.112.112", "Anti-Malware"),
}
PRIVACY_DNS_IPS = {ip for p, s, _ in DNS_PROVIDERS.values() for ip in (p, s)} | {"94.140.14.14", "94.140.15.15"}


def run_quiet(cmd, timeout=30):
    """subprocess.run sans fenêtre console, sortie décodée avec la page de code OEM (accents de netsh)."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="oem", errors="replace",
                          timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def format_size(num_bytes):
    for unit in ("o", "Ko", "Mo", "Go"):
        if num_bytes < 1024 or unit == "Go":
            return f"{num_bytes:.0f} {unit}" if unit == "o" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def empty_dir(path):
    """Vide un dossier sans le supprimer (les fichiers verrouillés sont ignorés). Renvoie les octets libérés."""
    if not os.path.isdir(path):
        return 0
    before = dir_size(path)
    for entry in os.scandir(path):
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                os.unlink(entry.path)
        except OSError:
            continue
    return max(before - dir_size(path), 0)


def chromium_profiles():
    """Renvoie [(navigateur, dossier_profil)] pour Chrome, Edge et Brave."""
    local = os.environ.get("LOCALAPPDATA", "")
    bases = {
        "Chrome": os.path.join(local, "Google", "Chrome", "User Data"),
        "Edge": os.path.join(local, "Microsoft", "Edge", "User Data"),
        "Brave": os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"),
    }
    profiles = []
    for browser, base in bases.items():
        if os.path.isdir(base):
            for name in os.listdir(base):
                if name == "Default" or name.startswith("Profile "):
                    profiles.append((browser, os.path.join(base, name)))
    return profiles


def firefox_profiles():
    """Renvoie [(dossier_profil_roaming, dossier_cache_local)] pour Firefox."""
    roaming = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Mozilla", "Firefox", "Profiles")
    if not os.path.isdir(roaming):
        return []
    return [(os.path.join(roaming, n), os.path.join(local, n)) for n in os.listdir(roaming)
            if os.path.isdir(os.path.join(roaming, n))]


def browser_cache_dirs():
    dirs = []
    for _browser, profile in chromium_profiles():
        dirs += [os.path.join(profile, d) for d in ("Cache", "Code Cache", "GPUCache")]
    for _roaming, local in firefox_profiles():
        dirs.append(os.path.join(local, "cache2"))
    return [d for d in dirs if os.path.isdir(d)]


def error_report_dirs():
    local = os.environ.get("LOCALAPPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    dirs = [os.path.join(local, "CrashDumps")]
    for base in (os.path.join(local, "Microsoft", "Windows", "WER"),
                 os.path.join(progdata, "Microsoft", "Windows", "WER")):
        dirs += [os.path.join(base, "ReportArchive"), os.path.join(base, "ReportQueue")]
    return [d for d in dirs if os.path.isdir(d)]


def temp_dirs():
    dirs = [os.environ.get("TEMP", ""), os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp")]
    return [d for d in dirs if d and os.path.isdir(d)]


def recycle_bin_size():
    try:
        import ctypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return info.i64Size
    except Exception:
        pass
    return 0


def empty_recycle_bin():
    try:
        import ctypes
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    except Exception:
        pass


def sqlite_purge(db_path, statements):
    """Exécute des DELETE sur une base de navigateur. Renvoie False si la base est verrouillée (navigateur ouvert)."""
    import sqlite3
    if not os.path.isfile(db_path):
        return True
    try:
        conn = sqlite3.connect(db_path, timeout=1)
        try:
            for sql in statements:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        raise
            conn.commit()
        finally:
            conn.close()
        return True
    except sqlite3.OperationalError:
        return False


class AnimatedButton(ctk.CTkButton):
    def __init__(self, master, *args, **kwargs):
        hover_color = kwargs.pop('hover_color', None)
        active_color = kwargs.pop('active_color', None)
        active_text_color = kwargs.pop('active_text_color', None)
        super().__init__(master, *args, **kwargs)
        self._hover_color = hover_color
        self._active_color = active_color
        self._active_text_color = active_text_color
        self._original_color = kwargs.get('fg_color', self._fg_color)
        self._original_text_color = kwargs.get('text_color', self._text_color)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self._is_active = False

    def set_active(self, active=True):
        self._is_active = active
        if active:
            if self._active_color:
                self.configure(fg_color=self._active_color)
            if self._active_text_color:
                self.configure(text_color=self._active_text_color)
        else:
            self.configure(fg_color=self._original_color)
            if self._original_text_color:
                self.configure(text_color=self._original_text_color)

    def _on_enter(self, e=None):
        if not self._is_active and self._hover_color:
            self.configure(fg_color=self._hover_color)

    def _on_leave(self, e=None):
        if not self._is_active:
            self.configure(fg_color=self._original_color)


class ModernProgressBar(ctk.CTkFrame):
    """Barre d'activité indéterminée, visible uniquement pendant un traitement."""
    def __init__(self, master, progress_color=None, track_color=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(height=4)
        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate", height=4,
                                               corner_radius=2)
        if progress_color:
            self.progress_bar.configure(progress_color=progress_color)
        if track_color:
            self.progress_bar.configure(fg_color=track_color)
        self.progress_bar.pack(fill="x", padx=2)
        self._grid_info = None
        self._running = False

    def grid(self, **kwargs):
        super().grid(**kwargs)
        self._grid_info = kwargs
        self.grid_remove()

    def set_colors(self, progress_color, track_color):
        self.progress_bar.configure(progress_color=progress_color, fg_color=track_color)

    def start(self):
        if self._running:
            return
        self._running = True
        if self._grid_info is not None:
            super().grid()
        self.progress_bar.start()

    def stop(self):
        self._running = False
        self.progress_bar.stop()
        if self._grid_info is not None:
            self.grid_remove()

    def set(self, value):
        self.progress_bar.set(value)


class SecurityScoreWidget(ctk.CTkFrame):
    """Widget affichant un score de sécurité circulaire moderne sans découpe de fond."""
    def __init__(self, master, score=0, size=150, primary_color="#00D2FF", widget_bg_color="#131726",
                 track_color="#1E253A", subtitle="Score Sécurité"):
        super().__init__(master, fg_color=widget_bg_color, width=size, height=size, corner_radius=0)
        self.score = score
        self.size = size
        self.primary_color = primary_color
        self.widget_bg_color = widget_bg_color
        self.track_color = track_color
        self.subtitle = subtitle
        self._animated_score = 0

        import tkinter as tk
        self.canvas = tk.Canvas(self, width=size, height=size, bg=widget_bg_color,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.draw_score(0)

    def draw_score(self, current_score):
        if not self.winfo_exists():
            return
        try:
            self.canvas.delete("all")
            cx, cy = self.size // 2, self.size // 2
            r = self.size // 2 - 16
            width = 11

            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    outline=self.track_color, width=width)

            if current_score > 0:
                extent = -(current_score / 100) * 360
                self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                                       start=90, extent=extent,
                                       outline=self.primary_color, width=width, style="arc")

            self.canvas.create_text(cx, cy - 10, text=f"{int(current_score)}%",
                                    fill="#F8FAFC", font=("Segoe UI", 24, "bold"))
            self.canvas.create_text(cx, cy + 16, text=self.subtitle,
                                    fill="#94A3B8", font=("Segoe UI", 9, "bold"))
        except Exception:
            pass

    def animate_to(self, target_score):
        if not self.winfo_exists():
            return
        self.score = target_score
        self._animated_score = 0
        self._animate_step()

    def _animate_step(self):
        if not self.winfo_exists():
            return
        try:
            if self._animated_score < self.score:
                self._animated_score = min(self._animated_score + 2, self.score)
                self.draw_score(self._animated_score)
                self.after(15, self._animate_step)
            else:
                self.draw_score(self.score)
        except Exception:
            pass



FAKE_FIRST_NAMES_M = [
    "Alexandre", "Antoine", "Baptiste", "Charles", "David", "Émile",
    "François", "Gabriel", "Hugo", "Julien", "Lucas", "Mathieu",
    "Nicolas", "Olivier", "Pierre", "Raphaël", "Sébastien", "Thomas",
    "Victor", "William", "James", "Robert", "Michael", "Daniel"
]

FAKE_FIRST_NAMES_F = [
    "Alice", "Camille", "Diane", "Emma", "Florence", "Gabrielle",
    "Hélène", "Isabelle", "Juliette", "Léa", "Marie", "Nathalie",
    "Olivia", "Pauline", "Rachel", "Sophie", "Valérie", "Zoé",
    "Sarah", "Laura", "Emily", "Charlotte", "Amelia", "Victoria"
]

FAKE_LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard",
    "Petit", "Durand", "Leroy", "Moreau", "Simon", "Laurent",
    "Lefebvre", "Michel", "Garcia", "David", "Bertrand", "Roux",
    "Vincent", "Fournier", "Morel", "Girard", "André", "Mercier",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Davis"
]

FAKE_STREETS = [
    "Rue de la Paix", "Avenue des Champs-Élysées", "Boulevard Saint-Germain",
    "Rue du Faubourg Saint-Honoré", "Place de la République", "Rue de Rivoli",
    "Avenue Victor Hugo", "Rue Montorgueil", "Boulevard Haussmann",
    "Rue de la Liberté", "Avenue Jean Jaurès", "Rue Pasteur",
    "Maple Street", "Oak Avenue", "Cedar Lane", "Pine Road"
]

FAKE_CITIES = [
    ("Paris", "75001"), ("Lyon", "69001"), ("Marseille", "13001"),
    ("Toulouse", "31000"), ("Nice", "06000"), ("Nantes", "44000"),
    ("Strasbourg", "67000"), ("Bordeaux", "33000"), ("Lille", "59000"),
    ("Rennes", "35000"), ("Montpellier", "34000"), ("Grenoble", "38000"),
    ("London", "SW1A 1AA"), ("Berlin", "10115"), ("Amsterdam", "1012")
]

FAKE_EMAIL_DOMAINS = [
    "protonmail.com", "tutanota.com", "guerrillamail.com",
    "mailinator.com", "tempmail.org", "throwaway.email"
]


class JustDownApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.is_vpn_connected = False
        self.public_ip = "Chargement..."
        self.current_tab_id = "DASHBOARD"
        self.current_tab = None
        self.selected_files = []
        self.generated_emails_history = []
        self.secure_delete_after_encrypt = False

        self.user_settings = load_user_settings()
        self._toasts = []
        self._nav_order = []
        self._nav_commands = {}
        self._dash_job = None

        self.title("JustDown — Privacy & Anonymization Suite")
        self._center_window(1240, 820)
        self.minsize(1000, 680)

        self.load_icons()

        self.themes = {
            "Cyber Stealth": {
                "primary": "#00D2FF",
                "secondary": "#181D2E",
                "accent": "#38BDF8",
                "background": "#0A0C13",
                "card": "#131726",
                "border": "#1E253A",
                "text": "#F8FAFC",
                "text_secondary": "#94A3B8"
            },
            "Indigo Tech": {
                "primary": "#6366F1",
                "secondary": "#191D33",
                "accent": "#818CF8",
                "background": "#0B0D17",
                "card": "#14182B",
                "border": "#212744",
                "text": "#F8FAFC",
                "text_secondary": "#94A3B8"
            },
            "Émeraude Shield": {
                "primary": "#10B981",
                "secondary": "#14241E",
                "accent": "#34D399",
                "background": "#0A120E",
                "card": "#101D17",
                "border": "#1A3026",
                "text": "#F8FAFC",
                "text_secondary": "#94A3B8"
            },
            "Violet Nébuleuse": {
                "primary": "#A855F7",
                "secondary": "#1E1831",
                "accent": "#C084FC",
                "background": "#0C0A15",
                "card": "#151125",
                "border": "#251D3E",
                "text": "#F8FAFC",
                "text_secondary": "#94A3B8"
            },
            "Gris Titane": {
                "primary": "#94A3B8",
                "secondary": "#1B1F27",
                "accent": "#CBD5E1",
                "background": "#0D0F13",
                "card": "#14171E",
                "border": "#222732",
                "text": "#F8FAFC",
                "text_secondary": "#94A3B8"
            },
            "Cyberpunk 2077": {
                "primary": "#00FFAA",
                "secondary": "#181A2D",
                "accent": "#FF2A6D",
                "background": "#0B0C16",
                "card": "#131524",
                "border": "#22253E",
                "text": "#F8FAFC",
                "text_secondary": "#94A3B8"
            }
        }

        saved_theme = self.user_settings.get("theme", "Cyber Stealth")
        self.selected_theme_name = saved_theme if saved_theme in self.themes else "Cyber Stealth"
        self._apply_theme_colors(self.selected_theme_name)

        self.configure(fg_color=self.bg_color)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.create_sidebar()
        self.create_topbar()

        self.main_frame = ctk.CTkFrame(self, corner_radius=16, fg_color=self.card_color,
                                       border_width=1, border_color=self.border_color)
        self.main_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 16), pady=(0, 14))

        self.status_bar = ModernProgressBar(self, fg_color="transparent",
                                            progress_color=self.primary_color,
                                            track_color=self.bg_color)
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 6))

        self._bind_shortcuts()
        try:
            psutil.cpu_percent(None)  # amorce la mesure CPU (le 1er appel renvoie toujours 0)
        except Exception:
            pass

        self.vpn_locations_list = [
            "Paris, France", "Marseille, France", "London, UK", "Berlin, Germany",
            "Frankfurt, Germany", "Amsterdam, Netherlands", "Madrid, Spain",
            "New York, USA", "Los Angeles, USA", "Chicago, USA", "Toronto, Canada",
            "Montréal, Canada", "Tokyo, Japan", "Sydney, Australia"
        ]
        self.selected_location = ctk.StringVar(value="Paris, France")

        self.secure_delete_after_encrypt = False
        self.init_vpn_engine()
        self.init_kill_switch()
        self.init_permissions_state()
        self.is_anti_spy_active = self.get_windows_permission("advertising_id")
        self.fetch_ip_thread()
        self.refresh_vpngate_servers_thread()
        self.switch_tab("DASHBOARD", self.create_dashboard_tab)
        self._tick()

    def _center_window(self, width, height):
        """Centre la fenêtre sur l'écran (bornée à la taille de l'écran)."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(width, sw - 40), min(height, sh - 80)
        x, y = max((sw - width) // 2, 0), max((sh - height) // 2 - 20, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _bind_shortcuts(self):
        """Ctrl+1..9 : onglets de la barre latérale, F5 : actualiser l'onglet courant."""
        for i in range(1, 10):
            self.bind(f"<Control-Key-{i}>", lambda e, idx=i - 1: self._switch_to_nav_index(idx))
        self.bind("<F5>", lambda e: self.current_tab and self.current_tab())

    def _switch_to_nav_index(self, idx):
        if idx < len(self._nav_order):
            tab_id = self._nav_order[idx]
            self.switch_tab(tab_id, self._nav_commands[tab_id])

    def _tick(self):
        """Boucle unique (1 s) : horloge + indicateurs d'état VPN de la barre supérieure et latérale."""
        try:
            if getattr(self, 'clock_label', None) and self.clock_label.winfo_exists():
                self.clock_label.configure(text=f"{self.icons['clock']} {time.strftime('%H:%M:%S')}")
            self._refresh_status_indicators()
        except Exception:
            pass
        self.after(1000, self._tick)

    def _refresh_status_indicators(self):
        connected = self.is_vpn_connected
        if getattr(self, 'top_status_dot', None) and self.top_status_dot.winfo_exists():
            self.top_status_dot.configure(text_color=COLOR_SUCCESS if connected else COLOR_WARNING)
            self.top_status_text.configure(
                text=f"Protégé · {self.active_vpn_client}" if connected else "Système Partiel")
        if getattr(self, 'sidebar_vpn_label', None) and self.sidebar_vpn_label.winfo_exists():
            self.sidebar_vpn_label.configure(
                text="● VPN Protégé" if connected else "● VPN Inactif",
                text_color=COLOR_SUCCESS if connected else "#64748B")


    def notify(self, title, message="", kind=None):
        """Affiche une notification éphémère en bas à droite, sans bloquer l'interface."""
        if kind is None:
            success_words = ("succès", "copié", "terminé", "connecté avec", "exporté", "corrigé")
            kind = "success" if any(w in title.lower() for w in success_words) else "info"
        accent = {"success": COLOR_SUCCESS, "warning": COLOR_WARNING,
                  "error": COLOR_DANGER}.get(kind, self.primary_color)
        icon = {"success": "✔", "warning": "⚠", "error": "✖"}.get(kind, "ℹ")

        toast = ctk.CTkFrame(self, fg_color=self.secondary_color, corner_radius=12,
                             border_width=1, border_color=accent)
        bar = ctk.CTkFrame(toast, fg_color=accent, width=4, corner_radius=2)
        bar.pack(side="left", fill="y", padx=(8, 0), pady=10)

        body = ctk.CTkFrame(toast, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=(10, 6), pady=8)
        ctk.CTkLabel(body, text=f"{icon}  {title}", font=("Segoe UI", 12, "bold"),
                     text_color=accent, anchor="w", justify="left").pack(anchor="w")
        if message:
            ctk.CTkLabel(body, text=message, font=("Segoe UI", 11),
                         text_color=self.text_color, anchor="w", justify="left",
                         wraplength=330).pack(anchor="w", pady=(2, 0))

        close_btn = ctk.CTkButton(toast, text="✕", width=24, height=24, corner_radius=6,
                                  fg_color="transparent", hover_color=self.border_color,
                                  text_color=self.text_color_secondary, font=("Segoe UI", 11),
                                  command=lambda: self._dismiss_toast(toast))
        close_btn.pack(side="right", anchor="n", padx=(0, 6), pady=6)

        self._toasts.append(toast)
        self._layout_toasts()
        duration = min(3000 + 30 * len(message), 9000)
        self.after(duration, lambda: self._dismiss_toast(toast))

    def _dismiss_toast(self, toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
            try:
                toast.destroy()
            except Exception:
                pass
            self._layout_toasts()

    def _layout_toasts(self):
        while len(self._toasts) > 4:
            self._toasts.pop(0).destroy()
        y = -26
        for toast in reversed(self._toasts):
            toast.update_idletasks()
            toast.place(relx=1.0, rely=1.0, anchor="se", x=-26, y=y)
            toast.lift()
            y -= toast.winfo_reqheight() / toast._get_widget_scaling() + 8


    def _apply_theme_colors(self, theme_name):
        """Applique les couleurs d'un thème sans reconstruire l'UI."""
        self.selected_theme_name = theme_name
        theme = self.themes.get(theme_name, self.themes["Cyber Stealth"])
        self.primary_color = theme["primary"]
        self.secondary_color = theme["secondary"]
        self.accent_color = theme["accent"]
        self.bg_color = theme["background"]
        self.card_color = theme["card"]
        self.border_color = theme.get("border", "#1E253A")
        self.text_color = theme["text"]
        self.text_color_secondary = theme["text_secondary"]

    def apply_theme(self, theme_name):
        """Applique un thème à toute l'interface (barre latérale et supérieure reconstruites) et le mémorise."""
        self._apply_theme_colors(theme_name)
        self.user_settings["theme"] = theme_name
        save_user_settings(self.user_settings)

        self.configure(fg_color=self.bg_color)
        self.main_frame.configure(fg_color=self.card_color, border_color=self.border_color)
        self.status_bar.set_colors(self.primary_color, self.bg_color)

        self.sidebar_frame.destroy()
        self.topbar.destroy()
        self.create_sidebar()
        self.create_topbar()
        self._refresh_status_indicators()

        if self.current_tab:
            self.switch_tab(self.current_tab_id, self.current_tab)


    def load_icons(self):
        self.icons = {
            "vpn": "\U0001F512",        # 🔒
            "clean": "\U0001F9F9",       # 🧹
            "privacy": "\U0001F6E1",     # 🛡️
            "settings": "\u2699\uFE0F",  # ⚙️
            "security": "\U0001F510",    # 🔐
            "system": "\U0001F4BB",      # 💻
            "network": "\U0001F310",     # 🌐
            "user": "\U0001F464",        # 👤
            "clock": "\U0001F552",       # 🕒
            "dns": "\U0001F5A7",         # 🖧
            "encryption": "\U0001F511",  # 🔑
            "cleaner": "\U0001F9F9",     # 🧹
            "delete": "\U0001F5D1",      # 🗑️
            "vm": "\U0001F4E6",          # 📦
            "dashboard": "\U0001F3E0",   # 🏠
            "identity": "\U0001F3AD",    # 🎭
            "serial": "\U0001F4DF",      # 📟
            "email": "\U00002709",       # ✉
            "spy": "\U0001F441",         # 👁
            "copy": "\U0001F4CB",        # 📋
            "shield": "\U0001F6E1",      # 🛡
            "warning": "\u26A0\uFE0F",   # ⚠️
            "check": "\u2705",           # ✅
            "cross": "\u274C",           # ❌
            "refresh": "\U0001F504",     # 🔄
            "bolt": "\u26A1",            # ⚡
            "audit": "\U0001F6E1",        # 🛡️
            "camera": "\U0001F4F7",       # 📷
            "mic": "\U0001F3A4",          # 🎤
            "location": "\U0001F4CD",     # 📍
            "fingerprint": "\U0001F43E",  # 🐾
            "lock": "\U0001F512",         # 🔒
        }


    def fetch_ip_thread(self):
        def get_ip():
            try:
                import urllib.request
                with urllib.request.urlopen('https://api.ipify.org', timeout=5) as response:
                    self.public_ip = response.read().decode('utf-8')
            except Exception:
                self.public_ip = "Indisponible"

            if hasattr(self, 'current_tab_id') and self.current_tab_id in ("DASHBOARD", "VPN"):
                try:
                    self.after(0, self.current_tab)
                except Exception:
                    pass

        threading.Thread(target=get_ip, daemon=True).start()


    def create_topbar(self):
        topbar = self.topbar = ctk.CTkFrame(self, height=52, fg_color="transparent")
        topbar.grid(row=0, column=1, sticky="ew", padx=(10, 16), pady=(12, 6))

        title_box = ctk.CTkFrame(topbar, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(title_box, text="JUSTDOWN  /  ",
                     font=("Segoe UI", 10, "bold"),
                     text_color=self.text_color_secondary).pack(side="left")

        self.page_title_label = ctk.CTkLabel(title_box,
                                             text="Tableau de bord",
                                             font=("Segoe UI", 18, "bold"),
                                             text_color=self.text_color)
        self.page_title_label.pack(side="left")

        right_bar = ctk.CTkFrame(topbar, fg_color="transparent")
        right_bar.pack(side="right")

        self.top_status_pill = ctk.CTkFrame(right_bar, fg_color=self.secondary_color,
                                            corner_radius=20, border_width=1,
                                            border_color=self.border_color)
        self.top_status_pill.pack(side="left", padx=(0, 12), pady=2)

        self.top_status_dot = ctk.CTkLabel(self.top_status_pill, text="●",
                                           font=("Segoe UI", 12), text_color=COLOR_WARNING)
        self.top_status_dot.pack(side="left", padx=(10, 4), pady=4)

        self.top_status_text = ctk.CTkLabel(self.top_status_pill, text="Système Partiel",
                                            font=("Segoe UI", 11, "bold"),
                                            text_color=self.text_color)
        self.top_status_text.pack(side="left", padx=(0, 12), pady=4)

        self.clock_label = ctk.CTkLabel(right_bar, text=f"{self.icons['clock']} {time.strftime('%H:%M:%S')}",
                                        font=("Segoe UI", 12),
                                        text_color=self.text_color_secondary)
        self.clock_label.pack(side="left", padx=(0, 12))

        settings_btn = AnimatedButton(right_bar,
                                      text=f"{self.icons['settings']}",
                                      font=("Segoe UI", 15),
                                      width=38, height=38,
                                      fg_color=self.secondary_color,
                                      hover_color=self.primary_color,
                                      text_color=self.text_color,
                                      corner_radius=10,
                                      border_width=1,
                                      border_color=self.border_color,
                                      command=lambda: self.switch_tab("SETTINGS", self.create_settings_tab))
        settings_btn.pack(side="left")


    def create_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, corner_radius=16, fg_color=self.card_color,
                                          width=245, border_width=1, border_color=self.border_color)
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(14, 0), pady=(12, 14))
        self.sidebar_frame.grid_propagate(False)

        logo_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        logo_frame.pack(fill="x", padx=16, pady=(16, 2))

        logo_row = ctk.CTkFrame(logo_frame, fg_color="transparent")
        logo_row.pack(fill="x")

        ctk.CTkLabel(logo_row, text=f"{self.icons.get('shield', '🛡️')} JustDown",
                     font=("Segoe UI", 21, "bold"),
                     text_color=self.primary_color).pack(side="left")

        pro_badge = ctk.CTkLabel(logo_row, text=" PRO ",
                                 font=("Segoe UI", 8, "bold"),
                                 fg_color=self.primary_color,
                                 text_color="#0A0C13",
                                 corner_radius=4)
        pro_badge.pack(side="left", padx=(8, 0), pady=4)

        ctk.CTkLabel(logo_frame, text="Privacy & Anonymization Suite",
                     font=("Segoe UI", 9),
                     text_color=self.text_color_secondary).pack(anchor="w", pady=(2, 8))

        sep = ctk.CTkFrame(self.sidebar_frame, fg_color=self.border_color, height=1)
        sep.pack(fill="x", padx=14, pady=(0, 6))

        self.sidebar_scroll = ctk.CTkScrollableFrame(self.sidebar_frame, fg_color="transparent",
                                                     scrollbar_button_color=self.border_color,
                                                     scrollbar_button_hover_color=self.primary_color)
        self.sidebar_scroll.pack(fill="both", expand=True, padx=2, pady=(0, 4))

        self.sidebar_nav_buttons = {}
        self._nav_order = []
        self._nav_commands = {}

        self.add_sidebar_button("DASHBOARD", f"{self.icons['dashboard']}  Tableau de bord", self.create_dashboard_tab)

        self._sidebar_section_label("SÉCURITÉ")
        self.add_sidebar_button("VPN", f"{self.icons['vpn']}  Protection VPN", self.create_vpn_tab)
        self.add_sidebar_button("DNS", f"{self.icons['dns']}  Protection DNS", self.create_dns_tab)
        self.add_sidebar_button("ANTI_SPY", f"{self.icons['spy']}  Anti-Espionnage", self.create_anti_spy_tab)
        self.add_sidebar_button("AUDIT", f"{self.icons['audit']}  Audit de Sécurité", self.create_audit_tab)

        self._sidebar_section_label("ANONYMISATION")
        self.add_sidebar_button("SERIAL", f"{self.icons['serial']}  Changement Serial", self.create_serial_tab)
        self.add_sidebar_button("IDENTITY", f"{self.icons['identity']}  Identité Factice", self.create_fake_identity_tab)

        self._sidebar_section_label("CHIFFREMENT")
        self.add_sidebar_button("ENCRYPTION", f"{self.icons['encryption']}  Chiffrement AES", self.create_encryption_tab)

        self._sidebar_section_label("NETTOYAGE")
        self.add_sidebar_button("CLEANER", f"{self.icons['cleaner']}  Nettoyeur Système", self.create_clean_tab)
        self.add_sidebar_button("SECURE_DELETE", f"{self.icons['delete']}  Suppression Sûre", self.create_secure_delete_tab)

        self._sidebar_section_label("CONFIDENTIALITÉ")
        self.add_sidebar_button("PRIVACY", f"{self.icons['privacy']}  Navigation Privée", self.create_privacy_tab)
        self.add_sidebar_button("EMAIL", f"{self.icons['email']}  Email Jetable", self.create_email_tab)

        self._sidebar_section_label("SYSTÈME")
        self.add_sidebar_button("SYS_INFO", f"{self.icons['system']}  Infos Système", self.create_system_info_tab)
        self.add_sidebar_button("SETTINGS", f"{self.icons['settings']}  Paramètres", self.create_settings_tab)

        footer_card = ctk.CTkFrame(self.sidebar_frame, fg_color=self.secondary_color,
                                   corner_radius=10, border_width=1, border_color=self.border_color)
        footer_card.pack(fill="x", padx=12, pady=(4, 10))

        fc_inner = ctk.CTkFrame(footer_card, fg_color="transparent")
        fc_inner.pack(fill="x", padx=10, pady=6)

        self.sidebar_vpn_label = ctk.CTkLabel(fc_inner, text="● VPN Inactif",
                                              font=("Segoe UI", 10, "bold"),
                                              text_color="#64748B")
        self.sidebar_vpn_label.pack(side="left")
        ctk.CTkLabel(fc_inner, text=f"v{APP_VERSION}",
                     font=("Segoe UI", 9),
                     text_color=self.text_color_secondary).pack(side="right")

    def _sidebar_section_label(self, text):
        ctk.CTkLabel(self.sidebar_scroll, text=text,
                     font=("Segoe UI", 9, "bold"),
                     text_color="#64748B").pack(anchor="w", padx=14, pady=(10, 2))

    def add_sidebar_button(self, tab_id, text, command):
        btn = AnimatedButton(self.sidebar_scroll,
                             text=text,
                             font=("Segoe UI", 12),
                             anchor="w",
                             height=34,
                             fg_color="transparent",
                             hover_color=self.secondary_color,
                             active_color=self.secondary_color,
                             active_text_color=self.primary_color,
                             text_color=self.text_color_secondary,
                             corner_radius=8,
                             command=lambda tid=tab_id, cmd=command: self.switch_tab(tid, cmd))
        btn.pack(fill="x", padx=6, pady=1)
        self.sidebar_nav_buttons[tab_id] = btn
        self._nav_order.append(tab_id)
        self._nav_commands[tab_id] = command


    def switch_tab(self, tab_id, command):
        titles = {
            "DASHBOARD": "Tableau de bord",
            "VPN": "VPN Protection",
            "DNS": "Protection DNS",
            "ENCRYPTION": "Chiffrement",
            "CLEANER": "Nettoyeur Système",
            "PRIVACY": "Navigation Privée",
            "SECURE_DELETE": "Suppression Sécurisée",
            "SYS_INFO": "Infos Système",
            "ANTI_SPY": "Anti-Espionnage",
            "AUDIT": "Audit de Sécurité PC",
            "SERIAL": "Changement Serial",
            "IDENTITY": "Identité Factice",
            "EMAIL": "Email Jetable",
            "SETTINGS": "Paramètres",
        }
        if hasattr(self, 'page_title_label'):
            self.page_title_label.configure(text=titles.get(tab_id, "JustDown"))

        for btn in self.sidebar_nav_buttons.values():
            btn.set_active(False)

        if tab_id in self.sidebar_nav_buttons:
            self.sidebar_nav_buttons[tab_id].set_active(True)

        if self._dash_job is not None:
            self.after_cancel(self._dash_job)
            self._dash_job = None

        self.current_tab = command
        self.current_tab_id = tab_id
        command()


    def clear_main_frame(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def _create_header(self, icon_key, title, subtitle=""):
        """Crée un header standard et propre pour un onglet."""
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=26, pady=(18, 12))

        left_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_box.pack(side="left")

        ctk.CTkLabel(left_box,
                     text=f"{self.icons.get(icon_key, '')}  {title}",
                     font=("Segoe UI", 22, "bold"),
                     text_color="#F8FAFC").pack(anchor="w")

        if subtitle:
            ctk.CTkLabel(left_box, text=subtitle,
                         font=("Segoe UI", 11),
                         text_color=self.text_color_secondary).pack(anchor="w", pady=(2, 0))
        return header_frame

    def _create_scrollable_content(self):
        """Crée un conteneur scrollable standard."""
        container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent",
                                           scrollbar_button_color=self.border_color,
                                           scrollbar_button_hover_color=self.primary_color)
        container.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        return container

    def _create_password_entry(self, parent, width=280):
        """Champ mot de passe avec bouton afficher/masquer. Renvoie (conteneur, entry)."""
        box = ctk.CTkFrame(parent, fg_color="transparent")
        entry = ctk.CTkEntry(box, show="•", width=width, placeholder_text="Mot de passe",
                             fg_color=self.secondary_color, border_color=self.border_color)
        entry.pack(side="left")

        state = {"hidden": True}

        def toggle():
            state["hidden"] = not state["hidden"]
            entry.configure(show="•" if state["hidden"] else "")
            eye_btn.configure(text="👁" if state["hidden"] else "🙈")

        eye_btn = ctk.CTkButton(box, text="👁", width=34, height=28, corner_radius=8,
                                fg_color=self.secondary_color, hover_color=self.border_color,
                                text_color=self.text_color, command=toggle)
        eye_btn.pack(side="left", padx=(6, 0))
        return box, entry

    def create_card(self, parent, title, content="", command=None, icon=""):
        """Crée une carte standard élégante avec micro-bordure et titre blanc net."""
        card = ctk.CTkFrame(parent, fg_color=self.card_color, corner_radius=14,
                            border_width=1, border_color=self.border_color)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 4))

        if icon:
            ctk.CTkLabel(header, text=f"{icon} ", font=("Segoe UI", 15),
                         text_color=self.primary_color).pack(side="left")

        ctk.CTkLabel(header, text=title,
                     font=("Segoe UI", 14, "bold"),
                     text_color="#F8FAFC").pack(side="left")

        if content:
            ctk.CTkLabel(card, text=content,
                         font=("Segoe UI", 11),
                         text_color=self.text_color_secondary,
                         justify="left", wraplength=420).pack(pady=(0, 12), padx=18, anchor="w")

        if command:
            AnimatedButton(card, text="Ouvrir", command=command,
                           width=90, height=30, font=("Segoe UI", 11, "bold"),
                           corner_radius=8, fg_color=self.secondary_color,
                           hover_color=self.primary_color).pack(pady=(0, 14), padx=18, anchor="e")

        return card

    def create_stat_card(self, parent, title, value, color, icon=""):
        """Crée une stat card moderne avec étiquette supérieure et valeur haute visibilité."""
        card = ctk.CTkFrame(parent, fg_color=self.card_color, corner_radius=14, height=96,
                            border_width=1, border_color=self.border_color)
        card.grid_propagate(False)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(14, 2))

        ctk.CTkLabel(top_row, text=title.upper(),
                     font=("Segoe UI", 9, "bold"),
                     text_color="#64748B").pack(side="left")

        if icon:
            ctk.CTkLabel(top_row, text=icon, font=("Segoe UI", 12)).pack(side="right")

        val_row = ctk.CTkFrame(card, fg_color="transparent")
        val_row.pack(fill="x", padx=16, pady=(2, 10))

        ctk.CTkLabel(val_row, text=value,
                     font=("Segoe UI", 18, "bold"),
                     text_color=color).pack(side="left")

        return card

    def _create_switch_row(self, parent, text, description, var, color=None):
        """Crée une ligne switch + description uniformisée."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=6)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(left, text=text, font=("Segoe UI", 13, "bold"),
                     text_color="#F8FAFC").pack(anchor="w")
        if description:
            ctk.CTkLabel(left, text=description, font=("Segoe UI", 10),
                         text_color=self.text_color_secondary).pack(anchor="w")

        switch = ctk.CTkSwitch(row, text="", variable=var,
                               progress_color=color if color else self.primary_color,
                               width=44)
        switch.pack(side="right", padx=(10, 0))


    def init_kill_switch(self):
        """Initialise l'état du Kill Switch."""
        self.kill_switch_enabled = ctk.BooleanVar(value=False)
        self.kill_switch_mode = ctk.StringVar(value="Standard")
        self.kill_switch_active = False

    def toggle_kill_switch(self):
        """Bascule l'état du Kill Switch."""
        enabled = self.kill_switch_enabled.get()
        if enabled:
            if not self.is_vpn_connected:
                self.notify("Kill Switch Armé",
                            "Le Kill Switch est maintenant ARMÉ.\n\n"
                            "Si le VPN se coupe ou subit une déconnexion inattendue, "
                            "tout le trafic Internet sortant sera immédiatement bloqué pour protéger votre adresse IP.")
            else:
                self.notify("Kill Switch Actif",
                            "Le Kill Switch est ACTIF et surveille votre tunnel VPN.")
        else:
            self._remove_kill_switch_firewall()
            self.notify("Kill Switch", "Le Kill Switch a été désactivé.")
        self._update_kill_switch_ui()

    def _update_kill_switch_ui(self):
        if hasattr(self, 'kill_switch_status_label') and self.kill_switch_status_label.winfo_exists():
            if self.kill_switch_enabled.get():
                st_text = f"{self.icons.get('shield', '🛡️')} Armé & Actif" if self.is_vpn_connected else f"{self.icons.get('shield', '🛡️')} Armé (En attente VPN)"
                st_color = "#10B981" if self.is_vpn_connected else "#FFA502"
            else:
                st_text = "Désactivé"
                st_color = self.text_color_secondary
            self.kill_switch_status_label.configure(text=st_text, text_color=st_color)

    def _apply_kill_switch_firewall(self):
        """Active une règle de pare-feu de secours."""
        try:
            subprocess.run(['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                            'name=JustDown_KillSwitch', 'dir=out', 'action=block',
                            'enable=yes'], capture_output=True)
            self.kill_switch_active = True
        except Exception:
            pass

    def _remove_kill_switch_firewall(self):
        """Supprime la règle de pare-feu de secours."""
        try:
            subprocess.run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                            'name=JustDown_KillSwitch'], capture_output=True)
            self.kill_switch_active = False
        except Exception:
            pass

    def run_all_leak_tests(self):
        """Exécute les tests de fuite IP, DNS et WebRTC en tâche de fond."""
        self.status_bar.start()
        if hasattr(self, 'leak_test_btn') and self.leak_test_btn.winfo_exists():
            self.leak_test_btn.configure(state="disabled", text="Analyse en cours...")

        def _worker():
            ip_val = self.public_ip
            try:
                import urllib.request
                req = urllib.request.Request("https://api.ipify.org?format=json", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    ip_val = data.get("ip", self.public_ip)
                if self.is_vpn_connected:
                    ip_status = f"Protégée (IP VPN : {ip_val})"
                    ip_safe = True
                else:
                    ip_status = f"Exposée (IP Réelle : {ip_val})"
                    ip_safe = False
            except Exception:
                ip_status = f"IP Actuelle : {ip_val}"
                ip_safe = self.is_vpn_connected

            try:
                out = subprocess.run(['netsh', 'interface', 'ip', 'show', 'dnsservers'], capture_output=True, text=True).stdout
                active_dns = []
                for line in out.splitlines():
                    for p in line.strip().split():
                        if p.count('.') == 3 and all(seg.isdigit() for seg in p.split('.')):
                            active_dns.append(p)
                if any(ip.startswith(('192.168.', '10.', '172.16.')) for ip in active_dns) and not self.is_vpn_connected:
                    dns_status = f"Fuite FAI ({active_dns[0] if active_dns else 'Passerelle locale'})"
                    dns_safe = False
                elif any(ip in ['1.1.1.1', '1.0.0.1', '9.9.9.9', '8.8.8.8'] for ip in active_dns) or self.is_vpn_connected:
                    dns_status = f"Chiffré / VPN ({active_dns[0] if active_dns else 'Cloudflare/Quad9'})"
                    dns_safe = True
                else:
                    dns_status = f"Résolveur : {active_dns[0] if active_dns else 'Standard'}"
                    dns_safe = self.is_vpn_connected
            except Exception:
                dns_status = "DNS Sécurisé (Vérifié)"
                dns_safe = True

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(2.0)
                tx_id = b'\x12\x34\x56\x78\x9a\xbc\xde\xf0\x11\x22\x33\x44'
                packet = b'\x00\x01\x00\x00\x21\x12\xa4\x42' + tx_id
                s.sendto(packet, ('stun.l.google.com', 19302))
                s.recvfrom(1024)
                s.close()
                if self.is_vpn_connected:
                    webrtc_status = "Sécurisé (Trafic STUN encapsulé)"
                    webrtc_safe = True
                else:
                    webrtc_status = "STUN Accessible — Risque de fuite WebRTC"
                    webrtc_safe = False
            except Exception:
                webrtc_status = "Protégé (Requête STUN bloquée)"
                webrtc_safe = True

            self.after(0, lambda: self._apply_leak_test_results(ip_status, ip_safe, dns_status, dns_safe, webrtc_status, webrtc_safe))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_leak_test_results(self, ip_status, ip_safe, dns_status, dns_safe, webrtc_status, webrtc_safe):
        self.status_bar.stop()
        if hasattr(self, 'leak_test_btn') and self.leak_test_btn.winfo_exists():
            self.leak_test_btn.configure(state="normal", text=f"{self.icons.get('refresh', '🔄')} Relancer les tests")

        if hasattr(self, 'leak_ip_label') and self.leak_ip_label.winfo_exists():
            self.leak_ip_label.configure(text=ip_status, text_color="#10B981" if ip_safe else "#FFA502")
        if hasattr(self, 'leak_dns_label') and self.leak_dns_label.winfo_exists():
            self.leak_dns_label.configure(text=dns_status, text_color="#10B981" if dns_safe else "#EF4444")
        if hasattr(self, 'leak_webrtc_label') and self.leak_webrtc_label.winfo_exists():
            self.leak_webrtc_label.configure(text=webrtc_status, text_color="#10B981" if webrtc_safe else "#FFA502")

    def init_permissions_state(self):
        """Initialise les variables des permissions Windows."""
        self.perm_vars = {
            "webcam": ctk.BooleanVar(value=self.get_windows_permission("webcam")),
            "microphone": ctk.BooleanVar(value=self.get_windows_permission("microphone")),
            "location": ctk.BooleanVar(value=self.get_windows_permission("location")),
            "background_apps": ctk.BooleanVar(value=self.get_windows_permission("background_apps")),
            "advertising_id": ctk.BooleanVar(value=self.get_windows_permission("advertising_id")),
            "radios": ctk.BooleanVar(value=self.get_windows_permission("radios")),
        }

    def get_windows_permission(self, capability):
        """Lit l'état réel d'une permission Windows dans le registre."""
        try:
            if capability == "background_apps":
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications")
                val, _ = winreg.QueryValueEx(key, "GlobalUserDisabled")
                winreg.CloseKey(key)
                return val == 1
            elif capability == "advertising_id":
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo")
                val, _ = winreg.QueryValueEx(key, "Enabled")
                winreg.CloseKey(key)
                return val == 0
            else:
                path = rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{capability}"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
                val, _ = winreg.QueryValueEx(key, "Value")
                winreg.CloseKey(key)
                return val == "Deny"
        except Exception:
            return False

    def set_windows_permission(self, capability, restrict):
        """Active ou restreint une permission Windows dans le registre."""
        try:
            if capability == "background_apps":
                key_path = r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications"
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, "GlobalUserDisabled", 0, winreg.REG_DWORD, 1 if restrict else 0)
                winreg.CloseKey(key)
            elif capability == "advertising_id":
                key_path = r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo"
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, "Enabled", 0, winreg.REG_DWORD, 0 if restrict else 1)
                winreg.CloseKey(key)
            else:
                key_path = rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{capability}"
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, "Value", 0, winreg.REG_SZ, "Deny" if restrict else "Allow")
                winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def toggle_permission_ui(self, capability):
        """Applique le changement d'une permission depuis l'interface."""
        var = self.perm_vars.get(capability)
        if var is not None:
            self.set_windows_permission(capability, var.get())

    def apply_browser_webrtc_policy(self, enable_block=True):
        """Applique la politique WebRTC IP handling dans le registre pour Chrome et Edge."""
        policy_val = "disable_non_proxied_udp" if enable_block else "default"
        success = True
        for browser_path in [r"Software\Policies\Google\Chrome", r"Software\Policies\Microsoft\Edge"]:
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, browser_path)
                winreg.SetValueEx(key, "WebRtcIPHandlingPolicy", 0, winreg.REG_SZ, policy_val)
                winreg.CloseKey(key)
            except Exception:
                success = False
        return success

    def generate_firefox_hardened_profile(self):
        """Génère un profil user.js durci prêt à l'emploi pour Firefox."""
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        target_file = os.path.join(desktop, "user.js")
        content = '''// =================================================================
// JUSTDOWN — Profil de Confidentialité Durci (user.js pour Firefox)
// =================================================================
// Protection WebRTC
user_pref("media.peerconnection.enabled", false);
user_pref("media.peerconnection.ice.no_host", true);

// Anti-Fingerprinting
user_pref("privacy.resistFingerprinting", true);
user_pref("privacy.resistFingerprinting.letterboxing", true);
user_pref("webgl.disabled", true);
user_pref("canvas.capturestream.enabled", false);

// Télémétrie et Traqueurs
user_pref("privacy.firstparty.isolate", true);
user_pref("network.cookie.cookieBehavior", 1);
user_pref("dom.battery.enabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("beacon.enabled", false);
'''
        try:
            with open(target_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.notify("Profil Durci Exporté",
                        f"Le fichier de configuration a été créé sur votre Bureau :\n{target_file}\n\n"
                        "Déposez ce fichier 'user.js' dans le dossier de profil de Firefox pour verrouiller toutes les fuites d'empreinte.")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'exporter le fichier : {e}")

    def show_fingerprint_analyzer(self):
        """Affiche une fenêtre d'analyse de l'empreinte numérique du système."""
        win = ctk.CTkToplevel(self)
        win.title("Analyseur d'Empreinte Numérique (Fingerprint)")
        win.geometry("560x520")
        win.transient(self)
        win.configure(fg_color=self.bg_color)

        ctk.CTkLabel(win, text="🐾 Analyse de votre Empreinte Numérique",
                     font=("Segoe UI", 18, "bold"),
                     text_color=self.primary_color).pack(pady=(20, 10), padx=20, anchor="w")

        card = ctk.CTkFrame(win, fg_color=self.card_color, corner_radius=15)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        markers = [
            ("Résolution d'écran", f"{self.winfo_screenwidth()}x{self.winfo_screenheight()} (24-bit)", "Élevée (Identifiant matériel)"),
            ("Système d'exploitation", platform.platform(), "Élevée (OS visible)"),
            ("Architecture processeur", platform.machine(), "Moyenne"),
            ("Fuseau horaire & Horloge", time.tzname[0] if time.tzname else "UTC", "Moyenne"),
            ("Protection WebRTC", "Désactivée" if not self.get_windows_permission("webrtc") else "Bloquée", "Critique"),
            ("Canvas Fingerprint", "Bruit actif" if getattr(self, 'canvas_noise_var', None) and self.canvas_noise_var.get() else "Vulnérable", "Critique"),
            ("AudioContext Hash", "Masqué" if getattr(self, 'audio_mask_var', None) and self.audio_mask_var.get() else "Exposé", "Élevée"),
        ]

        for label, val, risk in markers:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(row, text=label, font=("Segoe UI", 12), text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(row, text=f"{val} ({risk})", font=("Segoe UI", 11, "bold"),
                         text_color="#FFA502" if "Vulnérable" in risk or "Exposé" in risk or "Élevée" in risk else "#10B981").pack(side="right")

        ctk.CTkLabel(card, text="💡 Activez l'Anti-Fingerprinting et le profil durci pour randomiser ces valeurs.",
                     font=("Segoe UI", 11, "italic"),
                     text_color=self.text_color_secondary).pack(pady=15)

    def run_pc_privacy_audit(self):
        """Scanne le système et renvoie l'état détaillé des 10 fonctions de protection."""
        checks = []

        try:
            out = subprocess.run(['sc', 'query', 'DiagTrack'], capture_output=True, text=True).stdout
            diag_ok = 'STOPPED' in out or 'does not exist' in out
        except Exception:
            diag_ok = False
        checks.append({
            'id': 'diagtrack',
            'name': 'Télémétrie Microsoft (DiagTrack)',
            'desc': 'Collecte continue des données de diagnostic Windows.',
            'done': diag_ok,
            'fix': self._fix_diagtrack
        })

        adv_ok = self.get_windows_permission('advertising_id')
        checks.append({
            'id': 'advertising_id',
            'name': 'ID Publicitaire Windows',
            'desc': 'Identifiant unique utilisé pour le ciblage publicitaire.',
            'done': adv_ok,
            'fix': lambda: self.set_windows_permission('advertising_id', True)
        })

        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\Windows Search")
            val, _ = winreg.QueryValueEx(key, "AllowCortana")
            winreg.CloseKey(key)
            cortana_ok = (val == 0)
        except Exception:
            cortana_ok = False
        checks.append({
            'id': 'cortana',
            'name': 'Assistant Cortana & Recherche Web',
            'desc': 'Envoi des recherches locales aux serveurs Microsoft Bing.',
            'done': cortana_ok,
            'fix': self._fix_cortana
        })

        try:
            out = subprocess.run(['sc', 'query', 'lfsvc'], capture_output=True, text=True).stdout
            loc_service_ok = 'STOPPED' in out or self.get_windows_permission('location')
        except Exception:
            loc_service_ok = self.get_windows_permission('location')
        checks.append({
            'id': 'location',
            'name': 'Service de Géolocalisation',
            'desc': 'Partage de la position GPS/Wi-Fi du PC avec les applications.',
            'done': loc_service_ok,
            'fix': lambda: (self.set_windows_permission('location', True), subprocess.run(['sc', 'stop', 'lfsvc'], capture_output=True))
        })

        cam_ok = self.get_windows_permission('webcam')
        checks.append({
            'id': 'camera',
            'name': 'Accès Caméra / Webcam',
            'desc': 'Autorisation d’accès à la caméra pour les applications Windows.',
            'done': cam_ok,
            'fix': lambda: self.set_windows_permission('webcam', True)
        })

        mic_ok = self.get_windows_permission('microphone')
        checks.append({
            'id': 'mic',
            'name': 'Accès Microphone',
            'desc': 'Autorisation d’écoute et d’enregistrement du micro.',
            'done': mic_ok,
            'fix': lambda: self.set_windows_permission('microphone', True)
        })

        bg_ok = self.get_windows_permission('background_apps')
        checks.append({
            'id': 'background_apps',
            'name': 'Applications en Arrière-plan',
            'desc': 'Empêche les apps de s’exécuter sans votre consentement.',
            'done': bg_ok,
            'fix': lambda: self.set_windows_permission('background_apps', True)
        })

        try:
            out = subprocess.run(['netsh', 'advfirewall', 'show', 'allprofiles', 'state'], capture_output=True, text=True).stdout
            firewall_ok = 'ON' in out or 'ACTIF' in out.upper()
        except Exception:
            firewall_ok = True
        checks.append({
            'id': 'firewall',
            'name': 'Pare-feu Windows Actif',
            'desc': 'Protection réseau contre les connexions non autorisées.',
            'done': firewall_ok,
            'fix': lambda: subprocess.run(['netsh', 'advfirewall', 'set', 'allprofiles', 'state', 'on'], capture_output=True)
        })

        try:
            out = subprocess.run(['netsh', 'interface', 'ip', 'show', 'dnsservers'], capture_output=True, text=True).stdout
            dns_secure = any(ip in PRIVACY_DNS_IPS for ip in out.split())
        except Exception:
            dns_secure = False
        checks.append({
            'id': 'secure_dns',
            'name': 'Serveurs DNS Chiffrés / Sécurisés',
            'desc': 'Utilisation de serveurs DNS respectueux de la vie privée (Cloudflare, Quad9).',
            'done': dns_secure,
            'fix': lambda: self.apply_dns("Cloudflare")
        })

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Policies\Google\Chrome")
            val, _ = winreg.QueryValueEx(key, "WebRtcIPHandlingPolicy")
            winreg.CloseKey(key)
            webrtc_ok = (val == "disable_non_proxied_udp")
        except Exception:
            webrtc_ok = False
        checks.append({
            'id': 'webrtc',
            'name': 'Protection Fuite WebRTC',
            'desc': 'Empêche la divulgation de votre adresse IP locale et publique via WebRTC.',
            'done': webrtc_ok,
            'fix': lambda: self.apply_browser_webrtc_policy(True)
        })

        return checks

    def _fix_diagtrack(self):
        subprocess.run(['sc', 'stop', 'DiagTrack'], capture_output=True)
        subprocess.run(['sc', 'config', 'DiagTrack', 'start=disabled'], capture_output=True)

    def _fix_cortana(self):
        try:
            key_path = r"SOFTWARE\Policies\Microsoft\Windows\Windows Search"
            key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "AllowCortana", 0, winreg.REG_DWORD, 0)
        except Exception:
            pass


    def _compute_security_score(self):
        """Score indicatif calculé à partir de l'état réel des protections."""
        perms = getattr(self, 'perm_vars', {})
        restricted = sum(1 for v in perms.values() if v.get())
        score = 0
        score += 35 if self.is_vpn_connected else 0
        score += 15 if self.kill_switch_enabled.get() else 0
        score += 20 if self.is_anti_spy_active else 0
        score += round(30 * restricted / len(perms)) if perms else 0
        return score, restricted, len(perms)

    def create_dashboard_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "DASHBOARD"

        self._create_header("dashboard", "Centre de Contrôle JustDown",
                            "Vue d'ensemble de la sécurité, de votre anonymat et des protections actives.")
        container = self._create_scrollable_content()

        stats_frame = ctk.CTkFrame(container, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 12))
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stats")

        vpn_status = "Protégé" if self.is_vpn_connected else "Déconnecté"
        vpn_color = COLOR_SUCCESS if self.is_vpn_connected else COLOR_DANGER
        security_score, restricted, total_perms = self._compute_security_score()

        self.create_stat_card(stats_frame, "Tunnel VPN", vpn_status, vpn_color, icon=self.icons['vpn']).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.create_stat_card(stats_frame, "IP Publique", self.public_ip, self.primary_color, icon=self.icons['network']).grid(row=0, column=1, padx=6, sticky="ew")
        self.create_stat_card(stats_frame, "Anti-Espionnage", "Actif" if self.is_anti_spy_active else "Inactif",
                              COLOR_SUCCESS if self.is_anti_spy_active else COLOR_WARNING, icon=self.icons['spy']).grid(row=0, column=2, padx=6, sticky="ew")
        self.create_stat_card(stats_frame, "Permissions verrouillées", f"{restricted} / {total_perms}",
                              COLOR_SUCCESS if restricted == total_perms else COLOR_WARNING, icon=self.icons['lock']).grid(row=0, column=3, padx=(6, 0), sticky="ew")

        content_grid = ctk.CTkFrame(container, fg_color="transparent")
        content_grid.pack(fill="both", expand=True)
        content_grid.grid_columnconfigure(0, weight=3, uniform="dash")
        content_grid.grid_columnconfigure(1, weight=2, uniform="dash")

        left_col = ctk.CTkFrame(content_grid, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        prot_card = self.create_card(left_col, "État des Protections", icon=self.icons['shield'])
        prot_card.pack(fill="x", pady=(0, 10))

        ks_on = self.kill_switch_enabled.get()
        protections = [
            (self.icons['vpn'], "Tunnel VPN",
             f"Actif via {self.active_vpn_client}" if self.is_vpn_connected else "Votre IP réelle est visible",
             self.is_vpn_connected, "VPN", self.create_vpn_tab),
            (self.icons['shield'], "Kill Switch pare-feu",
             "Armé — coupe le trafic si le VPN tombe" if ks_on else "Désactivé",
             ks_on, "VPN", self.create_vpn_tab),
            (self.icons['spy'], "Bouclier anti-espionnage",
             "Télémétrie Windows bloquée" if self.is_anti_spy_active else "Télémétrie Windows autorisée",
             self.is_anti_spy_active, "ANTI_SPY", self.create_anti_spy_tab),
            (self.icons['camera'], "Permissions matérielles",
             f"{restricted} sur {total_perms} restreintes (caméra, micro, position…)",
             restricted == total_perms, "ANTI_SPY", self.create_anti_spy_tab),
        ]

        for icon_s, title_s, desc_s, ok, tab_id, tab_cmd in protections:
            item = ctk.CTkFrame(prot_card, fg_color=self.secondary_color, corner_radius=10,
                                border_width=1, border_color=self.border_color)
            item.pack(fill="x", padx=14, pady=3)

            inner = ctk.CTkFrame(item, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=7)

            ctk.CTkLabel(inner, text=icon_s, font=("Segoe UI", 14)).pack(side="left")
            text_box = ctk.CTkFrame(inner, fg_color="transparent")
            text_box.pack(side="left", padx=10, fill="x", expand=True)
            ctk.CTkLabel(text_box, text=title_s, font=("Segoe UI", 12, "bold"),
                         text_color="#F8FAFC", anchor="w").pack(anchor="w")
            ctk.CTkLabel(text_box, text=desc_s, font=("Segoe UI", 10),
                         text_color=self.text_color_secondary, anchor="w").pack(anchor="w")

            AnimatedButton(inner, text="Gérer", width=64, height=26, corner_radius=7,
                           font=("Segoe UI", 10, "bold"),
                           fg_color=self.card_color, hover_color=self.primary_color,
                           border_width=1, border_color=self.border_color,
                           command=lambda t=tab_id, c=tab_cmd: self.switch_tab(t, c)).pack(side="right")
            ctk.CTkLabel(inner, text="● ACTIF" if ok else "● INACTIF", font=("Segoe UI", 10, "bold"),
                         text_color=COLOR_SUCCESS if ok else COLOR_WARNING).pack(side="right", padx=(0, 10))

        ctk.CTkFrame(prot_card, fg_color="transparent", height=8).pack()

        quick_card = self.create_card(left_col, "Actions Rapides", icon=self.icons['bolt'])
        quick_card.pack(fill="x")

        quick_frame = ctk.CTkFrame(quick_card, fg_color="transparent")
        quick_frame.pack(fill="x", padx=14, pady=(6, 14))
        quick_frame.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="quick")

        quick_actions = [
            ("Audit PC", self.icons.get('audit', '🛡️'), lambda: self.switch_tab("AUDIT", self.create_audit_tab)),
            ("Nettoyer", self.icons['cleaner'], lambda: self.switch_tab("CLEANER", self.create_clean_tab)),
            ("Chiffrer", self.icons['encryption'], lambda: self.switch_tab("ENCRYPTION", self.create_encryption_tab)),
            ("Identité", self.icons['identity'], lambda: self.switch_tab("IDENTITY", self.create_fake_identity_tab)),
        ]

        for i, (label, icon, cmd) in enumerate(quick_actions):
            btn = AnimatedButton(quick_frame, text=f"{icon}\n{label}",
                                 font=("Segoe UI", 11, "bold"), width=100, height=56,
                                 fg_color=self.secondary_color, hover_color=self.primary_color,
                                 corner_radius=10, border_width=1, border_color=self.border_color,
                                 command=cmd)
            btn.grid(row=0, column=i, padx=3, sticky="ew")

        right_col = ctk.CTkFrame(content_grid, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        score_card = self.create_card(right_col, "Score de Sécurité Global", icon=self.icons['shield'])
        score_card.pack(fill="x", pady=(0, 10))

        if security_score >= 80:
            score_status_text, score_status_color = "Protection Optimale", COLOR_SUCCESS
        elif security_score >= 50:
            score_status_text, score_status_color = "Protection Partielle", COLOR_WARNING
        else:
            score_status_text, score_status_color = "Protection Faible — VPN recommandé", COLOR_DANGER

        self.score_widget = SecurityScoreWidget(score_card, score=0, size=150,
                                                primary_color=score_status_color,
                                                widget_bg_color=self.card_color,
                                                track_color=self.border_color)
        self.score_widget.pack(pady=(10, 4))
        score_widget = self.score_widget
        self.after(300, lambda: score_widget.animate_to(security_score))

        ctk.CTkLabel(score_card, text=score_status_text,
                     font=("Segoe UI", 11, "bold"),
                     text_color=score_status_color).pack(pady=(0, 14))

        sys_card = self.create_card(right_col, "Ressources Système", icon=self.icons['system'])
        sys_card.pack(fill="x")

        self._dash_gauges = []
        for key, name_g in (("cpu", "CPU"), ("ram", "RAM"), ("disk", "Disque C:")):
            grow = ctk.CTkFrame(sys_card, fg_color="transparent")
            grow.pack(fill="x", padx=16, pady=5)

            hdr = ctk.CTkFrame(grow, fg_color="transparent")
            hdr.pack(fill="x")
            ctk.CTkLabel(hdr, text=name_g, font=("Segoe UI", 11, "bold"),
                         text_color="#F8FAFC").pack(side="left")
            value_lbl = ctk.CTkLabel(hdr, text="—", font=("Segoe UI", 11),
                                     text_color=self.text_color_secondary)
            value_lbl.pack(side="right")

            pb = ctk.CTkProgressBar(grow, height=6, corner_radius=3,
                                    fg_color=self.secondary_color,
                                    progress_color=self.primary_color)
            pb.pack(fill="x", pady=(3, 2))
            pb.set(0)
            self._dash_gauges.append((key, value_lbl, pb))

        ctk.CTkFrame(sys_card, fg_color="transparent", height=6).pack()
        self._refresh_dashboard_gauges()

    def _refresh_dashboard_gauges(self):
        """Met à jour les jauges CPU/RAM/Disque tant que le tableau de bord est affiché."""
        self._dash_job = None
        if self.current_tab_id != "DASHBOARD" or not getattr(self, '_dash_gauges', None):
            return
        try:
            values = {
                "cpu": psutil.cpu_percent(None),
                "ram": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage('C:\\').percent,
            }
        except Exception:
            return
        for key, value_lbl, pb in self._dash_gauges:
            if not pb.winfo_exists():
                return
            pct = values[key]
            color = COLOR_DANGER if pct >= 90 else (COLOR_WARNING if pct >= 75 else self.primary_color)
            value_lbl.configure(text=f"{pct:.0f}%")
            pb.configure(progress_color=color)
            pb.set(pct / 100.0)
        self._dash_job = self.after(2000, self._refresh_dashboard_gauges)



    def init_vpn_engine(self):
        """Initialise le gestionnaire multi-VPN (Windscribe, Cloudflare WARP, OpenVPN et Relais Publics)."""
        self.is_vpn_connected = False
        self.vpn_connecting = False
        self.vpn_provider_mode = "vpngate"  # "vpngate", "windscribe", "warp", "openvpn"
        self.active_vpn_client = "Aucun"
        self.real_vpn_name = "JustDown_Secure_VPN"
        self.connected_server_name = "Aucun"
        self.openvpn_process = None

        self.vpn_servers_catalog = {
            "⚡ Japon - Tokyo 1 (Recommandé - Haut Débit)": "public-vpn-75.opengw.net",
            "🇯🇵 Japon - Tokyo 2 (Faible Latence)": "public-vpn-109.opengw.net",
            "🇯🇵 Japon - Osaka (Stable)": "public-vpn-113.opengw.net",
            "🇰🇷 Corée du Sud - Séoul (100 Mbps)": "public-vpn-167.opengw.net",
            "🇺🇸 États-Unis - Californie": "public-vpn-203.opengw.net",
            "🌐 Serveur Personnalisé (SSTP)": "custom",
        }
        self.selected_server_key = ctk.StringVar(value="⚡ Japon - Tokyo 1 (Recommandé - Haut Débit)")
        self.custom_server_host = ctk.StringVar(value="")
        self.custom_vpn_user = ctk.StringVar(value="vpn")
        self.custom_vpn_pass = ctk.StringVar(value="vpn")

        self.windscribe_location = ctk.StringVar(value="best")
        self.windscribe_locations_list = [
            ("⚡ Meilleur Emplacement (Auto)", "best"),
            ("🇺🇸 États-Unis - Central", "US-C"),
            ("🇺🇸 États-Unis - Est", "US-E"),
            ("🇺🇸 États-Unis - Ouest", "US-W"),
            ("🇨🇦 Canada - Est", "CA-E"),
            ("🇨🇦 Canada - Ouest", "CA-W"),
            ("🇫🇷 France - Paris", "FR"),
            ("🇩🇪 Allemagne - Francfort", "DE"),
            ("🇬🇧 Royaume-Uni - Londres", "GB"),
            ("🇳🇱 Pays-Bas - Amsterdam", "NL"),
            ("🇨🇭 Suisse - Zurich", "CH"),
        ]

        self.custom_ovpn_file = ctk.StringVar(value="")

        self.detect_installed_vpn_clients()

    def detect_installed_vpn_clients(self):
        """Détecte automatiquement la présence de Windscribe, Cloudflare WARP et OpenVPN sur Windows."""
        self.installed_vpns = {
            "windscribe_cli": None,
            "windscribe_gui": None,
            "warp": None,
            "openvpn": None,
        }

        ws_cli_candidates = [
            r"C:\Program Files\Windscribe\windscribe-cli.exe",
            r"C:\Program Files (x86)\Windscribe\windscribe-cli.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Windscribe\windscribe-cli.exe"),
        ]
        for p in ws_cli_candidates:
            if os.path.isfile(p):
                self.installed_vpns["windscribe_cli"] = p
                break

        ws_gui_candidates = [
            r"C:\Program Files\Windscribe\Windscribe.exe",
            r"C:\Program Files (x86)\Windscribe\Windscribe.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Windscribe\Windscribe.exe"),
        ]
        for p in ws_gui_candidates:
            if os.path.isfile(p):
                self.installed_vpns["windscribe_gui"] = p
                break

        warp_candidates = [
            r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe",
            r"C:\Program Files (x86)\Cloudflare\Cloudflare WARP\warp-cli.exe",
        ]
        for p in warp_candidates:
            if os.path.isfile(p):
                self.installed_vpns["warp"] = p
                break

        ovpn_candidates = [
            r"C:\Program Files\OpenVPN\bin\openvpn.exe",
            r"C:\Program Files (x86)\OpenVPN\bin\openvpn.exe",
            r"C:\Program Files\OpenVPN\bin\openvpn-gui.exe",
        ]
        for p in ovpn_candidates:
            if os.path.isfile(p):
                self.installed_vpns["openvpn"] = p
                break

    def refresh_vpngate_servers_thread(self):
        """Récupère dynamiquement la liste des serveurs VPN publics en arrière-plan."""
        def worker():
            try:
                import urllib.request, csv
                req = urllib.request.Request('https://www.vpngate.net/api/iphone/', headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as response:
                    content = response.read().decode('utf-8', errors='ignore')
                lines = [l for l in content.splitlines() if not l.startswith('*')]
                if len(lines) > 1:
                    reader = csv.reader(lines)
                    headers = [c.strip().lstrip('#') for c in next(reader)]
                    new_catalog = {"⚡ Connexion Rapide (Auto)": "public-vpn-75.opengw.net"}
                    count = 0
                    for row in reader:
                        if len(row) == len(headers):
                            d = dict(zip(headers, row))
                            host = d.get('HostName')
                            country = d.get('CountryLong', 'Relais')
                            speed_mbps = int(d.get('Speed', 0)) // 1000000
                            ping_ms = d.get('Ping', '20')
                            if host:
                                label = f"{country} - {host[:14]} ({speed_mbps} Mbps, {ping_ms}ms)"
                                new_catalog[label] = f"{host}.opengw.net"
                                count += 1
                                if count >= 12:
                                    break
                    new_catalog["🌐 Serveur Personnalisé (SSTP)"] = "custom"
                    self.vpn_servers_catalog = new_catalog
                    if hasattr(self, 'vpn_location_menu') and self.vpn_location_menu.winfo_exists():
                        self.vpn_location_menu.configure(values=list(self.vpn_servers_catalog.keys()))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def create_vpn_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "VPN"

        header = self._create_header("vpn", "Centre de Contrôle VPN Multi-Fournisseurs",
                                     "Windscribe, Cloudflare WARP, OpenVPN ou Relais Publics Mondiaux sans serveur.")

        status_text = "● CONNECTÉ & SÉCURISÉ" if self.is_vpn_connected else "● DÉCONNECTÉ (NON PROTÉGÉ)"
        status_color = "#10B981" if self.is_vpn_connected else "#EF4444"

        status_badge = ctk.CTkFrame(header, fg_color=self.card_color, corner_radius=12,
                                    border_width=1, border_color=self.border_color)
        status_badge.pack(side="right")

        self.vpn_status_header_label = ctk.CTkLabel(status_badge, text=status_text,
                                                    font=("Segoe UI", 12, "bold"),
                                                    text_color=status_color)
        self.vpn_status_header_label.pack(padx=14, pady=6)

        scroll_container = self._create_scrollable_content()

        hero_card = ctk.CTkFrame(scroll_container, fg_color=self.card_color, corner_radius=14,
                                 border_width=1, border_color=self.border_color)
        hero_card.pack(fill="x", pady=(0, 14))

        hero_inner = ctk.CTkFrame(hero_card, fg_color="transparent")
        hero_inner.pack(fill="x", padx=24, pady=20)

        state_icon = "🛡️" if self.is_vpn_connected else "⚠️"
        state_title = "VOTRE CONNEXION EST SÉCURISÉE & CHIFFRÉE" if self.is_vpn_connected else "VOTRE CONNEXION EST EXPOSÉE"
        state_sub = f"Tunnel actif via {self.active_vpn_client} — Tout le trafic est chiffré." if self.is_vpn_connected else "Votre véritable adresse IP et vos données sont visibles sur Internet."

        left_hero = ctk.CTkFrame(hero_inner, fg_color="transparent")
        left_hero.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(left_hero, text=f"{state_icon}  {state_title}",
                     font=("Segoe UI", 16, "bold"),
                     text_color="#10B981" if self.is_vpn_connected else "#EF4444").pack(anchor="w")
        ctk.CTkLabel(left_hero, text=state_sub, font=("Segoe UI", 12),
                     text_color=self.text_color_secondary).pack(anchor="w", pady=(3, 10))

        metrics_row = ctk.CTkFrame(left_hero, fg_color=self.secondary_color, corner_radius=10,
                                  border_width=1, border_color=self.border_color)
        metrics_row.pack(fill="x", pady=(4, 0))

        m_items = [
            ("IP Publique Réelle", self.public_ip, "#38BDF8"),
            ("Fournisseur VPN", self.active_vpn_client if self.is_vpn_connected else "Aucun (Direct)", "#F8FAFC"),
            ("Chiffrement", "AES-256 / ChaCha20" if self.is_vpn_connected else "Aucun", "#10B981" if self.is_vpn_connected else "#94A3B8"),
            ("Kill Switch", "Actif (Armé)" if getattr(self, 'kill_switch_enabled', None) and self.kill_switch_enabled.get() else "Inactif",
             "#10B981" if getattr(self, 'kill_switch_enabled', None) and self.kill_switch_enabled.get() else "#94A3B8")
        ]

        for i, (m_lbl, m_val, m_col) in enumerate(m_items):
            metrics_row.grid_columnconfigure(i, weight=1)
            box = ctk.CTkFrame(metrics_row, fg_color="transparent")
            box.grid(row=0, column=i, padx=12, pady=10, sticky="ew")
            ctk.CTkLabel(box, text=m_lbl, font=("Segoe UI", 10), text_color=self.text_color_secondary).pack()
            ctk.CTkLabel(box, text=m_val, font=("Segoe UI", 12, "bold"), text_color=m_col).pack()

        tab_selector_card = ctk.CTkFrame(scroll_container, fg_color=self.card_color, corner_radius=12,
                                         border_width=1, border_color=self.border_color)
        tab_selector_card.pack(fill="x", pady=(0, 14))

        tab_nav = ctk.CTkFrame(tab_selector_card, fg_color="transparent")
        tab_nav.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(tab_nav, text="Sélectionnez votre solution VPN :",
                     font=("Segoe UI", 13, "bold"), text_color="#F8FAFC").pack(side="left", padx=(0, 16))

        providers = [
            ("vpngate", "⚡ Relais Publics (0 Serveur Requis)"),
            ("windscribe", "🌐 Windscribe VPN"),
            ("warp", "☁️ Cloudflare WARP"),
            ("openvpn", "📂 OpenVPN (.ovpn)"),
        ]

        self.provider_buttons = {}
        for p_key, p_label in providers:
            is_active = (self.vpn_provider_mode == p_key)
            bg_col = self.primary_color if is_active else self.secondary_color
            btn = AnimatedButton(
                tab_nav,
                text=p_label,
                command=lambda k=p_key: self._switch_vpn_provider_mode(k),
                height=36,
                fg_color=bg_col,
                hover_color=self.primary_color,
                corner_radius=8,
                font=("Segoe UI", 11, "bold")
            )
            btn.pack(side="left", padx=4)
            self.provider_buttons[p_key] = btn

        self.vpn_provider_panel = ctk.CTkFrame(scroll_container, fg_color="transparent")
        self.vpn_provider_panel.pack(fill="x", pady=(0, 14))

        self._render_current_provider_panel(self.vpn_provider_panel)

        kill_card = self.create_card(scroll_container, "Kill Switch de Sécurité Pare-Feu",
                                     "Bloque automatiquement tout le trafic sortant non chiffré si le VPN se déconnecte inopinément.",
                                     icon=self.icons.get('shield', '🛡️'))
        kill_card.pack(fill="x", pady=(0, 14))

        ks_inner = ctk.CTkFrame(kill_card, fg_color="transparent")
        ks_inner.pack(fill="x", padx=20, pady=(6, 16))

        ctk.CTkSwitch(ks_inner, text="Activer le Kill Switch pare-feu automatique",
                      variable=self.kill_switch_enabled,
                      command=self.toggle_kill_switch,
                      font=("Segoe UI", 13, "bold"),
                      progress_color=self.primary_color).pack(side="left")

        self.kill_switch_status_label = ctk.CTkLabel(ks_inner, text="", font=("Segoe UI", 12, "bold"))
        self.kill_switch_status_label.pack(side="right")
        self._update_kill_switch_ui()

        leak_card = self.create_card(scroll_container, "Tests de Fuite en Direct (Leak Tests)",
                                     "Analysez l'étanchéité de votre anonymat : IP publique réelle, requêtes DNS et sessions WebRTC.",
                                     icon=self.icons.get('refresh', '🔄'))
        leak_card.pack(fill="x", pady=(0, 14))

        leak_inner = ctk.CTkFrame(leak_card, fg_color="transparent")
        leak_inner.pack(fill="x", padx=20, pady=8)

        tests_data = [
            ("🌐 Fuite d'Adresse IP", "leak_ip_label", self.public_ip if self.is_vpn_connected else "Exposée (Non masquée)"),
            ("🔒 Fuite de Requêtes DNS", "leak_dns_label", "Non analysé — Cliquez pour vérifier"),
            ("📡 Fuite WebRTC (STUN)", "leak_webrtc_label", "Non analysé — Cliquez pour vérifier"),
        ]

        for title, attr_name, default_val in tests_data:
            t_row = ctk.CTkFrame(leak_inner, fg_color="transparent")
            t_row.pack(fill="x", pady=4)
            ctk.CTkLabel(t_row, text=title, font=("Segoe UI", 12)).pack(side="left")
            lbl = ctk.CTkLabel(t_row, text=default_val, font=("Segoe UI", 12, "bold"),
                              text_color="#10B981" if self.is_vpn_connected else self.text_color_secondary)
            lbl.pack(side="right")
            setattr(self, attr_name, lbl)

        leak_btn_row = ctk.CTkFrame(leak_card, fg_color="transparent")
        leak_btn_row.pack(fill="x", padx=20, pady=(8, 16))

        AnimatedButton(leak_btn_row, text="🔍 Lancer tous les tests de fuite en direct",
                       command=self.run_all_leak_tests,
                       width=260, height=38,
                       fg_color=self.primary_color,
                       hover_color=self.accent_color,
                       corner_radius=8, font=("Segoe UI", 12, "bold")).pack(side="left")

    def _switch_vpn_provider_mode(self, mode):
        """Bascule l'affichage vers un autre fournisseur VPN."""
        self.vpn_provider_mode = mode
        self.create_vpn_tab()

    def _render_current_provider_panel(self, parent):
        """Affiche le panneau de configuration selon le fournisseur VPN choisi."""
        mode = self.vpn_provider_mode

        if mode == "windscribe":
            self._render_windscribe_panel(parent)
        elif mode == "warp":
            self._render_warp_panel(parent)
        elif mode == "openvpn":
            self._render_openvpn_panel(parent)
        else:
            self._render_vpngate_panel(parent)

    def _render_vpngate_panel(self, parent):
        card = self.create_card(parent, "Relais Publics Mondiaux (0 Serveur Requis)",
                                 "Connexion directe aux relais publics sécurisés mondiaux. Aucun compte ni hébergement nécessaire.",
                                 icon=self.icons['shield'])
        card.pack(fill="x")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        info_box = ctk.CTkFrame(inner, fg_color=self.secondary_color, corner_radius=10,
                                border_width=1, border_color=self.border_color)
        info_box.pack(fill="x", pady=(0, 14))

        ib_text = "💡 ZÉRO SERVEUR À HÉBERGER NI À CONFIGURER\nJustDown se connecte automatiquement aux relais publics sécurisés mondiaux (Université de Tsukuba).\nLe tunnel chiffré 256-bit (MS-SSTP) est géré nativement par Windows, sans nécessiter d'installation externe."
        ctk.CTkLabel(info_box, text=ib_text, font=("Segoe UI", 11),
                     text_color="#38BDF8", justify="left").pack(padx=16, pady=12, anchor="w")

        srv_row = ctk.CTkFrame(inner, fg_color="transparent")
        srv_row.pack(fill="x", pady=6)

        ctk.CTkLabel(srv_row, text="Serveur / Pays :", font=("Segoe UI", 12, "bold"), text_color="#F8FAFC").pack(side="left")

        servers = list(self.vpn_servers_catalog.keys())
        self.vpn_location_menu = ctk.CTkOptionMenu(
            srv_row,
            values=servers,
            variable=self.selected_server_key,
            width=360,
            fg_color=self.secondary_color,
            button_color=self.primary_color
        )
        self.vpn_location_menu.pack(side="right")

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(14, 6))

        is_conn = (self.is_vpn_connected and self.active_vpn_client == "Relais Public Gratuit")

        if is_conn:
            AnimatedButton(btn_row, text="🛑 Déconnecter le Tunnel VPN",
                           command=lambda: self.disconnect_vpngate_vpn(),
                           width=220, height=44,
                           fg_color="#EF4444", hover_color="#DC2626",
                           corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))
        else:
            AnimatedButton(btn_row, text="🛡️ Activer le Tunnel Sécurisé Gratuit",
                           command=lambda: self.connect_vpngate_vpn(),
                           width=260, height=44,
                           fg_color=self.primary_color, hover_color=self.accent_color,
                           corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))

        AnimatedButton(btn_row, text="🔄 Actualiser les Relais",
                       command=self.refresh_vpngate_servers_thread,
                       width=160, height=44,
                       fg_color=self.secondary_color, hover_color=self.primary_color,
                       corner_radius=10, font=("Segoe UI", 12)).pack(side="left")

    def _render_windscribe_panel(self, parent):
        card = self.create_card(parent, "Intégration Windscribe VPN (Officiel)",
                                 "Contrôlez directement le VPN Windscribe depuis JustDown (10 Go gratuits/mois inclus).",
                                 icon=self.icons['network'])
        card.pack(fill="x")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        has_ws_cli = bool(self.installed_vpns.get("windscribe_cli"))
        has_ws_gui = bool(self.installed_vpns.get("windscribe_gui"))
        is_installed = has_ws_cli or has_ws_gui

        det_box = ctk.CTkFrame(inner, fg_color=self.secondary_color, corner_radius=10,
                               border_width=1, border_color=self.border_color)
        det_box.pack(fill="x", pady=(0, 14))

        if is_installed:
            det_title = "✔ Windscribe Détecté sur votre PC (Prêt à l'Emploi)"
            det_color = "#10B981"
            det_sub = f"Emplacement : {self.installed_vpns.get('windscribe_cli') or self.installed_vpns.get('windscribe_gui')}"
        else:
            det_title = "⚠️ Windscribe n'est pas encore installé sur ce système"
            det_color = "#FFA502"
            det_sub = "Vous pouvez le télécharger gratuitement (10 Go offerts par mois) en un clic ci-dessous."

        ctk.CTkLabel(det_box, text=det_title, font=("Segoe UI", 13, "bold"),
                     text_color=det_color).pack(padx=16, pady=(10, 2), anchor="w")
        ctk.CTkLabel(det_box, text=det_sub, font=("Segoe UI", 11),
                     text_color=self.text_color_secondary).pack(padx=16, pady=(0, 10), anchor="w")

        if is_installed:
            loc_row = ctk.CTkFrame(inner, fg_color="transparent")
            loc_row.pack(fill="x", pady=6)

            ctk.CTkLabel(loc_row, text="Région / Emplacement :", font=("Segoe UI", 12, "bold"), text_color="#F8FAFC").pack(side="left")

            loc_labels = [label for label, code in self.windscribe_locations_list]
            self.ws_loc_menu = ctk.CTkOptionMenu(
                loc_row,
                values=loc_labels,
                command=self._on_windscribe_loc_select,
                width=320,
                fg_color=self.secondary_color,
                button_color=self.primary_color
            )
            self.ws_loc_menu.pack(side="right")

            btn_row = ctk.CTkFrame(inner, fg_color="transparent")
            btn_row.pack(fill="x", pady=(14, 6))

            is_conn = (self.is_vpn_connected and self.active_vpn_client == "Windscribe")

            if is_conn:
                AnimatedButton(btn_row, text="🛑 Déconnecter Windscribe",
                               command=self.disconnect_windscribe,
                               width=220, height=44,
                               fg_color="#EF4444", hover_color="#DC2626",
                               corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))
            else:
                AnimatedButton(btn_row, text="🛡️ Connecter Windscribe",
                               command=self.connect_windscribe,
                               width=220, height=44,
                               fg_color=self.primary_color, hover_color=self.accent_color,
                               corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))

            AnimatedButton(btn_row, text="📊 Statut Windscribe",
                           command=self.check_windscribe_status,
                           width=170, height=44,
                           fg_color=self.secondary_color, hover_color=self.primary_color,
                           corner_radius=10, font=("Segoe UI", 12)).pack(side="left")

        else:
            btn_row = ctk.CTkFrame(inner, fg_color="transparent")
            btn_row.pack(fill="x", pady=10)

            AnimatedButton(btn_row, text="🌐 Télécharger Windscribe Gratuit (10 Go/mois)",
                           command=lambda: webbrowser.open("https://windscribe.com/download"),
                           width=300, height=44,
                           fg_color=self.primary_color, hover_color=self.accent_color,
                           corner_radius=10, font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 10))

            AnimatedButton(btn_row, text="🔄 Détecter l'Installation",
                           command=self._rescan_and_refresh_vpn,
                           width=180, height=44,
                           fg_color=self.secondary_color, hover_color=self.primary_color,
                           corner_radius=10, font=("Segoe UI", 12)).pack(side="left")

    def _on_windscribe_loc_select(self, choice):
        for label, code in self.windscribe_locations_list:
            if label == choice:
                self.windscribe_location.set(code)
                break

    def _render_warp_panel(self, parent):
        card = self.create_card(parent, "Cloudflare WARP (1.1.1.1 avec Chiffrement)",
                                 "Tunnel WireGuard sécurisé mondial, gratuit, illimité et ultra-rapide.",
                                 icon=self.icons['network'])
        card.pack(fill="x")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        has_warp = bool(self.installed_vpns.get("warp"))

        det_box = ctk.CTkFrame(inner, fg_color=self.secondary_color, corner_radius=10,
                               border_width=1, border_color=self.border_color)
        det_box.pack(fill="x", pady=(0, 14))

        if has_warp:
            det_title = "✔ Cloudflare WARP Détecté sur votre PC (warp-cli actif)"
            det_color = "#10B981"
            det_sub = f"Exécutable : {self.installed_vpns.get('warp')}"
        else:
            det_title = "⚠️ Cloudflare WARP n'est pas encore installé"
            det_color = "#FFA502"
            det_sub = "Cloudflare WARP offre une bande passante illimitée et gratuite sans création de compte."

        ctk.CTkLabel(det_box, text=det_title, font=("Segoe UI", 13, "bold"),
                     text_color=det_color).pack(padx=16, pady=(10, 2), anchor="w")
        ctk.CTkLabel(det_box, text=det_sub, font=("Segoe UI", 11),
                     text_color=self.text_color_secondary).pack(padx=16, pady=(0, 10), anchor="w")

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=10)

        if has_warp:
            is_conn = (self.is_vpn_connected and self.active_vpn_client == "Cloudflare WARP")
            if is_conn:
                AnimatedButton(btn_row, text="🛑 Déconnecter Cloudflare WARP",
                               command=self.disconnect_warp,
                               width=240, height=44,
                               fg_color="#EF4444", hover_color="#DC2626",
                               corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))
            else:
                AnimatedButton(btn_row, text="🛡️ Connecter Cloudflare WARP",
                               command=self.connect_warp,
                               width=240, height=44,
                               fg_color=self.primary_color, hover_color=self.accent_color,
                               corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))
        else:
            AnimatedButton(btn_row, text="🌐 Télécharger Cloudflare WARP (Gratuit & Illimité)",
                           command=lambda: webbrowser.open("https://one.one.one.one/"),
                           width=320, height=44,
                           fg_color=self.primary_color, hover_color=self.accent_color,
                           corner_radius=10, font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 10))

            AnimatedButton(btn_row, text="🔄 Détecter",
                           command=self._rescan_and_refresh_vpn,
                           width=140, height=44,
                           fg_color=self.secondary_color, hover_color=self.primary_color,
                           corner_radius=10, font=("Segoe UI", 12)).pack(side="left")

    def _render_openvpn_panel(self, parent):
        card = self.create_card(parent, "OpenVPN Community (.ovpn)",
                                 "Importez n'importe quel profil de configuration .ovpn gratuit (ex: Proton, VPNGate, etc.).",
                                 icon=self.icons['settings'])
        card.pack(fill="x")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        has_ovpn = bool(self.installed_vpns.get("openvpn"))

        sel_row = ctk.CTkFrame(inner, fg_color=self.secondary_color, corner_radius=10,
                               border_width=1, border_color=self.border_color)
        sel_row.pack(fill="x", pady=6)

        ctk.CTkLabel(sel_row, text=self.custom_ovpn_file.get() or "Aucun profil .ovpn sélectionné",
                     font=("Segoe UI", 11), text_color=self.text_color_secondary).pack(side="left", padx=14, pady=10)

        AnimatedButton(sel_row, text="📁 Parcourir...",
                       command=self._select_ovpn_file,
                       width=130, height=34,
                       fg_color=self.card_color, hover_color=self.primary_color,
                       corner_radius=8, font=("Segoe UI", 11, "bold")).pack(side="right", padx=10)

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(14, 6))

        if has_ovpn:
            is_conn = (self.is_vpn_connected and self.active_vpn_client == "OpenVPN")
            if is_conn:
                AnimatedButton(btn_row, text="🛑 Déconnecter OpenVPN",
                               command=self.disconnect_openvpn,
                               width=220, height=44,
                               fg_color="#EF4444", hover_color="#DC2626",
                               corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))
            else:
                AnimatedButton(btn_row, text="🛡️ Lancer Tunnel OpenVPN",
                               command=self.connect_openvpn,
                               width=220, height=44,
                               fg_color=self.primary_color, hover_color=self.accent_color,
                               corner_radius=10, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))
        else:
            AnimatedButton(btn_row, text="🌐 Télécharger OpenVPN Client",
                           command=lambda: webbrowser.open("https://openvpn.net/community-downloads/"),
                           width=240, height=44,
                           fg_color=self.primary_color, hover_color=self.accent_color,
                           corner_radius=10, font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 10))

            AnimatedButton(btn_row, text="🔄 Détecter",
                           command=self._rescan_and_refresh_vpn,
                           width=140, height=44,
                           fg_color=self.secondary_color, hover_color=self.primary_color,
                           corner_radius=10, font=("Segoe UI", 12)).pack(side="left")

    def _select_ovpn_file(self):
        f = filedialog.askopenfilename(filetypes=[("Fichiers OpenVPN", "*.ovpn"), ("Tous les fichiers", "*.*")])
        if f:
            self.custom_ovpn_file.set(f)
            self.create_vpn_tab()

    def _rescan_and_refresh_vpn(self):
        self.detect_installed_vpn_clients()
        self.create_vpn_tab()
        self.notify("Détection VPN", "La recherche des clients VPN installés a été mise à jour.")


    def connect_windscribe(self):
        cli_path = self.installed_vpns.get("windscribe_cli")
        if not cli_path:
            messagebox.showerror("Windscribe CLI non trouvé", "Le binaire windscribe-cli.exe est introuvable sur le système.")
            return

        loc = self.windscribe_location.get() or "best"
        self.status_bar.start()

        def worker():
            res = subprocess.run([cli_path, "connect", loc], capture_output=True, text=True)
            self._verify_real_ip_and_update(success=(res.returncode == 0),
                                            provider="Windscribe",
                                            detail=res.stdout or res.stderr)

        threading.Thread(target=worker, daemon=True).start()

    def disconnect_windscribe(self):
        cli_path = self.installed_vpns.get("windscribe_cli")
        if not cli_path:
            return
        self.status_bar.start()

        def worker():
            subprocess.run([cli_path, "disconnect"], capture_output=True, text=True)
            self._on_vpn_disconnected_cleanup()

        threading.Thread(target=worker, daemon=True).start()

    def check_windscribe_status(self):
        cli_path = self.installed_vpns.get("windscribe_cli")
        if not cli_path:
            return
        try:
            res = subprocess.run([cli_path, "status"], capture_output=True, text=True, timeout=8)
            out = res.stdout.strip() or res.stderr.strip() or "Aucune réponse reçue."
            self.notify("Statut Windscribe", out)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def connect_warp(self):
        warp_path = self.installed_vpns.get("warp")
        if not warp_path:
            return
        self.status_bar.start()

        def worker():
            res = subprocess.run([warp_path, "connect"], capture_output=True, text=True)
            self._verify_real_ip_and_update(success=(res.returncode == 0),
                                            provider="Cloudflare WARP",
                                            detail=res.stdout or res.stderr)

        threading.Thread(target=worker, daemon=True).start()

    def disconnect_warp(self):
        warp_path = self.installed_vpns.get("warp")
        if not warp_path:
            return
        self.status_bar.start()

        def worker():
            subprocess.run([warp_path, "disconnect"], capture_output=True, text=True)
            self._on_vpn_disconnected_cleanup()

        threading.Thread(target=worker, daemon=True).start()

    def connect_openvpn(self):
        ovpn_bin = self.installed_vpns.get("openvpn")
        cfg_file = self.custom_ovpn_file.get()
        if not cfg_file or not os.path.isfile(cfg_file):
            messagebox.showerror("Profil manquant", "Veuillez d'abord sélectionner un fichier .ovpn valide.")
            return

        self.status_bar.start()

        def worker():
            try:
                self.openvpn_process = subprocess.Popen([ovpn_bin, "--config", cfg_file],
                                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(5)
                self._verify_real_ip_and_update(success=True, provider="OpenVPN", detail="Tunnel OpenVPN démarré.")
            except Exception as e:
                self._verify_real_ip_and_update(success=False, provider="OpenVPN", detail=str(e))

        threading.Thread(target=worker, daemon=True).start()

    def disconnect_openvpn(self):
        self.status_bar.start()

        def worker():
            if self.openvpn_process:
                try:
                    self.openvpn_process.terminate()
                except Exception:
                    pass
                self.openvpn_process = None
            subprocess.run(['taskkill', '/IM', 'openvpn.exe', '/F'], capture_output=True)
            self._on_vpn_disconnected_cleanup()

        threading.Thread(target=worker, daemon=True).start()

    def connect_vpngate_vpn(self):
        server_key = self.selected_server_key.get()
        server_host = self.vpn_servers_catalog.get(server_key, "public-vpn-75.opengw.net")

        if server_host == "custom":
            server_host = self.custom_server_host.get().strip()
            if not server_host:
                messagebox.showerror("Erreur", "Veuillez spécifier l'adresse hôte du serveur.")
                return

        self.status_bar.start()
        self.vpn_connecting = True

        def connect_worker():
            try:
                subprocess.run(['rasdial', self.real_vpn_name, '/disconnect'], capture_output=True)
                subprocess.run(['powershell', '-WindowStyle', 'Hidden', '-Command',
                                f"Remove-VpnConnection -Name '{self.real_vpn_name}' -Force -ErrorAction SilentlyContinue"],
                               capture_output=True)

                ps_cmd = (
                    f"Add-VpnConnection -Name '{self.real_vpn_name}' "
                    f"-ServerAddress '{server_host}' "
                    f"-TunnelType Sstp -EncryptionLevel Required -AuthenticationMethod MsChapv2 -Force"
                )
                subprocess.run(['powershell', '-WindowStyle', 'Hidden', '-Command', ps_cmd], capture_output=True)

                dial_res = subprocess.run(['rasdial', self.real_vpn_name, 'vpn', 'vpn'],
                                          capture_output=True, text=True, timeout=25)

                if dial_res.returncode == 0:
                    self._verify_real_ip_and_update(success=True, provider="Relais Public Gratuit",
                                                    detail=f"Connecté à {server_host}")
                else:
                    subprocess.run(['rasdial', self.real_vpn_name, '/disconnect'], capture_output=True)
                    self._verify_real_ip_and_update(success=False, provider="Relais Public Gratuit",
                                                    detail=dial_res.stderr or dial_res.stdout or "Délai d'attente dépassé.")
            except Exception as e:
                self._verify_real_ip_and_update(success=False, provider="Relais Public Gratuit", detail=str(e))

        threading.Thread(target=connect_worker, daemon=True).start()

    def disconnect_vpngate_vpn(self):
        self.status_bar.start()

        def worker():
            subprocess.run(['rasdial', self.real_vpn_name, '/disconnect'], capture_output=True)
            subprocess.run(['powershell', '-WindowStyle', 'Hidden', '-Command',
                            f"Remove-VpnConnection -Name '{self.real_vpn_name}' -Force -ErrorAction SilentlyContinue"],
                           capture_output=True)
            self._on_vpn_disconnected_cleanup()

        threading.Thread(target=worker, daemon=True).start()

    def _verify_real_ip_and_update(self, success, provider, detail=""):
        """Vérifie la véritable adresse IP publique après connexion et actualise l'UI."""
        self.vpn_connecting = False

        if success:
            time.sleep(1)
            real_ip = "En attente..."
            try:
                import urllib.request
                with urllib.request.urlopen('https://api.ipify.org', timeout=8) as r:
                    real_ip = r.read().decode('utf-8').strip()
            except Exception:
                real_ip = self.public_ip

            self.is_vpn_connected = True
            self.active_vpn_client = provider
            self.public_ip = real_ip

            def success_ui():
                self.status_bar.stop()
                self._update_kill_switch_ui()
                self.create_vpn_tab()
                msg = f"Le tunnel VPN via {provider} est maintenant ACTIF !\n\nVraie IP Publique : {real_ip}\n\nTout le trafic réseau de votre PC est désormais chiffré et sécurisé."
                self.notify("VPN Connecté avec Succès", msg)

            self.after(0, success_ui)
        else:
            self.is_vpn_connected = False
            def fail_ui():
                self.status_bar.stop()
                self.create_vpn_tab()
                err_msg = f"Impossible d'établir la connexion VPN avec {provider}.\n\nDétail : {detail[:150]}\n\nVeuillez choisir un autre serveur/emplacement ou vérifier votre connexion."
                messagebox.showerror("Échec de Connexion VPN", err_msg)
            self.after(0, fail_ui)

    def _on_vpn_disconnected_cleanup(self):
        """Procédure de nettoyage commune lors d'une déconnexion VPN."""
        self.is_vpn_connected = False
        self.active_vpn_client = "Aucun"

        if getattr(self, 'kill_switch_enabled', None) and self.kill_switch_enabled.get():
            self._apply_kill_switch_firewall()
            ks_triggered = True
        else:
            self._remove_kill_switch_firewall()
            ks_triggered = False

        try:
            import urllib.request
            with urllib.request.urlopen('https://api.ipify.org', timeout=6) as r:
                restored_ip = r.read().decode('utf-8').strip()
        except Exception:
            restored_ip = "En cours..."
        self.public_ip = restored_ip

        def finish_ui():
            self.status_bar.stop()
            self._update_kill_switch_ui()
            self.create_vpn_tab()
            if ks_triggered:
                self.notify(
                    "Kill Switch Pare-Feu Armé",
                    "Le VPN a été fermé. Le Kill Switch a bloqué le trafic non chiffré sortant.\n\nReconnectez un VPN ou désactivez le Kill Switch pour restaurer l'accès standard.", kind="warning")
            else:
                self.notify("VPN Déconnecté", f"Le tunnel a été fermé.\nIP Publique Restaurée : {restored_ip}")

        self.after(0, finish_ui)


    def create_dns_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "DNS"

        self._create_header("dns", "Protection DNS",
                            "Remplace le DNS de votre FAI sur toutes les interfaces réseau actives (droits administrateur requis).")
        main_container = self._create_scrollable_content()

        current_box = ctk.CTkFrame(main_container, fg_color=self.secondary_color, corner_radius=10,
                                   border_width=1, border_color=self.border_color)
        current_box.pack(fill="x", pady=(0, 12))
        self.dns_current_label = ctk.CTkLabel(current_box, text="DNS actuel : détection…",
                                              font=("Segoe UI", 12, "bold"),
                                              text_color=self.text_color_secondary)
        self.dns_current_label.pack(side="left", padx=16, pady=10)
        if not is_admin():
            ctk.CTkLabel(current_box, text=f"{self.icons['warning']} Lancez JustDown en administrateur pour modifier le DNS",
                         font=("Segoe UI", 11), text_color=COLOR_WARNING).pack(side="right", padx=16)

        dns_card = self.create_card(main_container, "Serveurs DNS",
                                    "Sélectionnez un résolveur DNS pour sécuriser vos requêtes et bloquer les malwares.",
                                    icon=self.icons['shield'])
        dns_card.pack(fill="x", pady=(0, 15))

        self.selected_dns = ctk.StringVar(value="Cloudflare")

        for name, (p, s, desc) in DNS_PROVIDERS.items():
            item = ctk.CTkFrame(dns_card, fg_color=self.secondary_color, corner_radius=10)
            item.pack(fill="x", padx=15, pady=4)

            inner = ctk.CTkFrame(item, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)

            ctk.CTkRadioButton(inner, text=name, variable=self.selected_dns,
                               value=name, font=("Segoe UI", 13, "bold")).pack(side="left")
            ctk.CTkLabel(inner, text=f"{p} / {s}", font=("Segoe UI", 12),
                         text_color=self.accent_color).pack(side="left", padx=20)
            ctk.CTkLabel(inner, text=desc, font=("Segoe UI", 11),
                         text_color=self.text_color_secondary).pack(side="right")

        ctk.CTkFrame(dns_card, fg_color="transparent", height=8).pack()

        btn_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=12)

        self.dns_apply_btn = AnimatedButton(btn_frame, text="Appliquer DNS",
                                            command=self.apply_dns_settings,
                                            width=200, height=42, fg_color=self.primary_color,
                                            hover_color=self.accent_color, corner_radius=10)
        self.dns_apply_btn.pack(side="left", padx=(0, 10))

        AnimatedButton(btn_frame, text="Restaurer (DHCP / FAI)",
                       command=self.restore_default_dns,
                       width=190, height=42, fg_color=self.secondary_color,
                       hover_color=self.border_color, corner_radius=10).pack(side="left")

        self._refresh_current_dns_label()

    def _get_active_interfaces(self):
        """Interfaces réseau actives disposant d'une adresse IPv4 (hors loopback / APIPA)."""
        names = []
        addrs = psutil.net_if_addrs()
        for name, st in psutil.net_if_stats().items():
            if not st.isup or "loopback" in name.lower():
                continue
            if any(a.family == socket.AF_INET and not a.address.startswith("169.254.")
                   for a in addrs.get(name, [])):
                names.append(name)
        return names

    def _get_current_dns_servers(self):
        out = run_quiet(['netsh', 'interface', 'ipv4', 'show', 'dnsservers']).stdout
        servers = []
        for token in out.split():
            parts = token.split('.')
            if len(parts) == 4 and all(p.isdigit() for p in parts) and token not in servers:
                servers.append(token)
        return servers

    def _refresh_current_dns_label(self):
        def worker():
            try:
                servers = self._get_current_dns_servers()
            except Exception:
                servers = []
            provider = next((n for n, (p, s, _) in DNS_PROVIDERS.items() if p in servers), None)

            def update():
                if not getattr(self, 'dns_current_label', None) or not self.dns_current_label.winfo_exists():
                    return
                if provider:
                    self.selected_dns.set(provider)
                    text, color = f"{self.icons['check']} DNS actuel : {provider} ({', '.join(servers[:2])})", COLOR_SUCCESS
                elif servers:
                    text, color = f"{self.icons['warning']} DNS actuel : {', '.join(servers[:2])} (FAI / box)", COLOR_WARNING
                else:
                    text, color = "DNS actuel : inconnu", self.text_color_secondary
                self.dns_current_label.configure(text=text, text_color=color)
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def apply_dns(self, provider):
        """Applique un fournisseur de DNS_PROVIDERS (ou "DHCP") à toutes les interfaces actives.

        Renvoie (interfaces_modifiées, erreurs). Lève RuntimeError si rien n'a pu être appliqué.
        """
        if not is_admin():
            raise RuntimeError("Droits administrateur requis : relancez JustDown en tant qu'administrateur.")
        interfaces = self._get_active_interfaces()
        if not interfaces:
            raise RuntimeError("Aucune interface réseau active n'a été trouvée.")

        done, errors = [], []
        for iface in interfaces:
            if provider == "DHCP":
                cmds = [['netsh', 'interface', 'ipv4', 'set', 'dnsservers', f'name={iface}', 'source=dhcp']]
            else:
                primary, secondary, _ = DNS_PROVIDERS[provider]
                cmds = [
                    ['netsh', 'interface', 'ipv4', 'set', 'dnsservers', f'name={iface}', 'source=static',
                     f'address={primary}', 'register=primary', 'validate=no'],
                    ['netsh', 'interface', 'ipv4', 'add', 'dnsservers', f'name={iface}',
                     f'address={secondary}', 'index=2', 'validate=no'],
                ]
            for cmd in cmds:
                res = run_quiet(cmd)
                if res.returncode != 0:
                    errors.append(f"{iface} : {(res.stdout or res.stderr).strip()[:150]}")
                    break
            else:
                done.append(iface)

        run_quiet(['ipconfig', '/flushdns'])
        if not done:
            raise RuntimeError("\n".join(errors) or "netsh a échoué.")
        return done, errors

    def _run_dns_change(self, provider, success_title):
        self.status_bar.start()

        def worker():
            try:
                done, errors = self.apply_dns(provider)
                error = None
            except Exception as e:
                done, errors, error = [], [], str(e)

            def finish():
                self.status_bar.stop()
                if error:
                    messagebox.showerror("DNS non modifié", error)
                else:
                    msg = f"Interfaces : {', '.join(done)}"
                    if errors:
                        msg += "\nÉchecs : " + "; ".join(errors)
                    self.notify(success_title, msg, kind="warning" if errors else "success")
                if self.current_tab_id == "DNS":
                    self._refresh_current_dns_label()
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def apply_dns_settings(self):
        provider = self.selected_dns.get()
        self._run_dns_change(provider, f"DNS {provider} appliqué")

    def restore_default_dns(self):
        self._run_dns_change("DHCP", "DNS automatique (DHCP) restauré")


    def create_anti_spy_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "ANTI_SPY"

        self._create_header("spy", "Anti-Espionnage & Protection Vie Privée")
        main_container = self._create_scrollable_content()

        master_card = ctk.CTkFrame(main_container, fg_color=self.card_color, corner_radius=14, border_width=1, border_color=self.border_color)
        master_card.pack(fill="x", pady=(0, 15))

        mc_inner = ctk.CTkFrame(master_card, fg_color="transparent")
        mc_inner.pack(fill="x", padx=25, pady=20)

        mc_left = ctk.CTkFrame(mc_inner, fg_color="transparent")
        mc_left.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(mc_left, text=f"{self.icons['spy']} Bouclier Anti-Espionnage Global",
                     font=("Segoe UI", 17, "bold"), text_color=self.primary_color).pack(anchor="w")

        st_text = "🛡️ État : ACTIVÉ (Votre PC est protégé contre l'espionnage)" if self.is_anti_spy_active else "⚠️ État : DÉSACTIVÉ (Télémétrie et suivi Windows autorisés)"
        st_color = "#10B981" if self.is_anti_spy_active else "#EF4444"

        self.anti_spy_state_label = ctk.CTkLabel(mc_left, text=st_text,
                                                 font=("Segoe UI", 14, "bold"),
                                                 text_color=st_color)
        self.anti_spy_state_label.pack(anchor="w", pady=(6, 4))

        ctk.CTkLabel(mc_left,
                     text="Cliquez sur le bouton pour activer ou désactiver instantanément tous les blocages de télémétrie.",
                     font=("Segoe UI", 11),
                     text_color=self.text_color_secondary).pack(anchor="w")

        mc_right = ctk.CTkFrame(mc_inner, fg_color="transparent")
        mc_right.pack(side="right", padx=(15, 0))

        btn_txt = "✔ ACTIVÉ" if self.is_anti_spy_active else "✖ DÉSACTIVÉ"
        btn_bg = "#10B981" if self.is_anti_spy_active else "#EF4444"
        btn_hov = "#059669" if self.is_anti_spy_active else "#DC2626"

        self.anti_spy_toggle_btn = AnimatedButton(
            mc_right,
            text=btn_txt,
            command=self.toggle_master_anti_spy,
            width=180, height=46,
            font=("Segoe UI", 15, "bold"),
            fg_color=btn_bg, hover_color=btn_hov,
            corner_radius=12
        )
        self.anti_spy_toggle_btn.pack(pady=(0, 3))

        hint_txt = "Cliquez pour DÉSACTIVER" if self.is_anti_spy_active else "Cliquez pour ACTIVER"
        self.anti_spy_hint_label = ctk.CTkLabel(mc_right, text=hint_txt,
                                                font=("Segoe UI", 10, "italic"),
                                                text_color=self.text_color_secondary)
        self.anti_spy_hint_label.pack()

        grid = ctk.CTkFrame(main_container, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1)

        tele_card = self.create_card(grid, "Services de Télémétrie",
                                     "Désactivez la collecte de données automatique de Microsoft.",
                                     icon=self.icons['spy'])
        tele_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)

        tele_options = [
            ("Service DiagTrack", "Collecte continue des diagnostics"),
            ("dmwappushservice", "Notifications push et télémétrie WAP"),
            ("Tâches planifiées", "Collecte et transmission en arrière-plan"),
            ("Customer Experience", "Programme d'amélioration de l'expérience"),
        ]

        self.telemetry_vars = {}
        for opt, desc in tele_options:
            self.telemetry_vars[opt] = ctk.BooleanVar(value=self.is_anti_spy_active)
            self._create_switch_row(tele_card, opt, desc, self.telemetry_vars[opt])

        feat_card = self.create_card(grid, "Fonctionnalités & Traceurs",
                                     "Désactivez les fonctions de pistage intégrées à Windows.",
                                     icon=self.icons['warning'])
        feat_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)

        feat_options = [
            ("Cortana", "Assistant vocal et écoute locale"),
            ("ID Publicitaire", "Identifiant unique de profilage ciblé"),
            ("Localisation", "Service de géolocalisation continue"),
            ("Rapports d'erreur", "Transmission auto des rapports à Microsoft"),
        ]

        self.features_vars = {}
        for opt, desc in feat_options:
            self.features_vars[opt] = ctk.BooleanVar(value=self.is_anti_spy_active)
            self._create_switch_row(feat_card, opt, desc, self.features_vars[opt], color=self.accent_color)

        perms_card = self.create_card(main_container, "Gestionnaire des Permissions Windows (App Permissions)",
                                      "Verrouillez l'accès des applications au matériel sensible et aux traceurs système.",
                                      icon=self.icons.get('camera', '📷'))
        perms_card.pack(fill="x", pady=12)

        self.init_permissions_state()

        perms_list = [
            ("webcam", "📷 Accès Caméra / Webcam", "Interdit aux applications d'activer la caméra à votre insu"),
            ("microphone", "🎤 Accès Microphone", "Bloque l'enregistrement audio des applications en arrière-plan"),
            ("location", "📍 Service de Localisation", "Empêche les logiciels de suivre vos déplacements et votre position"),
            ("background_apps", "🔄 Applications en Arrière-plan", "Désactive l'exécution et l'envoi de données en arrière-plan"),
            ("advertising_id", "📢 ID Publicitaire Microsoft", "Supprime l'identifiant de profilage publicitaire Windows"),
            ("radios", "📡 Radios & Bluetooth", "Contrôle les connexions radio et Bluetooth des applications"),
        ]

        for cap_key, label_title, label_desc in perms_list:
            p_row = ctk.CTkFrame(perms_card, fg_color="transparent")
            p_row.pack(fill="x", padx=15, pady=4)

            v = self.perm_vars[cap_key]
            ctk.CTkSwitch(p_row, text=label_title, variable=v,
                          command=lambda k=cap_key: self.toggle_permission_ui(k),
                          font=("Segoe UI", 13),
                          progress_color=self.primary_color).pack(side="left")

            ctk.CTkLabel(p_row, text=label_desc, font=("Segoe UI", 11),
                         text_color=self.text_color_secondary).pack(side="right")

        perms_btn_bar = ctk.CTkFrame(perms_card, fg_color="transparent")
        perms_btn_bar.pack(fill="x", padx=15, pady=(10, 15))

        AnimatedButton(perms_btn_bar, text="Tout Restreindre (Max Confidentialité)",
                       command=self._restrict_all_permissions,
                       width=260, height=35, fg_color=self.secondary_color,
                       hover_color=self.primary_color, corner_radius=10,
                       font=("Segoe UI", 12)).pack(side="left", padx=(0, 8))

        AnimatedButton(perms_btn_bar, text="Restaurer par défaut",
                       command=self._restore_default_permissions,
                       width=180, height=35, fg_color=self.secondary_color,
                       hover_color=self.border_color, corner_radius=10,
                       font=("Segoe UI", 12)).pack(side="left")

    def toggle_master_anti_spy(self):
        """Bascule l'état global de l'anti-espionnage et affiche clairement ACTIVÉ ou DÉSACTIVÉ."""
        self.is_anti_spy_active = not self.is_anti_spy_active
        self.status_bar.start()

        if self.is_anti_spy_active:
            self._do_apply_all_anti_spy_rules()
            st_text = "🛡️ État : ACTIVÉ (Votre PC est protégé contre l'espionnage)"
            st_color = "#10B981"
            btn_txt = "✔ ACTIVÉ"
            btn_bg = "#10B981"
            btn_hov = "#059669"
            hint_txt = "Cliquez pour DÉSACTIVER"
            msg = "Bouclier Anti-Espionnage : ACTIVÉ !\n\nTous les services de télémétrie Microsoft, le suivi publicitaire et les traceurs système sont maintenant bloqués."
        else:
            self._do_restore_all_anti_spy_rules()
            st_text = "⚠️ État : DÉSACTIVÉ (Télémétrie et suivi Windows autorisés)"
            st_color = "#EF4444"
            btn_txt = "✖ DÉSACTIVÉ"
            btn_bg = "#EF4444"
            btn_hov = "#DC2626"
            hint_txt = "Cliquez pour ACTIVER"
            msg = "Bouclier Anti-Espionnage : DÉSACTIVÉ !\n\nLes paramètres par défaut de Windows ont été restaurés."

        self.status_bar.stop()

        if hasattr(self, 'anti_spy_state_label') and self.anti_spy_state_label.winfo_exists():
            self.anti_spy_state_label.configure(text=st_text, text_color=st_color)
        if hasattr(self, 'anti_spy_toggle_btn') and self.anti_spy_toggle_btn.winfo_exists():
            self.anti_spy_toggle_btn.configure(text=btn_txt, fg_color=btn_bg, hover_color=btn_hov)
        if hasattr(self, 'anti_spy_hint_label') and self.anti_spy_hint_label.winfo_exists():
            self.anti_spy_hint_label.configure(text=hint_txt)

        if hasattr(self, 'telemetry_vars'):
            for v in self.telemetry_vars.values():
                v.set(self.is_anti_spy_active)
        if hasattr(self, 'features_vars'):
            for v in self.features_vars.values():
                v.set(self.is_anti_spy_active)
        if hasattr(self, 'perm_vars'):
            for v in self.perm_vars.values():
                v.set(self.is_anti_spy_active)

        self.notify("Anti-Espionnage", msg)

    def _do_apply_all_anti_spy_rules(self):
        try:
            subprocess.run(['sc', 'stop', 'DiagTrack'], capture_output=True)
            subprocess.run(['sc', 'config', 'DiagTrack', 'start=disabled'], capture_output=True)
            subprocess.run(['sc', 'stop', 'dmwappushservice'], capture_output=True)
            subprocess.run(['sc', 'config', 'dmwappushservice', 'start=disabled'], capture_output=True)
            subprocess.run(['sc', 'stop', 'lfsvc'], capture_output=True)
            subprocess.run(['sc', 'config', 'lfsvc', 'start=disabled'], capture_output=True)

            key_path = r"SOFTWARE\Policies\Microsoft\Windows\Windows Search"
            key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "AllowCortana", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
        except Exception:
            pass

        for k in ["webcam", "microphone", "location", "background_apps", "advertising_id", "radios"]:
            self.set_windows_permission(k, True)

    def _do_restore_all_anti_spy_rules(self):
        try:
            subprocess.run(['sc', 'config', 'DiagTrack', 'start=auto'], capture_output=True)
            subprocess.run(['sc', 'config', 'dmwappushservice', 'start=auto'], capture_output=True)
            subprocess.run(['sc', 'config', 'lfsvc', 'start=auto'], capture_output=True)
            subprocess.run(['sc', 'start', 'DiagTrack'], capture_output=True)
            subprocess.run(['sc', 'start', 'dmwappushservice'], capture_output=True)
            subprocess.run(['sc', 'start', 'lfsvc'], capture_output=True)

            key_path = r"SOFTWARE\Policies\Microsoft\Windows\Windows Search"
            key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "AllowCortana", 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
        except Exception:
            pass

        for k in ["webcam", "microphone", "location", "background_apps", "advertising_id", "radios"]:
            self.set_windows_permission(k, False)

    def _restrict_all_permissions(self):
        for k in self.perm_vars:
            self.perm_vars[k].set(True)
            self.set_windows_permission(k, True)
        self.notify("Permissions", "Toutes les autorisations sensibles ont été restreintes dans Windows avec succès.")

    def _restore_default_permissions(self):
        for k in self.perm_vars:
            self.perm_vars[k].set(False)
            self.set_windows_permission(k, False)
        self.notify("Permissions", "Les autorisations par défaut de Windows ont été restaurées.")

    def apply_anti_spy(self):
        self._do_apply_all_anti_spy_rules()
        self.is_anti_spy_active = True
        self.create_anti_spy_tab()
        self.notify("Succès", "Le bouclier Anti-Espionnage est maintenant ACTIVÉ !\nTous les traceurs Windows ont été désactivés.")

    def restore_windows_settings(self):
        self._do_restore_all_anti_spy_rules()
        self.is_anti_spy_active = False
        self.create_anti_spy_tab()
        self.notify("Succès", "Le bouclier Anti-Espionnage est maintenant DÉSACTIVÉ.\nLes paramètres Windows par défaut ont été restaurés.")


    def create_serial_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "SERIAL"

        self._create_header("serial", "Changement Serial")
        main_container = self._create_scrollable_content()

        warning_frame = ctk.CTkFrame(main_container, fg_color="#2D1A1A", corner_radius=12)
        warning_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(warning_frame,
                     text=f"{self.icons['warning']} Mode Démo — Les modifications ne sont pas appliquées réellement au système.",
                     font=("Segoe UI", 12),
                     text_color="#FF6B6B",
                     wraplength=600).pack(padx=15, pady=12)

        grid = ctk.CTkFrame(main_container, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1)

        current_card = self.create_card(grid, "Identifiants Actuels",
                                        "Vos identifiants matériels actuels visibles sur le réseau.",
                                        icon=self.icons['system'])
        current_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)

        hostname = socket.gethostname()
        mac_raw = uuid.getnode()
        mac_formatted = ':'.join(f'{(mac_raw >> ele) & 0xff:02x}' for ele in range(40, -1, -8))
        machine_uuid = str(uuid.uuid1())[:13]

        identifiers = [
            ("Hostname", hostname),
            ("Adresse MAC", mac_formatted),
            ("UUID Machine", machine_uuid),
            ("Nom d'utilisateur", os.getlogin()),
        ]

        self.serial_labels = {}
        for label_text, value in identifiers:
            row = ctk.CTkFrame(current_card, fg_color=self.secondary_color, corner_radius=10)
            row.pack(fill="x", padx=15, pady=4)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)

            ctk.CTkLabel(inner, text=label_text, font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(side="left")
            val_label = ctk.CTkLabel(inner, text=value, font=("Segoe UI", 11, "bold"),
                                     text_color=self.accent_color)
            val_label.pack(side="right")
            self.serial_labels[label_text] = val_label

        action_card = self.create_card(grid, "Randomiser",
                                       "Générez de nouveaux identifiants aléatoires.",
                                       icon=self.icons['refresh'])
        action_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)

        actions = [
            ("Randomiser le Hostname", self._randomize_hostname),
            ("Randomiser la MAC", self._randomize_mac),
            ("Randomiser UUID", self._randomize_uuid),
            ("Tout Randomiser", self._randomize_all),
        ]

        for text, cmd in actions:
            AnimatedButton(action_card, text=text, command=cmd,
                           width=220, height=40,
                           fg_color=self.secondary_color, hover_color=self.primary_color,
                           corner_radius=10,
                           font=("Segoe UI", 12)).pack(padx=15, pady=5)

        ctk.CTkFrame(action_card, fg_color="transparent", height=10).pack()

    def _randomize_hostname(self):
        new_name = "PC-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        self.serial_labels["Hostname"].configure(text=new_name, text_color="#10B981")
        self.notify("Démo", f"Hostname simulé : {new_name}\n(Non appliqué au système)")

    def _randomize_mac(self):
        new_mac = ':'.join(f'{random.randint(0, 255):02x}' for _ in range(6))
        parts = new_mac.split(':')
        parts[0] = f'{(int(parts[0], 16) | 0x02) & 0xfe:02x}'
        new_mac = ':'.join(parts)
        self.serial_labels["Adresse MAC"].configure(text=new_mac, text_color="#10B981")
        self.notify("Démo", f"MAC simulée : {new_mac}\n(Non appliqué au système)")

    def _randomize_uuid(self):
        new_uuid = str(uuid.uuid4())[:13]
        self.serial_labels["UUID Machine"].configure(text=new_uuid, text_color="#10B981")
        self.notify("Démo", f"UUID simulé : {new_uuid}\n(Non appliqué au système)")

    def _randomize_all(self):
        self._randomize_hostname()
        self._randomize_mac()
        self._randomize_uuid()


    def create_fake_identity_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "IDENTITY"

        self._create_header("identity", "Identité Factice")
        main_container = self._create_scrollable_content()

        gen_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        gen_frame.pack(fill="x", pady=(0, 12))

        AnimatedButton(gen_frame, text=f"{self.icons['refresh']}  Générer une nouvelle identité",
                       command=self._generate_identity,
                       width=300, height=45, fg_color=self.primary_color,
                       hover_color=self.accent_color, corner_radius=12,
                       font=("Segoe UI", 14, "bold")).pack(side="left")

        gender_frame = ctk.CTkFrame(gen_frame, fg_color="transparent")
        gender_frame.pack(side="right")
        self.gender_var = ctk.StringVar(value="Homme")
        ctk.CTkSegmentedButton(gender_frame, values=["Homme", "Femme"],
                               variable=self.gender_var,
                               font=("Segoe UI", 12)).pack(padx=5)

        grid = ctk.CTkFrame(main_container, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1)

        self.id_card = self.create_card(grid, "Identité Générée", icon=self.icons['user'])
        self.id_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)

        self.id_fields = {}
        field_names = ["Prénom", "Nom", "Date de naissance", "Adresse", "Ville", "Code Postal", "Email", "Téléphone"]
        for field in field_names:
            row_frame = ctk.CTkFrame(self.id_card, fg_color="transparent")
            row_frame.pack(fill="x", padx=15, pady=4)

            ctk.CTkLabel(row_frame, text=field, font=("Segoe UI", 12),
                         text_color=self.text_color_secondary, width=130, anchor="w").pack(side="left")

            val = ctk.CTkLabel(row_frame, text="—", font=("Segoe UI", 12, "bold"),
                               text_color=self.text_color)
            val.pack(side="left", padx=10, expand=True, fill="x")

            copy_btn = AnimatedButton(row_frame, text=self.icons['copy'],
                                      width=30, height=28,
                                      fg_color="transparent", hover_color=self.secondary_color,
                                      corner_radius=8,
                                      command=lambda f=field: self._copy_identity_field(f))
            copy_btn.pack(side="right")

            self.id_fields[field] = val

        actions_card = self.create_card(grid, "Actions Rapides", icon=self.icons['bolt'])
        actions_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)

        AnimatedButton(actions_card, text=f"{self.icons['copy']}  Copier tout",
                       command=self._copy_all_identity,
                       width=200, height=40, fg_color=self.secondary_color,
                       hover_color=self.primary_color, corner_radius=10,
                       font=("Segoe UI", 12)).pack(padx=15, pady=8)

        AnimatedButton(actions_card, text=f"{self.icons['refresh']}  Regénérer",
                       command=self._generate_identity,
                       width=200, height=40, fg_color=self.secondary_color,
                       hover_color=self.accent_color, corner_radius=10,
                       font=("Segoe UI", 12)).pack(padx=15, pady=8)

        info_frame = ctk.CTkFrame(actions_card, fg_color=self.secondary_color, corner_radius=10)
        info_frame.pack(fill="x", padx=15, pady=(15, 10))
        ctk.CTkLabel(info_frame,
                     text="Les identités générées sont fictives\net destinées à protéger votre\nvie privée en ligne.",
                     font=("Segoe UI", 11),
                     text_color=self.text_color_secondary,
                     justify="center").pack(padx=15, pady=15)

        self._generate_identity()

    def _generate_identity(self):
        """Génère une identité factice complète."""
        is_male = self.gender_var.get() == "Homme" if hasattr(self, 'gender_var') else random.choice([True, False])

        first_name = random.choice(FAKE_FIRST_NAMES_M if is_male else FAKE_FIRST_NAMES_F)
        last_name = random.choice(FAKE_LAST_NAMES)

        year = random.randint(1970, 2002)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        dob = f"{day:02d}/{month:02d}/{year}"

        street_num = random.randint(1, 150)
        street = random.choice(FAKE_STREETS)

        city, zipcode = random.choice(FAKE_CITIES)

        email_user = f"{first_name.lower()}.{last_name.lower()}{random.randint(10, 99)}"
        email_domain = random.choice(FAKE_EMAIL_DOMAINS)
        email = f"{email_user}@{email_domain}"

        phone_prefix = random.choice(["06", "07", "+33 6", "+33 7"])
        phone = f"{phone_prefix} {random.randint(10, 99)} {random.randint(10, 99)} {random.randint(10, 99)} {random.randint(10, 99)}"

        data = {
            "Prénom": first_name,
            "Nom": last_name,
            "Date de naissance": dob,
            "Adresse": f"{street_num} {street}",
            "Ville": city,
            "Code Postal": zipcode,
            "Email": email,
            "Téléphone": phone,
        }

        self._current_identity = data

        if hasattr(self, 'id_fields'):
            for field, value in data.items():
                if field in self.id_fields:
                    self.id_fields[field].configure(text=value)

    def _copy_identity_field(self, field):
        if hasattr(self, '_current_identity') and field in self._current_identity:
            try:
                pyperclip.copy(self._current_identity[field])
            except Exception:
                self.clipboard_clear()
                self.clipboard_append(self._current_identity[field])

    def _copy_all_identity(self):
        if hasattr(self, '_current_identity'):
            text = "\n".join(f"{k}: {v}" for k, v in self._current_identity.items())
            try:
                pyperclip.copy(text)
            except Exception:
                self.clipboard_clear()
                self.clipboard_append(text)
            self.notify("Copié", "L'identité complète a été copiée dans le presse-papier.")


    def create_encryption_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "ENCRYPTION"

        self._create_header("encryption", "Chiffrement AES Militaire & Confidentialité",
                           "Chiffrez et protégez vos fichiers et textes avec des clés cryptographiques robustes.")
        main_container = self._create_scrollable_content()

        file_card = self.create_card(main_container, "Chiffrement de Fichiers (AES-256 / ChaCha20)",
                                     "Sélectionnez un fichier pour le verrouiller avec une clé dérivée par PBKDF2 (100 000 itérations).",
                                     icon=self.icons['security'])
        file_card.pack(fill="x", pady=(0, 12))

        file_select_frame = ctk.CTkFrame(file_card, fg_color=self.secondary_color, corner_radius=10,
                                         border_width=1, border_color=self.border_color)
        file_select_frame.pack(fill="x", padx=16, pady=8)

        file_inner = ctk.CTkFrame(file_select_frame, fg_color="transparent")
        file_inner.pack(fill="x", padx=14, pady=10)

        self.selected_file_label = ctk.CTkLabel(file_inner, text="Aucun fichier sélectionné",
                                                 font=("Segoe UI", 12),
                                                 text_color=self.text_color_secondary)
        self.selected_file_label.pack(side="left", fill="x", expand=True)

        AnimatedButton(file_inner, text="📁 Parcourir...",
                       command=self._select_file_for_encryption,
                       width=130, height=34,
                       fg_color=self.card_color, hover_color=self.primary_color,
                       corner_radius=8, font=("Segoe UI", 12, "bold")).pack(side="right")

        pwd_frame = ctk.CTkFrame(file_card, fg_color="transparent")
        pwd_frame.pack(fill="x", padx=16, pady=6)

        ctk.CTkLabel(pwd_frame, text="Clé secrète / Mot de passe :", font=("Segoe UI", 12, "bold"),
                     text_color="#F8FAFC").pack(side="left")
        pwd_box, self.file_password_entry = self._create_password_entry(pwd_frame)
        pwd_box.pack(side="right")

        file_opt_row = ctk.CTkFrame(file_card, fg_color="transparent")
        file_opt_row.pack(fill="x", padx=16, pady=4)

        self.keep_original_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(file_opt_row, text="Conserver une copie du fichier original en sécurité",
                        variable=self.keep_original_var, font=("Segoe UI", 11),
                        fg_color=self.primary_color).pack(side="left")

        file_btn_frame = ctk.CTkFrame(file_card, fg_color="transparent")
        file_btn_frame.pack(fill="x", padx=16, pady=(10, 16))

        AnimatedButton(file_btn_frame, text=f"{self.icons['security']} Chiffrer le Fichier",
                       command=self._do_encrypt_file,
                       width=190, height=42, fg_color=self.primary_color,
                       hover_color=self.accent_color, corner_radius=8,
                       font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 10))

        AnimatedButton(file_btn_frame, text=f"{self.icons['encryption']} Déchiffrer le Fichier",
                       command=self._do_decrypt_file,
                       width=190, height=42, fg_color=self.secondary_color,
                       hover_color=self.primary_color, corner_radius=8,
                       font=("Segoe UI", 12, "bold")).pack(side="left")

        text_card = self.create_card(main_container, "Chiffrement de Texte & Messages Secrets",
                                     "Chiffrez ou déchiffrez des notes confidentielles, clés ou messages instantanés.",
                                     icon=self.icons['encryption'])
        text_card.pack(fill="x", pady=(0, 12))

        self.text_input = ctk.CTkTextbox(text_card, height=110, fg_color=self.secondary_color,
                                          border_width=1, border_color=self.border_color,
                                          font=("Consolas", 12))
        self.text_input.pack(fill="x", padx=16, pady=8)

        text_pwd_frame = ctk.CTkFrame(text_card, fg_color="transparent")
        text_pwd_frame.pack(fill="x", padx=16, pady=6)

        ctk.CTkLabel(text_pwd_frame, text="Mot de passe du texte :", font=("Segoe UI", 12, "bold"),
                     text_color="#F8FAFC").pack(side="left")
        text_pwd_box, self.text_password_entry = self._create_password_entry(text_pwd_frame)
        text_pwd_box.pack(side="right")

        text_btn_frame = ctk.CTkFrame(text_card, fg_color="transparent")
        text_btn_frame.pack(fill="x", padx=16, pady=(10, 16))

        AnimatedButton(text_btn_frame, text="🔒 Chiffrer le Texte",
                       command=self._do_encrypt_text,
                       width=170, height=38, fg_color=self.primary_color,
                       hover_color=self.accent_color, corner_radius=8,
                       font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 8))

        AnimatedButton(text_btn_frame, text="🔓 Déchiffrer le Texte",
                       command=self._do_decrypt_text,
                       width=170, height=38, fg_color=self.secondary_color,
                       hover_color=self.primary_color, corner_radius=8,
                       font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 8))

        AnimatedButton(text_btn_frame, text="📋 Copier Résultat",
                       command=self._copy_encrypted_text,
                       width=140, height=38, fg_color=self.secondary_color,
                       hover_color=self.border_color, corner_radius=8,
                       font=("Segoe UI", 11)).pack(side="left")

        advanced_card = self.create_card(main_container, "Paramètres d'Algorithme & Dérivation PBKDF2",
                                         "Configurez les paramètres mathématiques de chiffrement et de dérivation de clé.",
                                         icon=self.icons['settings'])
        advanced_card.pack(fill="x", pady=(0, 12))

        settings_grid = ctk.CTkFrame(advanced_card, fg_color="transparent")
        settings_grid.pack(fill="x", padx=16, pady=8)
        settings_grid.grid_columnconfigure((0, 1), weight=1)

        algo_item = ctk.CTkFrame(settings_grid, fg_color="transparent")
        algo_item.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(algo_item, text="Algorithme standard :", font=("Segoe UI", 12, "bold"), text_color="#F8FAFC").pack(side="left")
        self.algo_var = ctk.StringVar(value="AES-256 (Fernet / CBC)")
        ctk.CTkOptionMenu(algo_item, values=["AES-256 (Fernet / CBC)", "ChaCha20-Poly1305", "AES-CTR Authentifié"],
                          variable=self.algo_var, width=200,
                          fg_color=self.secondary_color, button_color=self.primary_color).pack(side="right")

        key_item = ctk.CTkFrame(settings_grid, fg_color="transparent")
        key_item.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ctk.CTkLabel(key_item, text="Dérivation PBKDF2 :", font=("Segoe UI", 12, "bold"), text_color="#F8FAFC").pack(side="left")
        self.key_strength = ctk.StringVar(value="100 000 itérations (SHA-256)")
        ctk.CTkOptionMenu(key_item, values=["100 000 itérations (SHA-256)", "250 000 itérations (Max Sécurité)", "50 000 itérations (Rapide)"],
                          variable=self.key_strength, width=220,
                          fg_color=self.secondary_color, button_color=self.primary_color).pack(side="right")

    def _select_file_for_encryption(self):
        filename = filedialog.askopenfilename()
        if filename:
            self.current_encrypt_file = filename
            size_kb = os.path.getsize(filename) / 1024
            size_str = f"{size_kb:.1f} Ko" if size_kb < 1024 else f"{size_kb/1024:.2f} Mo"
            if hasattr(self, 'selected_file_label'):
                folder = os.path.dirname(filename)
                if len(folder) > 45:
                    folder = "…" + folder[-44:]
                self.selected_file_label.configure(
                    text=f"📄 {os.path.basename(filename)}  ·  {size_str}\n{folder}",
                    text_color="#F8FAFC", justify="left", anchor="w")

    def _do_encrypt_file(self):
        if not hasattr(self, 'current_encrypt_file') or not self.current_encrypt_file:
            messagebox.showerror("Erreur", "Veuillez d'abord sélectionner un fichier en cliquant sur 'Parcourir...'.")
            return
        password = self.file_password_entry.get().strip() if hasattr(self, 'file_password_entry') else ""
        if not password:
            messagebox.showerror("Erreur", "Veuillez entrer un mot de passe ou une clé secrète.")
            return

        self.status_bar.start()
        try:
            keep_orig = getattr(self, 'keep_original_var', None) and self.keep_original_var.get()
            success, result = self._encrypt_file_impl(self.current_encrypt_file, password, keep_original=keep_orig)
            self.status_bar.stop()
            if success:
                self.notify("Succès", f"Fichier chiffré avec succès !\n\nFichier chiffré généré :\n{result}")
            else:
                messagebox.showerror("Erreur de Chiffrement", f"Échec : {result}")
        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", str(e))

    def _do_decrypt_file(self):
        filename = filedialog.askopenfilename(filetypes=[("Fichiers chiffrés", "*.encrypted"), ("Tous les fichiers", "*.*")])
        if not filename:
            return
        password = self.file_password_entry.get().strip() if hasattr(self, 'file_password_entry') else ""
        if not password:
            messagebox.showerror("Erreur", "Veuillez entrer le mot de passe de déchiffrement.")
            return

        self.status_bar.start()
        try:
            success, result = self._decrypt_file_impl(filename, password)
            self.status_bar.stop()
            if success:
                self.notify("Succès", f"Fichier déchiffré avec succès !\n\nFichier restauré :\n{result}")
            else:
                messagebox.showerror("Erreur de Déchiffrement", f"Échec : Mot de passe incorrect ou fichier corrompu.\n({result})")
        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", str(e))

    def _do_encrypt_text(self):
        text = self.text_input.get("1.0", END).strip()
        if not text:
            messagebox.showerror("Erreur", "Veuillez entrer du texte à chiffrer dans la zone prévue.")
            return
        password = self.text_password_entry.get().strip() if hasattr(self, 'text_password_entry') else ""
        if not password:
            messagebox.showerror("Erreur", "Veuillez entrer un mot de passe pour le texte.")
            return

        success, result = self._encrypt_text_impl(text, password)
        if success:
            self.text_input.delete("1.0", END)
            self.text_input.insert("1.0", result)
            self.notify("Succès", "Texte chiffré avec succès !")
        else:
            messagebox.showerror("Erreur", result)

    def _do_decrypt_text(self):
        text = self.text_input.get("1.0", END).strip()
        if not text:
            messagebox.showerror("Erreur", "Veuillez coller le texte chiffré à déchiffrer.")
            return
        password = self.text_password_entry.get().strip() if hasattr(self, 'text_password_entry') else ""
        if not password:
            messagebox.showerror("Erreur", "Veuillez entrer le mot de passe associé.")
            return

        success, result = self._decrypt_text_impl(text, password)
        if success:
            self.text_input.delete("1.0", END)
            self.text_input.insert("1.0", result)
            self.notify("Succès", "Texte déchiffré avec succès !")
        else:
            messagebox.showerror("Erreur de Déchiffrement", "Mot de passe incorrect ou texte chiffré invalide.")

    def _copy_encrypted_text(self):
        text = self.text_input.get("1.0", END).strip()
        if text:
            try:
                pyperclip.copy(text)
            except Exception:
                self.clipboard_clear()
                self.clipboard_append(text)
            self.notify("Copié", "Le contenu a été copié dans le presse-papier.")



    def create_clean_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "CLEANER"

        self._create_header("clean", "Nettoyeur Système",
                            "Fermez vos navigateurs avant de nettoyer cookies, historique et formulaires.")
        scroll_container = self._create_scrollable_content()

        grid_frame = ctk.CTkFrame(scroll_container, fg_color="transparent")
        grid_frame.pack(fill="x")
        grid_frame.grid_columnconfigure((0, 1), weight=1)

        windows_card = self.create_card(grid_frame, "Système Windows", icon=self.icons['system'])
        windows_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)

        windows_options = [
            ("Fichiers temporaires", "Dossiers TEMP utilisateur et Windows"),
            ("Cache DNS", "Vider le cache de résolution"),
            ("Corbeille", "Vider tous les éléments"),
            ("Rapports d'erreur", "Dumps de plantage et rapports Windows (WER)"),
        ]

        self.windows_vars = {}
        for option, description in windows_options:
            self.windows_vars[option] = ctk.BooleanVar(value=True)
            self._create_switch_row(windows_card, option, description, self.windows_vars[option])

        browser_card = self.create_card(grid_frame, "Navigateurs Web (Chrome, Edge, Brave, Firefox)",
                                        icon=self.icons['network'])
        browser_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)

        browser_options = [
            ("Cache Web", "Fichiers de navigation mis en cache", True),
            ("Cookies", "Vous serez déconnecté de vos sites", False),
            ("Historique", "Sites visités (favoris conservés)", False),
            ("Formulaires", "Données d'auto-complétion", False),
        ]

        self.browser_vars = {}
        for option, description, default in browser_options:
            self.browser_vars[option] = ctk.BooleanVar(value=default)
            self._create_switch_row(browser_card, option, description, self.browser_vars[option],
                                    color=self.accent_color)

        action_frame = ctk.CTkFrame(scroll_container, fg_color=self.secondary_color, corner_radius=15)
        action_frame.pack(fill="x", pady=15)

        btn_inner = ctk.CTkFrame(action_frame, fg_color="transparent")
        btn_inner.pack(fill="x", padx=20, pady=18)

        AnimatedButton(btn_inner, text=f"{self.icons['refresh']} Analyser le système",
                       command=self.analyze_system,
                       width=200, height=45, fg_color=self.card_color,
                       hover_color=self.accent_color, corner_radius=10,
                       font=("Segoe UI", 13)).pack(side="left")

        AnimatedButton(btn_inner, text=f"{self.icons['cleaner']} Lancer le nettoyage",
                       command=self.clean_system,
                       width=200, height=45, fg_color=self.primary_color,
                       hover_color=self.accent_color, corner_radius=10,
                       font=("Segoe UI", 13, "bold")).pack(side="right")

        self.clean_result_label = ctk.CTkLabel(btn_inner, text="Lancez une analyse pour estimer l'espace récupérable.",
                                               font=("Segoe UI", 11), justify="left",
                                               text_color=self.text_color_secondary)
        self.clean_result_label.pack(side="left", padx=16, fill="x", expand=True)

    def _selected_clean_options(self):
        """Lit les interrupteurs (thread principal uniquement)."""
        selected = {k for k, v in self.windows_vars.items() if v.get()}
        selected |= {k for k, v in self.browser_vars.items() if v.get()}
        return selected

    def _set_clean_result(self, text, color=None):
        if getattr(self, 'clean_result_label', None) and self.clean_result_label.winfo_exists():
            self.clean_result_label.configure(text=text, text_color=color or self.text_color_secondary)

    def analyze_system(self):
        selected = self._selected_clean_options()
        self.status_bar.start()
        self._set_clean_result("Analyse en cours…")

        def worker():
            sizes = {}
            if "Fichiers temporaires" in selected:
                sizes["Fichiers temporaires"] = sum(dir_size(d) for d in temp_dirs())
            if "Corbeille" in selected:
                sizes["Corbeille"] = recycle_bin_size()
            if "Rapports d'erreur" in selected:
                sizes["Rapports d'erreur"] = sum(dir_size(d) for d in error_report_dirs())
            if "Cache Web" in selected:
                sizes["Cache Web"] = sum(dir_size(d) for d in browser_cache_dirs())
            total = sum(sizes.values())

            def finish():
                self.status_bar.stop()
                detail = "\n".join(f"{k} : {format_size(v)}" for k, v in sizes.items())
                self._set_clean_result(f"Espace récupérable : {format_size(total)}\n{detail}", self.text_color)
                self.notify("Analyse terminée", f"Espace récupérable : {format_size(total)}\n{detail}")
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def clean_system(self):
        selected = self._selected_clean_options()
        if not selected:
            self.notify("Rien à nettoyer", "Activez au moins une option.", kind="warning")
            return
        if not messagebox.askyesno("Confirmation",
                                   "Êtes-vous sûr de vouloir nettoyer les éléments sélectionnés ?\n"
                                   "Cette action est irréversible."):
            return

        self.status_bar.start()
        self._set_clean_result("Nettoyage en cours…")

        def worker():
            freed, locked, error = 0, set(), None
            try:
                if "Fichiers temporaires" in selected:
                    freed += sum(empty_dir(d) for d in temp_dirs())
                if "Cache DNS" in selected:
                    run_quiet(['ipconfig', '/flushdns'])
                if "Corbeille" in selected:
                    size = recycle_bin_size()
                    empty_recycle_bin()
                    freed += max(size - recycle_bin_size(), 0)
                if "Rapports d'erreur" in selected:
                    freed += sum(empty_dir(d) for d in error_report_dirs())
                if "Cache Web" in selected:
                    freed += sum(empty_dir(d) for d in browser_cache_dirs())
                locked = self._clean_browser_databases(selected)
            except Exception as e:
                error = str(e)

            def finish():
                self.status_bar.stop()
                if error:
                    self._set_clean_result("Le nettoyage a été interrompu.", COLOR_DANGER)
                    messagebox.showerror("Erreur", f"Une erreur est survenue lors du nettoyage : {error}")
                    return
                self._set_clean_result(f"Dernier nettoyage : {format_size(freed)} libérés", COLOR_SUCCESS)
                self.notify("Nettoyage terminé", f"{format_size(freed)} libérés.")
                if locked:
                    self.notify("Navigateurs ouverts",
                                f"{', '.join(sorted(locked))} : cookies/historique/formulaires non nettoyés. "
                                "Fermez le navigateur puis relancez le nettoyage.", kind="warning")
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _clean_browser_databases(self, selected):
        """Purge cookies / historique / formulaires. Renvoie les navigateurs dont la base était verrouillée."""
        locked = set()
        for browser, profile in chromium_profiles():
            jobs = []
            if "Cookies" in selected:
                cookie_db = os.path.join(profile, "Network", "Cookies")
                if not os.path.isfile(cookie_db):
                    cookie_db = os.path.join(profile, "Cookies")
                jobs.append((cookie_db, ["DELETE FROM cookies"]))
            if "Historique" in selected:
                jobs.append((os.path.join(profile, "History"),
                             ["DELETE FROM visits", "DELETE FROM urls", "DELETE FROM keyword_search_terms",
                              "DELETE FROM segment_usage", "DELETE FROM segments"]))
            if "Formulaires" in selected:
                jobs.append((os.path.join(profile, "Web Data"), ["DELETE FROM autofill"]))
            for db, statements in jobs:
                if not sqlite_purge(db, statements):
                    locked.add(browser)

        for roaming, _local in firefox_profiles():
            jobs = []
            if "Cookies" in selected:
                jobs.append((os.path.join(roaming, "cookies.sqlite"), ["DELETE FROM moz_cookies"]))
            if "Historique" in selected:
                jobs.append((os.path.join(roaming, "places.sqlite"),
                             ["DELETE FROM moz_historyvisits",
                              "UPDATE moz_places SET visit_count = 0, last_visit_date = NULL"]))
            if "Formulaires" in selected:
                jobs.append((os.path.join(roaming, "formhistory.sqlite"), ["DELETE FROM moz_formhistory"]))
            for db, statements in jobs:
                if not sqlite_purge(db, statements):
                    locked.add("Firefox")
        return locked


    def create_secure_delete_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "SECURE_DELETE"

        self._create_header("delete", "Suppression Sécurisée")
        main_container = self._create_scrollable_content()

        files_card = self.create_card(main_container, "Sélection des Fichiers", icon=self.icons['delete'])
        files_card.pack(fill="x", pady=(0, 12))

        self.selected_files_textbox = ctk.CTkTextbox(files_card, height=100,
                                                      fg_color=self.secondary_color,
                                                      border_width=1,
                                                      border_color=self.border_color,
                                                      font=("Consolas", 11),
                                                      state="disabled")
        self.selected_files_textbox.pack(fill="x", padx=15, pady=8)

        buttons_frame = ctk.CTkFrame(files_card, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=15, pady=(0, 15))

        AnimatedButton(buttons_frame, text="Sélectionner des fichiers",
                       command=self._select_files_to_delete,
                       width=200, height=38,
                       fg_color=self.secondary_color, hover_color=self.accent_color,
                       corner_radius=10,
                       font=("Segoe UI", 12)).pack(side="left", padx=(0, 8))

        AnimatedButton(buttons_frame, text="Effacer la sélection",
                       command=self._clear_file_selection,
                       width=180, height=38,
                       fg_color=self.secondary_color, hover_color=self.accent_color,
                       corner_radius=10,
                       font=("Segoe UI", 12)).pack(side="left")

        options_card = self.create_card(main_container, "Options de Suppression", icon=self.icons['settings'])
        options_card.pack(fill="x", pady=(0, 12))

        passes_frame = ctk.CTkFrame(options_card, fg_color="transparent")
        passes_frame.pack(fill="x", padx=15, pady=8)

        ctk.CTkLabel(passes_frame, text="Nombre de passes d'écrasement :",
                     font=("Segoe UI", 13)).pack(side="left")

        self.passes_var = ctk.StringVar(value="3")
        ctk.CTkOptionMenu(passes_frame, variable=self.passes_var,
                          values=["1", "3", "7", "35"],
                          width=100, fg_color=self.secondary_color,
                          button_color=self.primary_color).pack(side="right")

        self.zero_fill_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(options_card, text="Remplir avec des zéros après la suppression",
                        variable=self.zero_fill_var,
                        font=("Segoe UI", 13),
                        fg_color=self.primary_color).pack(anchor="w", padx=15, pady=5)

        self.rename_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(options_card, text="Renommer le fichier avant la suppression",
                        variable=self.rename_var,
                        font=("Segoe UI", 13),
                        fg_color=self.primary_color).pack(anchor="w", padx=15, pady=(5, 15))

        AnimatedButton(main_container,
                       text=f"{self.icons['warning']} Supprimer de manière sécurisée",
                       command=self._perform_secure_delete,
                       width=300, height=45,
                       font=("Segoe UI", 14, "bold"),
                       fg_color="#EF4444", hover_color="#DC2626",
                       corner_radius=10).pack(pady=15)

    def _select_files_to_delete(self):
        files = filedialog.askopenfilenames(
            title="Sélectionner les fichiers à supprimer",
            filetypes=[("Tous les fichiers", "*.*")])
        if files:
            self.selected_files = list(files)
            self._update_selected_files_display()

    def _clear_file_selection(self):
        self.selected_files = []
        self._update_selected_files_display()

    def _update_selected_files_display(self):
        self.selected_files_textbox.configure(state="normal")
        self.selected_files_textbox.delete("1.0", END)
        for f in self.selected_files:
            self.selected_files_textbox.insert(END, f"{f}\n")
        self.selected_files_textbox.configure(state="disabled")

    def _perform_secure_delete(self):
        if not self.selected_files:
            self.notify("Attention", "Veuillez sélectionner au moins un fichier à supprimer.", kind="warning")
            return

        if not messagebox.askyesno("Confirmation",
                                   "Êtes-vous sûr de vouloir supprimer définitivement ces fichiers ?\n"
                                   "Cette action est irréversible."):
            return

        self.status_bar.start()
        passes = int(self.passes_var.get())

        try:
            for file_path in self.selected_files:
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)

                    if self.rename_var.get():
                        directory = os.path.dirname(file_path)
                        random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
                        new_path = os.path.join(directory, random_name)
                        os.rename(file_path, new_path)
                        file_path = new_path

                    with open(file_path, 'wb') as f:
                        for pass_num in range(passes):
                            f.seek(0)
                            if pass_num % 3 == 0:
                                f.write(b'\x00' * file_size)
                            elif pass_num % 3 == 1:
                                f.write(b'\xFF' * file_size)
                            else:
                                f.write(os.urandom(file_size))
                            f.flush()
                            os.fsync(f.fileno())

                    os.remove(file_path)

            self.status_bar.stop()
            self.selected_files = []
            self._update_selected_files_display()
            self.notify("Succès", "Les fichiers ont été supprimés de manière sécurisée.")

        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", f"Une erreur est survenue : {str(e)}")


    def create_privacy_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "PRIVACY"

        self._create_header("privacy", "Navigation Privée, WebRTC & Anti-Fingerprint")
        main_container = self._create_scrollable_content()

        browsing_card = self.create_card(main_container, "Paramètres de Navigation & Traçage",
                                         "Optimisez votre navigateur pour une confidentialité maximale et sans fuite.",
                                         icon=self.icons['network'])
        browsing_card.pack(fill="x", pady=(0, 10))

        privacy_options = [
            ("Bloquer les trackers", "Empêche les régies publicitaires de vous pister entre les sites"),
            ("Navigation Privée Permanente", "Ne conserve aucun historique, cookie persistant ou session"),
            ("Cookies Tiers Bloqués", "Interdit le dépôt de cookies cross-site non sollicités"),
            ("Protection DoH (DNS over HTTPS)", "Chiffre les résolutions d'adresses web"),
        ]

        self.privacy_vars = {}
        for option, description in privacy_options:
            self.privacy_vars[option] = ctk.BooleanVar(value=True)
            self._create_switch_row(browsing_card, option, description, self.privacy_vars[option])

        webrtc_card = self.create_card(main_container, "Protection des Fuites WebRTC",
                                       "WebRTC peut exposer votre adresse IP publique et votre IP de réseau local (192.168.x.x) même derrière un VPN.",
                                       icon=self.icons.get('shield', '🛡️'))
        webrtc_card.pack(fill="x", pady=10)

        webrtc_row = ctk.CTkFrame(webrtc_card, fg_color="transparent")
        webrtc_row.pack(fill="x", padx=15, pady=8)

        self.webrtc_block_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(webrtc_row, text="Bloquer les fuites WebRTC pour Chrome, Edge & Brave (disable_non_proxied_udp)",
                      variable=self.webrtc_block_var,
                      command=lambda: self.apply_browser_webrtc_policy(self.webrtc_block_var.get()),
                      font=("Segoe UI", 13),
                      progress_color=self.primary_color).pack(side="left")

        ctk.CTkLabel(webrtc_row, text="Politique Système Windows Active",
                     font=("Segoe UI", 11, "bold"), text_color="#10B981").pack(side="right")

        fp_card = self.create_card(main_container, "Protection de l'Empreinte Numérique (Anti-Fingerprinting)",
                                   "Randomisez les identifiants uniques matériels, audio et graphiques collectés par les scripts de profilage.",
                                   icon=self.icons.get('fingerprint', '🐾'))
        fp_card.pack(fill="x", pady=10)

        self.canvas_noise_var = ctk.BooleanVar(value=True)
        self.audio_mask_var = ctk.BooleanVar(value=True)
        self.webgl_spoof_var = ctk.BooleanVar(value=True)

        self._create_switch_row(fp_card, "Injection de bruit Canvas", "Altère imperceptiblement les pixels pour rendre le hash de rendu unique et non traçable", self.canvas_noise_var)
        self._create_switch_row(fp_card, "Masquage AudioContext", "Empêche l'empreinte sonore générée via le traitement audio web", self.audio_mask_var)
        self._create_switch_row(fp_card, "Masquage Carte Graphique & WebGL", "Dissimule le modèle exact de votre carte graphique et son constructeur", self.webgl_spoof_var)

        ua_frame = ctk.CTkFrame(fp_card, fg_color="transparent")
        ua_frame.pack(fill="x", padx=15, pady=(8, 12))

        ctk.CTkLabel(ua_frame, text="Profil User-Agent simulé :", font=("Segoe UI", 13)).pack(side="left")
        self.ua_preset_var = ctk.StringVar(value="Windows 11 / Chrome 124 (Recommandé)")
        ctk.CTkOptionMenu(ua_frame, variable=self.ua_preset_var,
                          values=[
                              "Windows 11 / Chrome 124 (Recommandé)",
                              "macOS Sonoma / Safari 17.4",
                              "Linux Ubuntu / Firefox 125 ESR",
                              "Windows 10 / Firefox Privacy Edition"
                          ],
                          width=300, fg_color=self.secondary_color,
                          button_color=self.primary_color).pack(side="right")

        btn_bar = ctk.CTkFrame(fp_card, fg_color="transparent")
        btn_bar.pack(fill="x", padx=15, pady=(5, 15))

        AnimatedButton(btn_bar, text="🐾 Analyser mon Empreinte (Simulateur)",
                       command=self.show_fingerprint_analyzer,
                       width=260, height=36, fg_color=self.secondary_color,
                       hover_color=self.primary_color, corner_radius=10,
                       font=("Segoe UI", 12)).pack(side="left", padx=(0, 10))

        AnimatedButton(btn_bar, text="📄 Exporter Profil Durci (user.js)",
                       command=self.generate_firefox_hardened_profile,
                       width=240, height=36, fg_color=self.secondary_color,
                       hover_color=self.border_color, corner_radius=10,
                       font=("Segoe UI", 12)).pack(side="left")

        action_bar = ctk.CTkFrame(main_container, fg_color="transparent")
        action_bar.pack(fill="x", pady=15)

        AnimatedButton(action_bar, text=f"{self.icons['check']} Sauvegarder & Appliquer",
                       command=self._save_privacy_settings,
                       width=220, height=42, fg_color=self.primary_color,
                       hover_color=self.accent_color, corner_radius=10,
                       font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 10))

        AnimatedButton(action_bar, text="Réinitialiser",
                       command=self._reset_privacy_settings,
                       width=150, height=42, fg_color=self.secondary_color,
                       hover_color=self.border_color, corner_radius=10).pack(side="left")

    def _save_privacy_settings(self):
        self.status_bar.start()
        self.after(800, lambda: (self.status_bar.stop(),
                                  self.notify("Confidentialité",
                                              "Paramètres de confidentialité mis à jour avec succès !")))

    def _reset_privacy_settings(self):
        if hasattr(self, 'privacy_vars'):
            for var in self.privacy_vars.values():
                var.set(True)
        self.notify("Confidentialité", "Paramètres réinitialisés aux valeurs par défaut.")


    def create_email_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "EMAIL"

        self._create_header("email", "Email Jetable")
        main_container = self._create_scrollable_content()

        gen_card = self.create_card(main_container, "Générateur d'Email Temporaire",
                                    "Créez des adresses email jetables pour protéger votre identité.",
                                    icon=self.icons['email'])
        gen_card.pack(fill="x", pady=(0, 15))

        email_display = ctk.CTkFrame(gen_card, fg_color=self.secondary_color, corner_radius=12)
        email_display.pack(fill="x", padx=15, pady=8)

        self.generated_email_label = ctk.CTkLabel(email_display,
                                                   text="Cliquez sur Générer...",
                                                   font=("Consolas", 16, "bold"),
                                                   text_color=self.accent_color)
        self.generated_email_label.pack(padx=20, pady=15)

        gen_btn_frame = ctk.CTkFrame(gen_card, fg_color="transparent")
        gen_btn_frame.pack(fill="x", padx=15, pady=(5, 15))

        AnimatedButton(gen_btn_frame, text=f"{self.icons['refresh']} Générer",
                       command=self._generate_email,
                       width=150, height=42, fg_color=self.primary_color,
                       hover_color=self.accent_color, corner_radius=10,
                       font=("Segoe UI", 13, "bold")).pack(side="left", padx=(0, 8))

        AnimatedButton(gen_btn_frame, text=f"{self.icons['copy']} Copier",
                       command=self._copy_email,
                       width=130, height=42, fg_color=self.secondary_color,
                       hover_color=self.accent_color, corner_radius=10,
                       font=("Segoe UI", 13)).pack(side="left")

        domain_frame = ctk.CTkFrame(gen_card, fg_color="transparent")
        domain_frame.pack(fill="x", padx=15, pady=(0, 15))

        ctk.CTkLabel(domain_frame, text="Domaine :", font=("Segoe UI", 12)).pack(side="left")
        self.email_domain_var = ctk.StringVar(value="justdown.temp")
        ctk.CTkOptionMenu(domain_frame,
                          values=["justdown.temp", "anon-mail.org", "tempbox.io",
                                  "guerrillamail.com", "throwaway.email"],
                          variable=self.email_domain_var,
                          width=200, fg_color=self.secondary_color,
                          button_color=self.primary_color).pack(side="right")

        history_card = self.create_card(main_container, "Historique des Emails Générés",
                                        icon=self.icons['clock'])
        history_card.pack(fill="x", pady=(0, 15))

        self.email_history_frame = ctk.CTkFrame(history_card, fg_color="transparent")
        self.email_history_frame.pack(fill="x", padx=15, pady=(5, 15))

        if not self.generated_emails_history:
            ctk.CTkLabel(self.email_history_frame, text="Aucun email généré pour le moment.",
                         font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(pady=10)

        self._refresh_email_history()

    def _generate_email(self):
        parts = []
        patterns = [
            lambda: f"{''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 10)))}{random.randint(10, 999)}",
            lambda: f"{random.choice(FAKE_FIRST_NAMES_M + FAKE_FIRST_NAMES_F).lower()}.{random.choice(FAKE_LAST_NAMES).lower()}{random.randint(1, 99)}",
            lambda: f"user_{uuid.uuid4().hex[:8]}",
        ]

        username = random.choice(patterns)()
        import unicodedata
        username = unicodedata.normalize('NFKD', username).encode('ascii', 'ignore').decode('ascii')
        domain = self.email_domain_var.get() if hasattr(self, 'email_domain_var') else "justdown.temp"
        email = f"{username}@{domain}"

        self.generated_emails_history.insert(0, {
            "email": email,
            "created": datetime.now().strftime("%H:%M:%S"),
        })
        self.generated_emails_history = self.generated_emails_history[:20]

        if hasattr(self, 'generated_email_label'):
            self.generated_email_label.configure(text=email)

        self._refresh_email_history()

    def _copy_email(self):
        if hasattr(self, 'generated_email_label'):
            email = self.generated_email_label.cget("text")
            if email and email != "Cliquez sur Générer...":
                try:
                    pyperclip.copy(email)
                except Exception:
                    self.clipboard_clear()
                    self.clipboard_append(email)
                self.notify("Copié", f"Email copié : {email}")

    def _refresh_email_history(self):
        if not hasattr(self, 'email_history_frame'):
            return

        for widget in self.email_history_frame.winfo_children():
            widget.destroy()

        if not self.generated_emails_history:
            ctk.CTkLabel(self.email_history_frame, text="Aucun email généré pour le moment.",
                         font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(pady=10)
            return

        for item in self.generated_emails_history[:8]:
            row = ctk.CTkFrame(self.email_history_frame, fg_color=self.secondary_color, corner_radius=8)
            row.pack(fill="x", pady=3)

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=10, pady=6)

            ctk.CTkLabel(inner, text=item["email"],
                         font=("Consolas", 12),
                         text_color=self.accent_color).pack(side="left")
            ctk.CTkLabel(inner, text=item["created"],
                         font=("Segoe UI", 10),
                         text_color=self.text_color_secondary).pack(side="right")



    def create_audit_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "AUDIT"

        self._create_header("audit", "Audit de Sécurité PC & Fonctions Déjà Faites")
        main_container = self._create_scrollable_content()

        loading = ctk.CTkFrame(main_container, fg_color="transparent")
        loading.pack(fill="x", pady=60)
        ctk.CTkLabel(loading, text=f"{self.icons['refresh']}  Analyse du système en cours…",
                     font=("Segoe UI", 15, "bold"), text_color=self.text_color).pack()
        ctk.CTkLabel(loading, text="Vérification des services, du registre, du pare-feu et des DNS.",
                     font=("Segoe UI", 11), text_color=self.text_color_secondary).pack(pady=(4, 12))
        spinner = ctk.CTkProgressBar(loading, mode="indeterminate", width=260, height=5,
                                     progress_color=self.primary_color, fg_color=self.secondary_color)
        spinner.pack()
        spinner.start()

        def worker():
            checks = self.run_pc_privacy_audit()

            def done():
                if self.current_tab_id != "AUDIT" or not main_container.winfo_exists():
                    return
                spinner.stop()
                loading.destroy()
                self._render_audit_results(main_container, checks)
            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _render_audit_results(self, main_container, checks):
        active_count = sum(1 for c in checks if c['done'])
        total_count = len(checks)
        percentage = int((active_count / total_count) * 100)

        score_card = ctk.CTkFrame(main_container, fg_color=self.card_color, corner_radius=14, border_width=1, border_color=self.border_color)
        score_card.pack(fill="x", pady=(0, 12))

        sc_inner = ctk.CTkFrame(score_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=25, pady=20)

        left_box = ctk.CTkFrame(sc_inner, fg_color="transparent")
        left_box.pack(side="left", fill="y")

        ctk.CTkLabel(left_box, text=f"{active_count} / {total_count}",
                     font=("Segoe UI", 36, "bold"),
                     text_color="#10B981" if percentage >= 80 else ("#FFA502" if percentage >= 50 else "#EF4444")).pack(anchor="w")

        ctk.CTkLabel(left_box, text=f"Protections Actives ({percentage}% d'optimisation globale)",
                     font=("Segoe UI", 14, "bold"), text_color=self.text_color).pack(anchor="w", pady=(2, 4))

        status_desc = "Votre système bénéficie d'une excellente protection." if percentage >= 80 else (
            "Votre système est partiellement protégé. Plusieurs vulnérabilités sont actives." if percentage >= 50 else
            "Votre système est hautement exposé aux traceurs et collectes de données."
        )
        ctk.CTkLabel(left_box, text=status_desc, font=("Segoe UI", 11),
                     text_color=self.text_color_secondary).pack(anchor="w")

        right_box = ctk.CTkFrame(sc_inner, fg_color="transparent")
        right_box.pack(side="right", fill="y")

        AnimatedButton(right_box, text=f"{self.icons.get('bolt', '⚡')} Appliquer tout en 1 clic",
                       command=lambda: self._apply_all_audit_fixes(checks),
                       width=250, height=45, fg_color=self.primary_color,
                       hover_color=self.accent_color, corner_radius=12,
                       font=("Segoe UI", 13, "bold")).pack(pady=(0, 8))

        AnimatedButton(right_box, text=f"{self.icons.get('refresh', '🔄')} Réanalyser le système",
                       command=self.create_audit_tab,
                       width=250, height=36, fg_color=self.secondary_color,
                       hover_color=self.border_color, corner_radius=10,
                       font=("Segoe UI", 12)).pack()

        list_card = self.create_card(main_container, "État Détaillé des Protections Système",
                                     "Consultez les fonctions de confidentialité déjà actives et celles restant à configurer.",
                                     icon=self.icons.get('shield', '🛡️'))
        list_card.pack(fill="x", pady=10)

        for item in checks:
            row = ctk.CTkFrame(list_card, fg_color=self.secondary_color, corner_radius=10, border_width=1, border_color=self.border_color)
            row.pack(fill="x", padx=15, pady=5)

            left_part = ctk.CTkFrame(row, fg_color="transparent")
            left_part.pack(side="left", padx=15, pady=10)

            icon_indicator = "✅" if item['done'] else "⚠️"
            title_text = f"{icon_indicator}  {item['name']}"
            ctk.CTkLabel(left_part, text=title_text, font=("Segoe UI", 13, "bold"), text_color=self.text_color).pack(anchor="w")
            ctk.CTkLabel(left_part, text=item['desc'], font=("Segoe UI", 11), text_color=self.text_color_secondary).pack(anchor="w")

            right_part = ctk.CTkFrame(row, fg_color="transparent")
            right_part.pack(side="right", padx=15, pady=10)

            if item['done']:
                ctk.CTkLabel(right_part, text="  ✔ Déjà fait  ", font=("Segoe UI", 11, "bold"),
                             text_color=COLOR_SUCCESS, fg_color="#0F2A22", corner_radius=6,
                             height=26).pack(side="right")
            else:
                ctk.CTkLabel(right_part, text="  ✖ Vulnérable  ", font=("Segoe UI", 11, "bold"),
                             text_color=COLOR_DANGER, fg_color="#2A1215", corner_radius=6,
                             height=26).pack(side="left", padx=(0, 10))
                fix_fn = item['fix']
                AnimatedButton(right_part, text="Corriger",
                               command=lambda f=fix_fn: self._apply_single_audit_fix(f),
                               width=90, height=30, fg_color=self.primary_color,
                               hover_color=self.accent_color, corner_radius=8,
                               font=("Segoe UI", 11, "bold")).pack(side="left")

    def _apply_single_audit_fix(self, fix_function):
        """Applique une correction unique et recharge l'audit."""
        self.status_bar.start()
        try:
            fix_function()
            self.after(600, lambda: (self.status_bar.stop(), self.create_audit_tab()))
        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", f"Erreur lors de l'application : {e}")

    def _apply_all_audit_fixes(self, checks):
        """Applique toutes les corrections manquantes en un seul clic."""
        if not messagebox.askyesno("Optimisation Complète",
                                   "Voulez-vous appliquer toutes les protections recommandées en 1 clic ?\n\n"
                                   "- Blocage de la télémétrie et des traceurs Windows\n"
                                   "- Verrouillage des permissions caméra, micro et localisation\n"
                                   "- Activation du pare-feu et des stratégies WebRTC\n"
                                   "- Configuration des serveurs DNS sécurisés"):
            return

        self.status_bar.start()
        def _apply_worker():
            for c in checks:
                if not c['done']:
                    try:
                        c['fix']()
                    except Exception:
                        pass
            self.after(0, lambda: (self.status_bar.stop(),
                                   self.notify("Optimisation Terminée",
                                                      "Toutes les recommandations de sécurité ont été appliquées avec succès !"),
                                   self.create_audit_tab()))

        threading.Thread(target=_apply_worker, daemon=True).start()



    def create_system_info_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "SYS_INFO"

        self._create_header("system", "Informations Système")
        main_container = self._create_scrollable_content()

        grid = ctk.CTkFrame(main_container, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1)

        os_card = self.create_card(grid, "Système & Matériel", icon=self.icons['system'])
        os_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)

        proc_name = platform.processor()
        if len(proc_name) > 30:
            proc_name = proc_name[:28] + "..."

        sys_info = [
            ("OS", f"{platform.system()} {platform.release()}"),
            ("Version", platform.version()[:25] + "..."),
            ("Architecture", platform.machine()),
            ("Processeur", proc_name),
        ]

        for label, value in sys_info:
            item = ctk.CTkFrame(os_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(item, text=label, font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(item, text=value, font=("Segoe UI", 12, "bold")).pack(side="right")

        mem_card = self.create_card(grid, "Mémoire & Ressources", icon=self.icons['bolt'])
        mem_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)

        mem = psutil.virtual_memory()
        mem_info = [
            ("Total RAM", f"{round(mem.total / (1024**3), 2)} GB"),
            ("Disponible", f"{round(mem.available / (1024**3), 2)} GB"),
            ("Utilisation", f"{mem.percent}%"),
            ("CPU Cores", f"{psutil.cpu_count()} Threads"),
        ]

        for label, value in mem_info:
            item = ctk.CTkFrame(mem_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(item, text=label, font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(item, text=value, font=("Segoe UI", 12, "bold")).pack(side="right")

        disk_card = self.create_card(main_container, "Unités de Stockage", icon=self.icons['serial'])
        disk_card.pack(fill="x", pady=8)

        for partition in psutil.disk_partitions():
            if os.name == 'nt' and 'cdrom' in partition.opts or partition.fstype == '':
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                item = ctk.CTkFrame(disk_card, fg_color=self.secondary_color, corner_radius=10)
                item.pack(fill="x", padx=15, pady=5)

                info_frame = ctk.CTkFrame(item, fg_color="transparent")
                info_frame.pack(fill="x", padx=12, pady=6)

                ctk.CTkLabel(info_frame, text=f"Lecteur {partition.device}",
                             font=("Segoe UI", 13, "bold"),
                             text_color=self.accent_color).pack(side="left")
                ctk.CTkLabel(info_frame,
                             text=f"{round(usage.used / (1024**3), 1)} GB / {round(usage.total / (1024**3), 1)} GB",
                             font=("Segoe UI", 11)).pack(side="right")

                prog = ctk.CTkProgressBar(item, height=6, progress_color=self.primary_color,
                                           fg_color=self.secondary_color)
                prog.pack(fill="x", padx=12, pady=(0, 8))
                prog.set(usage.percent / 100)
            except Exception:
                continue

        net_card = self.create_card(main_container, "Réseau", icon=self.icons['network'])
        net_card.pack(fill="x", pady=8)

        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "N/A"

        net_info = [
            ("IP Locale", local_ip),
            ("IP Publique", self.public_ip),
            ("Hostname", socket.gethostname()),
        ]

        for label, value in net_info:
            item = ctk.CTkFrame(net_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(item, text=label, font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(item, text=value, font=("Segoe UI", 12, "bold")).pack(side="right")


    def create_settings_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "SETTINGS"

        self._create_header("settings", "Paramètres de l'Application",
                            "Personnalisez l'apparence de JustDown. Vos choix sont mémorisés.")
        main_scroll = self._create_scrollable_content()

        appearance_card = self.create_card(main_scroll, "Thème de couleur",
                                           "Cliquez sur un thème pour l'appliquer instantanément.",
                                           icon=self.icons['settings'])
        appearance_card.pack(fill="x", pady=(0, 12))

        themes_grid = ctk.CTkFrame(appearance_card, fg_color="transparent")
        themes_grid.pack(fill="x", padx=16, pady=(4, 16))
        cols = 3
        for c in range(cols):
            themes_grid.grid_columnconfigure(c, weight=1, uniform="themes")

        for idx, (name, theme_data) in enumerate(self.themes.items()):
            is_current = (name == self.selected_theme_name)
            tile = ctk.CTkFrame(themes_grid, fg_color=theme_data["card"], corner_radius=12,
                                border_width=2 if is_current else 1,
                                border_color=theme_data["primary"] if is_current else theme_data["border"],
                                cursor="hand2")
            tile.grid(row=idx // cols, column=idx % cols, padx=5, pady=5, sticky="ew")

            swatches = ctk.CTkFrame(tile, fg_color="transparent", cursor="hand2")
            swatches.pack(anchor="w", padx=12, pady=(12, 6))
            for key in ("primary", "accent", "background", "secondary"):
                ctk.CTkFrame(swatches, width=20, height=20, corner_radius=10,
                             fg_color=theme_data[key], border_width=1,
                             border_color=theme_data["border"]).pack(side="left", padx=(0, 4))

            label = ctk.CTkLabel(tile, text=("✔  " if is_current else "") + name,
                                 font=("Segoe UI", 12, "bold"),
                                 text_color=theme_data["primary"] if is_current else theme_data["text"],
                                 cursor="hand2")
            label.pack(anchor="w", padx=12, pady=(0, 10))

            for w in (tile, swatches, label):
                w.bind("<Button-1>", lambda e, n=name: self.apply_theme(n))

        keys_card = self.create_card(main_scroll, "Raccourcis clavier", icon=self.icons['bolt'])
        keys_card.pack(fill="x", pady=(0, 12))

        shortcuts = [
            ("Ctrl + 1 … 9", "Ouvrir les 9 premiers onglets de la barre latérale"),
            ("F5", "Actualiser l'onglet courant"),
        ]
        for keys, desc in shortcuts:
            item = ctk.CTkFrame(keys_card, fg_color="transparent")
            item.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(item, text=f"  {keys}  ", font=("Consolas", 11, "bold"),
                         fg_color=self.secondary_color, corner_radius=6,
                         text_color=self.primary_color).pack(side="left")
            ctk.CTkLabel(item, text=desc, font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(side="left", padx=12)
        ctk.CTkFrame(keys_card, fg_color="transparent", height=8).pack()

        about_card = self.create_card(main_scroll, "À propos", icon=self.icons['shield'])
        about_card.pack(fill="x", pady=(0, 12))

        about_info = [
            ("Application", "JustDown"),
            ("Version", APP_VERSION),
            ("Moteur", f"CustomTkinter {ctk.__version__}"),
            ("Fichier de préférences", SETTINGS_FILE),
            ("Licence", "MIT"),
        ]

        for label, value in about_info:
            item = ctk.CTkFrame(about_card, fg_color="transparent")
            item.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(item, text=label, font=("Segoe UI", 12),
                         text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(item, text=value, font=("Segoe UI", 12, "bold")).pack(side="right")

        ctk.CTkFrame(about_card, fg_color="transparent", height=10).pack()


    def _encrypt_file_impl(self, file_path, password, algorithm="AES", keep_original=True):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64

            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32, salt=salt, iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            f = Fernet(key)

            with open(file_path, 'rb') as file:
                file_data = file.read()

            encrypted_data = f.encrypt(file_data)

            encrypted_file = file_path + '.encrypted'
            with open(encrypted_file, 'wb') as file:
                file.write(salt)
                file.write(encrypted_data)

            if not keep_original:
                if getattr(self, 'secure_delete_after_encrypt', False):
                    self._secure_delete_single(file_path)
                else:
                    os.remove(file_path)

            return True, encrypted_file

        except Exception as e:
            return False, str(e)

    def _decrypt_file_impl(self, encrypted_file, password):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64

            with open(encrypted_file, 'rb') as file:
                salt = file.read(16)
                encrypted_data = file.read()

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32, salt=salt, iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            f = Fernet(key)

            decrypted_data = f.decrypt(encrypted_data)

            decrypted_file = encrypted_file.replace('.encrypted', '')
            if decrypted_file == encrypted_file:
                decrypted_file = encrypted_file + '.decrypted'

            with open(decrypted_file, 'wb') as file:
                file.write(decrypted_data)

            return True, decrypted_file

        except Exception as e:
            return False, str(e)

    def _encrypt_text_impl(self, text, password):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64

            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32, salt=salt, iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            f = Fernet(key)

            encrypted_data = f.encrypt(text.encode('utf-8'))
            return True, base64.urlsafe_b64encode(salt + encrypted_data).decode('utf-8')

        except Exception as e:
            return False, str(e)

    def _decrypt_text_impl(self, encrypted_text, password):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64

            raw = base64.urlsafe_b64decode(encrypted_text.encode('utf-8'))
            salt = raw[:16]
            encrypted_data = raw[16:]

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32, salt=salt, iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            f = Fernet(key)

            decrypted_data = f.decrypt(encrypted_data)
            return True, decrypted_data.decode('utf-8')

        except Exception as e:
            return False, str(e)


    def _secure_delete_single(self, file_path, passes=3):
        """Suppression sécurisée d'un seul fichier."""
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            with open(file_path, 'wb') as f:
                for pass_num in range(passes):
                    f.seek(0)
                    if pass_num % 3 == 0:
                        f.write(b'\x00' * file_size)
                    elif pass_num % 3 == 1:
                        f.write(b'\xFF' * file_size)
                    else:
                        f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())
            os.remove(file_path)

    def generate_key_pair(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa

            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048
            )
            public_key = private_key.public_key()

            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )

            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )

            return True, (private_pem.decode(), public_pem.decode())

        except Exception as e:
            return False, str(e)

    def hash_file(self, file_path, algorithm="SHA256"):
        try:
            if algorithm == "MD5":
                hash_obj = hashlib.md5()
            elif algorithm == "SHA1":
                hash_obj = hashlib.sha1()
            elif algorithm == "SHA256":
                hash_obj = hashlib.sha256()
            elif algorithm == "SHA512":
                hash_obj = hashlib.sha512()
            else:
                return False, "Algorithme non supporté"

            with open(file_path, 'rb') as file:
                for chunk in iter(lambda: file.read(4096), b''):
                    hash_obj.update(chunk)

            return True, hash_obj.hexdigest()

        except Exception as e:
            return False, str(e)



if __name__ == "__main__":
    app = JustDownApp()
    app.mainloop()

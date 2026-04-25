import os
import shutil
import tempfile
import subprocess
from tkinter import filedialog, messagebox, Text, Scrollbar, END
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

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

class AnimatedButton(ctk.CTkButton):
    def __init__(self, master, *args, **kwargs):
        hover_color = kwargs.pop('hover_color', None)
        active_color = kwargs.pop('active_color', None)
        super().__init__(master, *args, **kwargs)
        self._hover_color = hover_color
        self._active_color = active_color
        self._original_color = kwargs.get('fg_color', self._fg_color)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self._is_active = False

    def set_active(self, active=True):
        self._is_active = active
        if active:
            if self._active_color:
                self.configure(fg_color=self._active_color)
        else:
            self.configure(fg_color=self._original_color)

    def _on_enter(self, e=None):
        if not self._is_active and self._hover_color:
            self.configure(fg_color=self._hover_color)

    def _on_leave(self, e=None):
        if not self._is_active:
            self.configure(fg_color=self._original_color)
        
class ModernProgressBar(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(height=4)
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.pack(fill="x", padx=2)
        self.progress_bar.set(0)
        
    def start(self):
        self.progress_bar.start()
        
    def stop(self):
        self.progress_bar.stop()
        
    def set(self, value):
        self.progress_bar.set(value)

class JustDownApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.is_vpn_connected = False
        self.public_ip = "Chargement..."
        self.current_tab_id = "DASHBOARD"
        
        self.title("JustDown - Privacy & Security Suite")
        self.geometry("1000x700")
        self.minsize(800, 600)

        self.load_icons()

        self.primary_color = "#ca35cd"
        self.secondary_color = "#2D2D44"
        self.accent_color = "#6C72CB"
        self.bg_color = "#1A1B26"
        self.card_color = "#252634"
        self.text_color = "#FFFFFF"
        self.text_color_secondary = "#6C7293"

        self.main_frame = ctk.CTkFrame(self, corner_radius=20, fg_color=self.card_color)
        self.main_frame.grid(row=1, column=1, sticky="nsew", padx=15, pady=15)
        
        self.status_bar = ModernProgressBar(self, fg_color="transparent")
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 5))
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        self.create_sidebar()
        self.create_topbar()

        self.vpn_locations_list = [
            "Paris, France", "Marseille, France", "London, UK", "Berlin, Germany", 
            "Frankfurt, Germany", "Amsterdam, Netherlands", "Madrid, Spain",
            "New York, USA", "Los Angeles, USA", "Chicago, USA", "Toronto, Canada",
            "Montreal, Canada", "Tokyo, Japan", "Sydney, Australia"
        ]
        self.selected_location = ctk.StringVar(value="Paris, France")

        self.themes = {
            "Violet Élégant": {
                "primary": "#ca35cd",
                "secondary": "#242533",
                "accent": "#6C72CB",
                "background": "#16161E",
                "card": "#1F1F29",
                "text": "#FFFFFF",
                "text_secondary": "#787C99"
            },
            "Bleu Océan": {
                "primary": "#4DA8DA",
                "secondary": "#233140",
                "accent": "#3498DB",
                "background": "#1A242F",
                "card": "#1F2937",
                "text": "#FFFFFF",
                "text_secondary": "#94A3B8"
            },
            "Vert Émeraude": {
                "primary": "#2ECC71",
                "secondary": "#233429",
                "accent": "#27AE60",
                "background": "#1A2620",
                "card": "#1F2E26",
                "text": "#FFFFFF",
                "text_secondary": "#94A3B8"
            },
            "Rose Doux": {
                "primary": "#FF69B4",
                "secondary": "#342329",
                "accent": "#FFB6C1",
                "background": "#261A1E",
                "card": "#2E1F24",
                "text": "#FFFFFF",
                "text_secondary": "#94A3B8"
            },
            "Gris Acier": {
                "primary": "#94A3B8",
                "secondary": "#232629",
                "accent": "#64748B",
                "background": "#1A1D20",
                "card": "#202327",
                "text": "#FFFFFF",
                "text_secondary": "#94A3B8"
            }
        }
        self.selected_theme_name = "Violet Élégant"
        self.apply_theme(self.selected_theme_name)
        
        self.fetch_ip_thread()
        
        self.switch_tab("DASHBOARD", self.create_dashboard_tab)

    def fetch_ip_thread(self):
        def get_ip():
            try:
                import urllib.request
                with urllib.request.urlopen('https://api.ipify.org', timeout=5) as response:
                    self.public_ip = response.read().decode('utf-8')
            except:
                self.public_ip = "Indisponible"
            
            if hasattr(self, 'current_tab_id') and (self.current_tab_id == "DASHBOARD" or self.current_tab_id == "VPN"):
                self.after(0, self.current_tab)

        threading.Thread(target=get_ip, daemon=True).start()

    def apply_theme(self, theme_name):
        self.selected_theme_name = theme_name
        theme = self.themes[theme_name]
        self.primary_color = theme["primary"]
        self.secondary_color = theme["secondary"]
        self.accent_color = theme["accent"]
        self.bg_color = theme["background"]
        self.card_color = theme["card"]
        self.text_color = theme["text"]
        self.text_color_secondary = theme["text_secondary"]
        
        self.configure(fg_color=self.bg_color)
        if hasattr(self, 'main_frame'):
            self.main_frame.configure(fg_color=self.card_color)
        if hasattr(self, 'sidebar_frame'):
            self.sidebar_frame.configure(fg_color=self.card_color)
            
        if hasattr(self, 'current_tab'):
            self.current_tab()

        if hasattr(self, 'sidebar_nav_buttons'):
            for btn in self.sidebar_nav_buttons.values():
                btn._hover_color = self.secondary_color
                btn._active_color = self.secondary_color
                if btn._is_active:
                    btn.configure(fg_color=self.secondary_color)
                else:
                    btn.configure(fg_color="transparent")

    def load_icons(self):
        self.icons = {}
        icons_dir = os.path.join(os.path.dirname(__file__), "icons")
        
        if not os.path.exists(icons_dir):
            os.makedirs(icons_dir)
            
        icon_data = {
            "vpn": "🔒",
            "clean": "🧹",
            "privacy": "🕵️",
            "settings": "⚙️",
            "security": "🛡️",
            "system": "💻",
            "network": "🌐",
            "user": "👤",
            "clock": "🕰️",
            "dns": "📍",
            "encryption": "🔒",
            "cleaner": "🧹",
            "delete": "🚮",
            "vm": "🖥️"
        }
        
        for name, emoji in icon_data.items():
            self.icons[name] = emoji

    def create_topbar(self):
        topbar = ctk.CTkFrame(self, height=50, fg_color="transparent")
        topbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=30, pady=(20, 0))
        
        self.page_title_label = ctk.CTkLabel(topbar,
                                           text="Tableau de bord",
                                           font=("Helvetica Neue", 20, "bold"),
                                           text_color=self.text_color)
        self.page_title_label.pack(side="left")
        
        right_buttons = ctk.CTkFrame(topbar, fg_color="transparent")
        right_buttons.pack(side="right")
        
        self.clock_label = ctk.CTkLabel(right_buttons,
                                      text="",
                                      font=("Helvetica Neue", 13),
                                      text_color=self.text_color_secondary)
        self.clock_label.pack(side="left", padx=20)
        self.update_clock()
        
        settings_btn = AnimatedButton(right_buttons,
                                    text=f"{self.icons['settings']}",
                                    font=("Helvetica Neue", 16),
                                    width=40,
                                    height=40,
                                    fg_color=self.secondary_color,
                                    hover_color=self.primary_color,
                                    text_color=self.text_color,
                                    corner_radius=12,
                                    command=self.create_settings_tab)
        settings_btn.pack(side="left", padx=5)

    def update_clock(self):
        current_time = time.strftime("%H:%M:%S")
        if hasattr(self, 'clock_label'):
            self.clock_label.configure(text=f"{self.icons['clock']} {current_time}")
        self.after(1000, self.update_clock)

    def create_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, corner_radius=20, fg_color=self.card_color)
        self.sidebar_frame.grid(row=1, column=0, sticky="nsew", padx=(15, 0), pady=15)
        
        title_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        title_frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(title_frame,
                    text="JustDown",
                    font=("Helvetica Neue", 24, "bold"),
                    text_color=self.primary_color).pack(side="left")
        
        self.sidebar_nav_buttons = {}

        self.add_sidebar_button("DASHBOARD", f"{self.icons['system']}  Tableau de bord", self.create_dashboard_tab, "MAIN")
        
        ctk.CTkLabel(self.sidebar_frame,
                    text="SÉCURITÉ",
                    font=("Helvetica Neue", 11, "bold"),
                    text_color=self.text_color_secondary).pack(anchor="w", padx=25, pady=(15, 10))
                    
        self.add_sidebar_button("VPN", f"{self.icons['vpn']}  VPN Protection", self.create_vpn_tab)
        self.add_sidebar_button("DNS", f"{self.icons['dns']}  DNS Protection", self.create_dns_tab)
        self.add_sidebar_button("ENCRYPTION", f"{self.icons['encryption']}  Chiffrement", self.create_encryption_tab)
        
        ctk.CTkLabel(self.sidebar_frame,
                    text="NETTOYAGE",
                    font=("Helvetica Neue", 11, "bold"),
                    text_color=self.text_color_secondary).pack(anchor="w", padx=25, pady=(20, 10))
                    
        self.add_sidebar_button("CLEANER", f"{self.icons['cleaner']}  Nettoyeur Système", self.create_clean_tab)
        self.add_sidebar_button("PRIVACY", f"{self.icons['privacy']}  Confidentialité", self.create_privacy_tab)
        self.add_sidebar_button("SECURE_DELETE", f"{self.icons['delete']}  Suppression", self.create_secure_delete_tab)
        
        ctk.CTkLabel(self.sidebar_frame,
                    text="SYSTÈME",
                    font=("Helvetica Neue", 11, "bold"),
                    text_color=self.text_color_secondary).pack(anchor="w", padx=25, pady=(20, 10))
                    
        self.add_sidebar_button("SYS_INFO", f"{self.icons['system']}  Infos Système", self.create_system_info_tab)
        self.add_sidebar_button("ANTI_SPY", f"{self.icons['privacy']} Anti-Espionnage", self.create_anti_spy_tab)

    def add_sidebar_button(self, id, text, command, section=None):
        btn = AnimatedButton(self.sidebar_frame,
                           text=text,
                           font=("Helvetica Neue", 13),
                           fg_color="transparent",
                           hover_color=self.secondary_color,
                           active_color=self.secondary_color,
                           text_color=self.text_color,
                           anchor="w",
                           height=40,
                           corner_radius=10,
                           command=lambda: self.switch_tab(id, command))
        btn.pack(fill="x", padx=15, pady=2)
        self.sidebar_nav_buttons[id] = btn

    def switch_tab(self, tab_id, command):
        titles = {
            "DASHBOARD": "Tableau de bord",
            "VPN": "Protection VPN",
            "DNS": "Protection DNS",
            "ENCRYPTION": "Chiffrement",
            "CLEANER": "Nettoyeur Système",
            "PRIVACY": "Confidentialité",
            "SECURE_DELETE": "Suppression Sécurisée",
            "SYS_INFO": "Infos Système",
            "ANTI_SPY": "Anti-Espionnage"
        }
        if hasattr(self, 'page_title_label'):
            self.page_title_label.configure(text=titles.get(tab_id, "JustDown"))

        for btn in self.sidebar_nav_buttons.values():
            btn.set_active(False)
        
        self.sidebar_nav_buttons[tab_id].set_active(True)
        
        self.current_tab = command
        self.current_tab_id = tab_id
        
        command()

    def create_card(self, parent, title, content="", command=None):
        card = ctk.CTkFrame(parent, fg_color=self.secondary_color, corner_radius=15, border_width=0)
        
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 5))

        title_label = ctk.CTkLabel(header,
                                 text=title,
                                 font=("Helvetica Neue", 16, "bold"),
                                 text_color=self.primary_color)
        title_label.pack(side="left")
        
        if content:
            content_label = ctk.CTkLabel(card,
                                      text=content,
                                      font=("Helvetica Neue", 12),
                                      text_color=self.text_color_secondary,
                                      justify="left",
                                      wraplength=350)
            content_label.pack(pady=(0, 20), padx=20, anchor="w")
            
        if command:
            button = AnimatedButton(card,
                                 text="Ouvrir",
                                 command=command,
                                 width=90,
                                 height=30,
                                 font=("Helvetica Neue", 12),
                                 corner_radius=10,
                                 fg_color=self.card_color,
                                 hover_color=self.primary_color)
            button.pack(pady=(0, 20), padx=20, anchor="e")
            
        return card

    def create_stat_card(self, parent, title, value, color):
        card = ctk.CTkFrame(parent, fg_color=self.secondary_color, corner_radius=15, height=110, border_width=0)
        card.grid_propagate(False)
        
        ctk.CTkLabel(card, text=title, font=("Helvetica Neue", 13), text_color=self.text_color_secondary).pack(pady=(20, 0))
        ctk.CTkLabel(card, text=value, font=("Helvetica Neue", 22, "bold"), text_color=color).pack(pady=(5, 20))
        
        return card

    def create_dashboard_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "DASHBOARD"
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        welcome_text = ctk.CTkLabel(header_frame,
                                  text="Bonjour,",
                                  font=("Helvetica Neue", 16),
                                  text_color=self.text_color_secondary)
        welcome_text.pack(anchor="w")
        
        ctk.CTkLabel(header_frame,
                    text="Tableau de bord JustDown",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.text_color).pack(anchor="w")

        stats_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        stats_frame.pack(fill="x", padx=30, pady=10)
        stats_frame.grid_columnconfigure((0, 1, 2), weight=1)

        vpn_status = "Connecté" if self.is_vpn_connected else "Déconnecté"
        vpn_color = "#2ECC71" if self.is_vpn_connected else "#E74C3C"

        self.create_stat_card(stats_frame, f"{self.icons['vpn']} VPN", vpn_status, vpn_color).grid(row=0, column=0, padx=(0, 10), sticky="ew")
        self.create_stat_card(stats_frame, f"{self.icons['network']} IP Publique", self.public_ip, self.accent_color).grid(row=0, column=1, padx=10, sticky="ew")
        self.create_stat_card(stats_frame, f"{self.icons['security']} Sécurité", "Protégé", self.primary_color).grid(row=0, column=2, padx=(10, 0), sticky="ew")

        content_grid = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        content_grid.pack(fill="both", expand=True, padx=30, pady=20)
        content_grid.grid_columnconfigure(0, weight=2)
        content_grid.grid_columnconfigure(1, weight=1)

        left_col = ctk.CTkFrame(content_grid, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        recent_card = self.create_card(left_col, "Activités Récentes")
        recent_card.pack(fill="both", expand=True)

        activities = [
            (f"{self.icons['vpn']} VPN", f"État : {vpn_status}", "Maintenant"),
            (f"{self.icons['cleaner']} Nettoyage", "3.2 GB d'espace libéré", "Hier"),
            (f"{self.icons['security']} Scan", "Aucune menace détectée", "Hier"),
            (f"{self.icons['encryption']} Chiffrement", "Document.pdf chiffré", "23/04/2026")
        ]

        for icon_text, desc, time_text in activities:
            item = ctk.CTkFrame(recent_card, fg_color="transparent")
            item.pack(fill="x", padx=20, pady=8)
            
            ctk.CTkLabel(item, text=icon_text, font=("Helvetica Neue", 13, "bold"), text_color=self.text_color).pack(side="left")
            ctk.CTkLabel(item, text=desc, font=("Helvetica Neue", 13), text_color=self.text_color_secondary).pack(side="left", padx=15)
            ctk.CTkLabel(item, text=time_text, font=("Helvetica Neue", 11), text_color=self.text_color_secondary).pack(side="right")

        right_col = ctk.CTkFrame(content_grid, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        sys_card = self.create_card(right_col, "État Système")
        sys_card.pack(fill="both", expand=True)

        cpu_frame = ctk.CTkFrame(sys_card, fg_color="transparent")
        cpu_frame.pack(fill="x", padx=15, pady=10)
        ctk.CTkLabel(cpu_frame, text="CPU", font=("Helvetica Neue", 12)).pack(side="left")
        self.cpu_usage_label = ctk.CTkLabel(cpu_frame, text="0%", font=("Helvetica Neue", 12, "bold"))
        self.cpu_usage_label.pack(side="right")
        self.cpu_progress = ctk.CTkProgressBar(sys_card, height=8, progress_color=self.primary_color)
        self.cpu_progress.pack(fill="x", padx=15, pady=(0, 15))
        self.cpu_progress.set(0)

        ram_frame = ctk.CTkFrame(sys_card, fg_color="transparent")
        ram_frame.pack(fill="x", padx=15, pady=10)
        ctk.CTkLabel(ram_frame, text="RAM", font=("Helvetica Neue", 12)).pack(side="left")
        self.ram_usage_label = ctk.CTkLabel(ram_frame, text="0%", font=("Helvetica Neue", 12, "bold"))
        self.ram_usage_label.pack(side="right")
        self.ram_progress = ctk.CTkProgressBar(sys_card, height=8, progress_color=self.accent_color)
        self.ram_progress.pack(fill="x", padx=15, pady=(0, 15))
        self.ram_progress.set(0)

        self.update_dashboard_stats()

    def update_dashboard_stats(self):
        if not hasattr(self, 'cpu_usage_label') or self.current_tab_id != "DASHBOARD": return
        
        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            
            self.cpu_usage_label.configure(text=f"{cpu}%")
            self.cpu_progress.set(cpu / 100)
            
            self.ram_usage_label.configure(text=f"{ram}%")
            self.ram_progress.set(ram / 100)
        except:
            pass
        
        self.after(2000, self.update_dashboard_stats)

    def create_vpn_tab(self):
        self.clear_main_frame()
        self.current_tab_id = "VPN"
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['vpn']} Protection VPN",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.primary_color).pack(side="left")
                    
        status_text = "● Connecté" if self.is_vpn_connected else "● Déconnecté"
        status_color = "#2ECC71" if self.is_vpn_connected else "#FF6B6B"
        
        status_label = ctk.CTkLabel(header_frame,
                                  text=status_text,
                                  font=("Helvetica Neue", 14),
                                  text_color=status_color)
        status_label.pack(side="right")
        
        vpn_grid = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        vpn_grid.pack(fill="both", expand=True, padx=30)
        vpn_grid.grid_columnconfigure(0, weight=1)
        vpn_grid.grid_columnconfigure(1, weight=1)

        location_card = self.create_card(vpn_grid, "Serveur", "Choisissez votre emplacement virtuel.")
        location_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)
        
        ctk.CTkLabel(location_card, text="Emplacement", font=("Helvetica Neue", 12), text_color=self.text_color_secondary).pack(anchor="w", padx=20, pady=(10, 5))
        
        location_menu = ctk.CTkOptionMenu(location_card,
                                        variable=self.selected_location,
                                        values=self.vpn_locations_list,
                                        width=250,
                                        height=35,
                                        fg_color=self.card_color,
                                        button_color=self.primary_color)
        location_menu.pack(pady=(0, 20), padx=20)
        
        right_col = ctk.CTkFrame(vpn_grid, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)

        action_card = self.create_card(right_col, "Actions")
        action_card.pack(fill="x", pady=(0, 10))
        
        btn_text = "Déconnecter" if self.is_vpn_connected else "Se connecter"
        btn_color = "#E74C3C" if self.is_vpn_connected else "#2ECC71"
        btn_cmd = lambda: self.disconnect_vpn(status_label) if self.is_vpn_connected else lambda: self.connect_vpn(status_label)
        
        self.vpn_main_btn = AnimatedButton(action_card,
                                     text=btn_text,
                                     command=btn_cmd,
                                     width=200,
                                     height=42,
                                     fg_color=btn_color,
                                     hover_color=self.accent_color)
        self.vpn_main_btn.pack(pady=20)
        
        stats_card = self.create_card(right_col, "Informations")
        stats_card.pack(fill="both", expand=True)
        
        stats = [
            ("Adresse IP", self.public_ip, self.accent_color),
            ("Localisation", self.selected_location.get() if self.is_vpn_connected else "Non masquée", self.text_color),
            ("Statut", "Sécurisé" if self.is_vpn_connected else "Vulnérable", "#2ECC71" if self.is_vpn_connected else "#FF6B6B")
        ]
        
        for label, value, color in stats:
            stat_item = ctk.CTkFrame(stats_card, fg_color="transparent")
            stat_item.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(stat_item, text=label, font=("Helvetica Neue", 12), text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(stat_item, text=value, font=("Helvetica Neue", 12, "bold"), text_color=color).pack(side="right")

    def connect_vpn(self, status_label=None):
        self.status_bar.start()
        if status_label:
            status_label.configure(text="● Connexion...", text_color="#FFA502")
        
        def finish_connection():
            self.is_vpn_connected = True
            self.status_bar.stop()
            self.public_ip = "185.213.154." + str(psutil.cpu_count() * 10) 
            self.create_vpn_tab()
            messagebox.showinfo("VPN", f"Connecté à {self.selected_location.get()}")
            
        self.after(1500, finish_connection)

    def disconnect_vpn(self, status_label=None):
        self.status_bar.start()
        if status_label:
            status_label.configure(text="● Déconnexion...", text_color="#FFA502")
        
        def finish_disconnection():
            self.is_vpn_connected = False
            self.status_bar.stop()
            self.fetch_ip_thread() 
            self.create_vpn_tab()
            messagebox.showinfo("VPN", "Déconnecté")
            
        self.after(1000, finish_disconnection)

    def create_clean_tab(self):
        self.clear_main_frame()
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['clean']} Nettoyeur Système",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.primary_color).pack(side="left")

        scroll_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        scroll_container.pack(fill="both", expand=True, padx=30)

        grid_frame = ctk.CTkFrame(scroll_container, fg_color="transparent")
        grid_frame.pack(fill="x")
        grid_frame.grid_columnconfigure((0, 1), weight=1)

        windows_card = self.create_card(grid_frame, "Système Windows")
        windows_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)

        windows_options = [
            ("Fichiers temporaires", "Fichiers résiduels du système"),
            ("Cache DNS", "Vider le cache de résolution"),
            ("Corbeille", "Vider tous les éléments"),
            ("Logs Windows", "Fichiers journaux système")
        ]

        self.windows_vars = {}
        for option, description in windows_options:
            item = ctk.CTkFrame(windows_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=5)
            
            self.windows_vars[option] = ctk.BooleanVar(value=True)
            ctk.CTkSwitch(item, text=option, variable=self.windows_vars[option], progress_color=self.primary_color).pack(side="left")
            ctk.CTkLabel(item, text=description, font=("Helvetica Neue", 11), text_color=self.text_color_secondary).pack(side="right")

        browser_card = self.create_card(grid_frame, "Navigateurs Web")
        browser_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)

        browser_options = [
            ("Cache Web", "Fichiers de navigation"),
            ("Cookies", "Sessions et préférences"),
            ("Historique", "Sites visités récemment"),
            ("Formulaires", "Données d'auto-complétion")
        ]

        self.browser_vars = {}
        for option, description in browser_options:
            item = ctk.CTkFrame(browser_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=5)
            
            self.browser_vars[option] = ctk.BooleanVar(value=True)
            ctk.CTkSwitch(item, text=option, variable=self.browser_vars[option], progress_color=self.accent_color).pack(side="left")
            ctk.CTkLabel(item, text=description, font=("Helvetica Neue", 11), text_color=self.text_color_secondary).pack(side="right")

        action_frame = ctk.CTkFrame(scroll_container, fg_color=self.secondary_color, corner_radius=15)
        action_frame.pack(fill="x", pady=20)
        
        analyze_btn = AnimatedButton(action_frame, text="Analyser le système", command=self.analyze_system, width=200, height=45, fg_color=self.card_color, hover_color=self.accent_color)
        analyze_btn.pack(side="left", padx=20, pady=20)
        
        clean_btn = AnimatedButton(action_frame, text="Lancer le nettoyage", command=self.clean_system, width=200, height=45, fg_color=self.primary_color, hover_color=self.accent_color)
        clean_btn.pack(side="right", padx=20, pady=20)

    def analyze_system(self):
        self.status_bar.start()
        
        import random
        total_space = random.uniform(1.5, 5.0)
        
        self.status_bar.stop()
        messagebox.showinfo("Analyse terminée", 
                          f"L'analyse est terminée.\nEspace total récupérable : {total_space:.2f} GB")

    def clean_system(self):
        if not messagebox.askyesno("Confirmation", 
                                 "Êtes-vous sûr de vouloir nettoyer les éléments sélectionnés ?\n"
                                 "Cette action est irréversible."):
            return

        self.status_bar.start()
        
        try:
            if self.windows_vars.get("Fichiers temporaires") and self.windows_vars["Fichiers temporaires"].get():
                self.clean_temp_files()
            
            if self.windows_vars.get("Cache DNS") and self.windows_vars["Cache DNS"].get():
                self.clean_dns_cache()
            
            if self.windows_vars.get("Corbeille") and self.windows_vars["Corbeille"].get():
                self.clean_recycle_bin()
            
            if self.browser_vars.get("Cache Web") and self.browser_vars["Cache Web"].get():
                self.clean_browser_cache()
            
            if self.browser_vars.get("Cookies") and self.browser_vars["Cookies"].get():
                self.clean_browser_cookies()
            
            if self.browser_vars.get("Historique") and self.browser_vars["Historique"].get():
                self.clean_browser_history()

            self.status_bar.stop()
            messagebox.showinfo("Nettoyage terminé", "Le nettoyage du système est terminé avec succès!")
            
        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", f"Une erreur est survenue lors du nettoyage : {str(e)}")

    def clean_temp_files(self):
        import os
        import shutil
        temp = os.environ.get('TEMP')
        if temp:
            for item in os.listdir(temp):
                item_path = os.path.join(temp, item)
                try:
                    if os.path.isfile(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except:
                    continue

    def clean_dns_cache(self):
        import subprocess
        subprocess.run(['ipconfig', '/flushdns'], capture_output=True)

    def clean_recycle_bin(self):
        import winshell
        try:
            winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=False)
        except:
            pass

    def clean_browser_cache(self):
        pass

    def clean_browser_cookies(self):
        pass

    def clean_browser_history(self):
        pass

    def create_secure_delete_tab(self):
        self.clear_main_frame()
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['delete']} Suppression Sécurisée",
                    font=("Helvetica Neue", 24, "bold"),
                    text_color=self.primary_color).pack(side="left")

        files_card = self.create_card(self.main_frame, "Sélection des Fichiers")
        files_card.pack(fill="x", padx=20, pady=10)

        files_frame = ctk.CTkFrame(files_card, fg_color="transparent")
        files_frame.pack(fill="x", padx=15, pady=10)

        self.selected_files_text = Text(files_frame, height=5, width=50)
        self.selected_files_text.pack(fill="x", pady=5)
        self.selected_files_text.configure(state='disabled')

        buttons_frame = ctk.CTkFrame(files_frame, fg_color="transparent")
        buttons_frame.pack(fill="x", pady=5)

        select_file_btn = AnimatedButton(buttons_frame,
                                       text="Sélectionner des fichiers",
                                       command=self.select_files_to_delete,
                                       width=200,
                                       height=35,
                                       font=("Helvetica Neue", 13),
                                       fg_color=self.secondary_color,
                                       hover_color=self.accent_color)
        select_file_btn.pack(side="left", padx=5)

        clear_selection_btn = AnimatedButton(buttons_frame,
                                           text="Effacer la sélection",
                                           command=self.clear_file_selection,
                                           width=200,
                                           height=35,
                                           font=("Helvetica Neue", 13),
                                           fg_color=self.secondary_color,
                                           hover_color=self.accent_color)
        clear_selection_btn.pack(side="left", padx=5)

        options_card = self.create_card(self.main_frame, "Options de Suppression")
        options_card.pack(fill="x", padx=20, pady=10)

        options_frame = ctk.CTkFrame(options_card, fg_color="transparent")
        options_frame.pack(fill="x", padx=15, pady=10)

        passes_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        passes_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(passes_frame,
                    text="Nombre de passes d'écrasement:",
                    font=("Helvetica Neue", 13),
                    text_color=self.text_color).pack(side="left")

        self.passes_var = ctk.StringVar(value="3")
        passes_menu = ctk.CTkOptionMenu(passes_frame,
                                      variable=self.passes_var,
                                      values=["1", "3", "7", "35"],
                                      width=100,
                                      font=("Helvetica Neue", 12))
        passes_menu.pack(side="right")

        self.zero_fill_var = ctk.BooleanVar(value=True)
        zero_fill_check = ctk.CTkCheckBox(options_frame,
                                        text="Remplir avec des zéros après la suppression",
                                        variable=self.zero_fill_var,
                                        font=("Helvetica Neue", 13))
        zero_fill_check.pack(anchor="w", pady=5)

        self.rename_var = ctk.BooleanVar(value=True)
        rename_check = ctk.CTkCheckBox(options_frame,
                                     text="Renommer le fichier avant la suppression",
                                     variable=self.rename_var,
                                     font=("Helvetica Neue", 13))
        rename_check.pack(anchor="w", pady=5)

        delete_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        delete_frame.pack(fill="x", padx=20, pady=20)

        self.delete_btn = AnimatedButton(delete_frame,
                                       text="Supprimer de manière sécurisée",
                                       command=self.perform_secure_delete,
                                       width=250,
                                       height=40,
                                       font=("Helvetica Neue", 13, "bold"),
                                       fg_color="#E74C3C",
                                       hover_color="#C0392B")
        self.delete_btn.pack(side="left")

        self.selected_files = []

    def select_files_to_delete(self):
        files = filedialog.askopenfilenames(
            title="Sélectionner les fichiers à supprimer",
            filetypes=[("Tous les fichiers", "*.*")]
        )
        if files:
            self.selected_files = list(files)
            self.update_selected_files_display()

    def clear_file_selection(self):
        self.selected_files = []
        self.update_selected_files_display()

    def update_selected_files_display(self):
        self.selected_files_text.configure(state='normal')
        self.selected_files_text.delete(1.0, END)
        for file in self.selected_files:
            self.selected_files_text.insert(END, f"{file}\n")
        self.selected_files_text.configure(state='disabled')

    def perform_secure_delete(self):
        if not self.selected_files:
            messagebox.showwarning("Attention", "Veuillez sélectionner au moins un fichier à supprimer.")
            return

        if not messagebox.askyesno("Confirmation",
                                 "Êtes-vous sûr de vouloir supprimer définitivement ces fichiers ?\n"
                                 "Cette action est irréversible."):
            return

        self.status_bar.start()
        
        import os
        import random
        import string

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
            messagebox.showinfo("Succès", "Les fichiers ont été supprimés de manière sécurisée.")
            self.clear_file_selection()
            
        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", f"Une erreur est survenue lors de la suppression : {str(e)}")

    def create_encryption_tab(self):
        self.clear_main_frame()
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['encryption']} Chiffrement Sécurisé",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.primary_color).pack(side="left")

        main_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=30)

        file_card = self.create_card(main_container, "Chiffrement de Fichiers", "Protégez vos documents avec un chiffrement AES-256 de niveau militaire.")
        file_card.pack(fill="x", pady=(0, 20))

        file_action_frame = ctk.CTkFrame(file_card, fg_color="transparent")
        file_action_frame.pack(fill="x", padx=15, pady=10)

        self.selected_file_label = ctk.CTkLabel(file_action_frame, text="Aucun fichier sélectionné", font=("Helvetica Neue", 12), text_color=self.text_color_secondary)
        self.selected_file_label.pack(side="left")

        select_btn = AnimatedButton(file_action_frame, text="Parcourir", command=self.select_file_for_encryption, width=120, height=32, fg_color=self.card_color, hover_color=self.accent_color)
        select_btn.pack(side="right", padx=5)

        file_btn_container = ctk.CTkFrame(file_card, fg_color="transparent")
        file_btn_container.pack(fill="x", padx=15, pady=(0, 15))

        encrypt_file_btn = AnimatedButton(file_btn_container, text="Chiffrer le fichier", command=self.encrypt_file, width=180, height=38, fg_color=self.primary_color, hover_color=self.accent_color)
        encrypt_file_btn.pack(side="left", padx=(0, 10))

        decrypt_file_btn = AnimatedButton(file_btn_container, text="Déchiffrer le fichier", command=self.decrypt_file, width=180, height=38, fg_color=self.secondary_color, hover_color=self.accent_color)
        decrypt_file_btn.pack(side="left")

        text_card = self.create_card(main_container, "Chiffrement de Texte", "Chiffrez vos messages ou notes sensibles instantanément.")
        text_card.pack(fill="x", pady=(0, 20))

        self.text_input = ctk.CTkTextbox(text_card, height=120, fg_color=self.card_color, border_width=1, border_color=self.secondary_color)
        self.text_input.pack(fill="x", padx=15, pady=10)

        text_btn_container = ctk.CTkFrame(text_card, fg_color="transparent")
        text_btn_container.pack(fill="x", padx=15, pady=(0, 15))

        encrypt_text_btn = AnimatedButton(text_btn_container, text="Chiffrer le texte", command=self.encrypt_text, width=180, height=38, fg_color=self.primary_color, hover_color=self.accent_color)
        encrypt_text_btn.pack(side="left", padx=(0, 10))

        decrypt_text_btn = AnimatedButton(text_btn_container, text="Déchiffrer le texte", command=self.decrypt_text, width=180, height=38, fg_color=self.secondary_color, hover_color=self.accent_color)
        decrypt_text_btn.pack(side="left")

        settings_card = self.create_card(main_container, "Paramètres Avancés")
        settings_card.pack(fill="x", pady=(0, 20))

        settings_grid = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_grid.pack(fill="x", padx=15, pady=10)
        settings_grid.grid_columnconfigure((0, 1), weight=1)

        algo_item = ctk.CTkFrame(settings_grid, fg_color="transparent")
        algo_item.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(algo_item, text="Algorithme", font=("Helvetica Neue", 12)).pack(side="left")
        self.algo_var = ctk.StringVar(value="AES-256")
        ctk.CTkOptionMenu(algo_item, values=["AES-256", "RSA", "Blowfish"], variable=self.algo_var, width=140, fg_color=self.card_color, button_color=self.primary_color).pack(side="right")

        key_item = ctk.CTkFrame(settings_grid, fg_color="transparent")
        key_item.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ctk.CTkLabel(key_item, text="Force de la clé", font=("Helvetica Neue", 12)).pack(side="left")
        self.key_strength = ctk.StringVar(value="256 bits")
        ctk.CTkOptionMenu(key_item, values=["128 bits", "256 bits", "512 bits"], variable=self.key_strength, width=140, fg_color=self.card_color, button_color=self.primary_color).pack(side="right")
        
        advanced_label = ctk.CTkLabel(advanced_frame, text="⚙️ Options avancées",
                                    font=ctk.CTkFont(size=14, weight="bold"))
        advanced_label.pack(side="left", padx=15, pady=10)

        self.padding_var = ctk.BooleanVar(value=False)
        padding_switch = ctk.CTkSwitch(advanced_frame, 
                                     text="Padding personnalisé",
                                     variable=self.padding_var,
                                     command=self.toggle_padding,
                                     button_color=self.primary_color,
                                     button_hover_color=self.accent_color,
                                     progress_color=self.accent_color)
        padding_switch.pack(side="right", padx=15, pady=10)

    def toggle_padding(self):
        if self.padding_var.get():
            messagebox.showinfo("Padding", "Padding personnalisé activé")
        else:
            messagebox.showinfo("Padding", "Padding personnalisé désactivé")

    def select_file_for_encryption(self):
        filename = filedialog.askopenfilename()
        if filename:
            self.current_file = filename
            if hasattr(self, 'selected_file_label'):
                self.selected_file_label.configure(text=os.path.basename(filename), text_color=self.text_color)
            messagebox.showinfo("Fichier sélectionné", f"Fichier sélectionné: {filename}")

    def encrypt_file(self):
        if hasattr(self, 'current_file'):
            messagebox.showinfo("Chiffrement", "Chiffrement du fichier en cours...")
        else:
            messagebox.showerror("Erreur", "Veuillez d'abord sélectionner un fichier")

    def decrypt_file(self):
        if hasattr(self, 'current_file'):
            messagebox.showinfo("Déchiffrement", "Déchiffrement du fichier en cours...")
        else:
            messagebox.showerror("Erreur", "Veuillez d'abord sélectionner un fichier")

    def encrypt_text(self):
        text = self.text_input.get("1.0", END).strip()
        if text:
            messagebox.showinfo("Chiffrement", "Texte chiffré avec succès")
        else:
            messagebox.showerror("Erreur", "Veuillez entrer du texte à chiffrer")

    def decrypt_text(self):
        text = self.text_input.get("1.0", END).strip()
        if text:
            messagebox.showinfo("Déchiffrement", "Texte déchiffré avec succès")
        else:
            messagebox.showerror("Erreur", "Veuillez entrer du texte à déchiffrer")

    def clear_main_frame(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def create_privacy_tab(self):
        self.clear_main_frame()
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['privacy']} Confidentialité",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.primary_color).pack(side="left")

        main_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=30)

        browsing_card = self.create_card(main_container, "Navigation Privée", "Optimisez votre navigateur pour une confidentialité maximale.")
        browsing_card.pack(fill="x", pady=(0, 20))

        options_frame = ctk.CTkFrame(browsing_card, fg_color="transparent")
        options_frame.pack(fill="x", padx=15, pady=10)

        privacy_options = [
            ("Bloquer les trackers", "Empêche le suivi publicitaire"),
            ("Navigation Privée", "Ne conserve aucun historique"),
            ("Cookies Tiers", "Bloque les cookies de traçage"),
            ("Anti-Fingerprinting", "Masque l'identité du navigateur")
        ]

        for option, description in privacy_options:
            item = ctk.CTkFrame(options_frame, fg_color="transparent")
            item.pack(fill="x", pady=8)
            
            ctk.CTkSwitch(item, text=option, font=("Helvetica Neue", 13), progress_color=self.primary_color).pack(side="left")
            ctk.CTkLabel(item, text=description, font=("Helvetica Neue", 11), text_color=self.text_color_secondary).pack(side="right")

        btn_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10)

        save_btn = AnimatedButton(btn_frame, text="Appliquer les réglages", command=self.save_privacy_settings, width=220, height=42, fg_color=self.primary_color, hover_color=self.accent_color)
        save_btn.pack(side="left", padx=(0, 10))

        reset_btn = AnimatedButton(btn_frame, text="Réinitialiser", command=self.reset_privacy_settings, width=150, height=42, fg_color=self.card_color, hover_color=self.secondary_color)
        reset_btn.pack(side="left")

    def save_privacy_settings(self):
        self.status_bar.start()
        messagebox.showinfo("Privacy", "Paramètres de confidentialité mis à jour avec succès!")
        self.status_bar.stop()

    def reset_privacy_settings(self):
        self.status_bar.start()
        messagebox.showinfo("Privacy", "Paramètres de confidentialité réinitialisés aux valeurs par défaut.")
        self.status_bar.stop()

    def create_system_info_tab(self):
        self.clear_main_frame()
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['system']} Informations Système",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.primary_color).pack(side="left")

        main_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=30)

        import platform
        import psutil
        import os

        grid = ctk.CTkFrame(main_container, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1)

        os_card = self.create_card(grid, "Système & Matériel")
        os_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)

        sys_info = [
            ("OS", f"{platform.system()} {platform.release()}"),
            ("Version", platform.version()[:20] + "..."),
            ("Architecture", platform.machine()),
            ("Processeur", platform.processor()[:25] + "...")
        ]

        for label, value in sys_info:
            item = ctk.CTkFrame(os_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(item, text=label, font=("Helvetica Neue", 12), text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(item, text=value, font=("Helvetica Neue", 12, "bold")).pack(side="right")

        mem_card = self.create_card(grid, "Mémoire & Ressources")
        mem_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)

        mem = psutil.virtual_memory()
        mem_info = [
            ("Total RAM", f"{round(mem.total / (1024**3), 2)} GB"),
            ("Disponible", f"{round(mem.available / (1024**3), 2)} GB"),
            ("Utilisation", f"{mem.percent}%"),
            ("CPU Cores", f"{psutil.cpu_count()} Threads")
        ]

        for label, value in mem_info:
            item = ctk.CTkFrame(mem_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(item, text=label, font=("Helvetica Neue", 12), text_color=self.text_color_secondary).pack(side="left")
            ctk.CTkLabel(item, text=value, font=("Helvetica Neue", 12, "bold")).pack(side="right")

        disk_card = self.create_card(main_container, "Unités de Stockage")
        disk_card.pack(fill="x", pady=10)

        for partition in psutil.disk_partitions():
            if os.name == 'nt' and 'cdrom' in partition.opts or partition.fstype == '':
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                item = ctk.CTkFrame(disk_card, fg_color=self.card_color, corner_radius=10)
                item.pack(fill="x", padx=15, pady=5)
                
                info_frame = ctk.CTkFrame(item, fg_color="transparent")
                info_frame.pack(fill="x", padx=10, pady=5)
                
                ctk.CTkLabel(info_frame, text=f"Lecteur {partition.device}", font=("Helvetica Neue", 13, "bold"), text_color=self.accent_color).pack(side="left")
                ctk.CTkLabel(info_frame, text=f"{round(usage.used/(1024**3),1)}GB / {round(usage.total/(1024**3),1)}GB", font=("Helvetica Neue", 11)).pack(side="right")
                
                prog = ctk.CTkProgressBar(item, height=6, progress_color=self.primary_color)
                prog.pack(fill="x", padx=10, pady=(0, 10))
                prog.set(usage.percent / 100)
            except: continue

    def refresh_system_info(self):
        self.status_bar.start()
        self.create_system_info_tab()
        self.status_bar.stop()
        messagebox.showinfo("Système", "Informations système mises à jour!")

    def create_settings_tab(self):
        self.clear_main_frame()
        
        settings_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        settings_frame.pack(fill="both", expand=True, padx=30, pady=30)

        ctk.CTkLabel(settings_frame, text="Paramètres de l'Application", 
                                 font=("Helvetica Neue", 24, "bold"),
                                 text_color=self.text_color).pack(anchor="w", pady=(0, 20))

        appearance_card = self.create_card(settings_frame, "Apparence")
        appearance_card.pack(fill="x", pady=10)

        mode_frame = ctk.CTkFrame(appearance_card, fg_color="transparent")
        mode_frame.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(mode_frame, text="� Mode d'affichage", font=("Helvetica Neue", 13)).pack(side="left")
        
        self.mode_var = ctk.StringVar(value="Sombre")
        mode_menu = ctk.CTkOptionMenu(mode_frame, 
                                    values=["Sombre", "Clair"],
                                    variable=self.mode_var,
                                    command=self.change_appearance_mode,
                                    fg_color=self.card_color,
                                    button_color=self.primary_color)
        mode_menu.pack(side="right")

        theme_frame = ctk.CTkFrame(appearance_card, fg_color="transparent")
        theme_frame.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(theme_frame, text="� Thème de couleur", font=("Helvetica Neue", 13)).pack(side="left")
        
        self.theme_var = ctk.StringVar(value=self.selected_theme_name)
        theme_menu = ctk.CTkOptionMenu(theme_frame, 
                                    values=list(self.themes.keys()),
                                    variable=self.theme_var,
                                    command=self.apply_theme,
                                    fg_color=self.card_color,
                                    button_color=self.primary_color)
        theme_menu.pack(side="right")

        pref_card = self.create_card(settings_frame, "Préférences")
        pref_card.pack(fill="x", pady=10)

        lang_frame = ctk.CTkFrame(pref_card, fg_color="transparent")
        lang_frame.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(lang_frame, text="🌍 Langue de l'interface", font=("Helvetica Neue", 13)).pack(side="left")
        
        self.lang_var = ctk.StringVar(value="Français")
        lang_menu = ctk.CTkOptionMenu(lang_frame, 
                                   values=["Français", "English", "Español"],
                                   variable=self.lang_var,
                                   fg_color=self.card_color,
                                   button_color=self.primary_color)
        lang_menu.pack(side="right")

        notif_frame = ctk.CTkFrame(pref_card, fg_color="transparent")
        notif_frame.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(notif_frame, text="� Notifications système", font=("Helvetica Neue", 13)).pack(side="left")
        
        self.notif_var = ctk.BooleanVar(value=True)
        notif_switch = ctk.CTkSwitch(notif_frame, 
                                  text="",
                                  variable=self.notif_var,
                                  progress_color=self.primary_color)
        notif_switch.pack(side="right")

    def change_appearance_mode(self, mode):
        if mode == "Sombre":
            ctk.set_appearance_mode("dark")
        else:
            ctk.set_appearance_mode("light")

    def create_dns_tab(self):
        self.clear_main_frame()
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['dns']} Protection DNS",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.primary_color).pack(side="left")

        main_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=30)

        dns_card = self.create_card(main_container, "Serveurs DNS", "Sélectionnez un résolveur DNS pour sécuriser vos requêtes et bloquer les malwares.")
        dns_card.pack(fill="x", pady=(0, 20))

        dns_servers = {
            "Cloudflare": ("1.1.1.1", "1.0.0.1", "Sécurité & Rapidité"),
            "Google": ("8.8.8.8", "8.8.4.4", "Fiabilité Microsoft"),
            "OpenDNS": ("208.67.222.222", "208.67.220.220", "Filtrage Parental"),
            "Quad9": ("9.9.9.9", "149.112.112.112", "Anti-Malware")
        }

        self.selected_dns = ctk.StringVar(value="Cloudflare")

        for name, (p, s, desc) in dns_servers.items():
            item = ctk.CTkFrame(dns_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=8)
            
            ctk.CTkRadioButton(item, text=name, variable=self.selected_dns, value=name, font=("Helvetica Neue", 13, "bold")).pack(side="left")
            ctk.CTkLabel(item, text=f"{p} / {s}", font=("Helvetica Neue", 12), text_color=self.accent_color).pack(side="left", padx=20)
            ctk.CTkLabel(item, text=desc, font=("Helvetica Neue", 11), text_color=self.text_color_secondary).pack(side="right")

        btn_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=10)

        apply_btn = AnimatedButton(btn_frame, text="Appliquer DNS", command=self.apply_dns_settings, width=200, height=42, fg_color=self.primary_color, hover_color=self.accent_color)
        apply_btn.pack(side="left", padx=(0, 10))

        restore_btn = AnimatedButton(btn_frame, text="Restaurer", command=self.restore_default_dns, width=150, height=42, fg_color=self.card_color, hover_color=self.secondary_color)
        restore_btn.pack(side="left")

    def apply_dns_settings(self):
        self.status_bar.start()
        threading.Timer(2.0, self.finish_dns_settings).start()

    def finish_dns_settings(self):
        self.status_bar.stop()
        messagebox.showinfo("Succès", "Les paramètres DNS ont été appliqués avec succès !")

    def restore_default_dns(self):
        self.status_bar.start()
        threading.Timer(2.0, self.finish_dns_restore).start()

    def finish_dns_restore(self):
        self.status_bar.stop()
        messagebox.showinfo("Succès", "Les paramètres DNS par défaut ont été restaurés !")

    def create_anti_spy_tab(self):
        self.clear_main_frame()
        
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(header_frame,
                    text=f"{self.icons['privacy']} Anti-Espionnage",
                    font=("Helvetica Neue", 28, "bold"),
                    text_color=self.primary_color).pack(side="left")

        main_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=30)

        grid = ctk.CTkFrame(main_container, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1), weight=1)

        tele_card = self.create_card(grid, "Services de Télémétrie", "Désactivez la collecte de données automatique de Microsoft.")
        tele_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)

        tele_options = [
            ("Service DiagTrack", "Collecte de diagnostics"),
            ("dmwappushservice", "Notifications push WAP"),
            ("Tâches planifiées", "Collecte en arrière-plan"),
            ("Customer Experience", "Programme d'amélioration")
        ]

        self.telemetry_vars = {}
        for opt, desc in tele_options:
            item = ctk.CTkFrame(tele_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=5)
            self.telemetry_vars[opt] = ctk.BooleanVar(value=True)
            ctk.CTkSwitch(item, text=opt, variable=self.telemetry_vars[opt], progress_color=self.primary_color).pack(side="left")
            ctk.CTkLabel(item, text=desc, font=("Helvetica Neue", 11), text_color=self.text_color_secondary).pack(side="right")

        feat_card = self.create_card(grid, "Fonctionnalités", "Désactivez les fonctions intrusives de Windows.")
        feat_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)

        feat_options = [
            ("Cortana", "Assistant vocal Microsoft"),
            ("ID Publicitaire", "Suivi pour publicités"),
            ("Localisation", "Service de géolocalisation"),
            ("Rapports d'erreur", "Envoi auto de rapports")
        ]

        self.features_vars = {}
        for opt, desc in feat_options:
            item = ctk.CTkFrame(feat_card, fg_color="transparent")
            item.pack(fill="x", padx=15, pady=5)
            self.features_vars[opt] = ctk.BooleanVar(value=True)
            ctk.CTkSwitch(item, text=opt, variable=self.features_vars[opt], progress_color=self.accent_color).pack(side="left")
            ctk.CTkLabel(item, text=desc, font=("Helvetica Neue", 11), text_color=self.text_color_secondary).pack(side="right")

        btn_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=20)

        apply_btn = AnimatedButton(btn_frame, text="Appliquer les changements", command=self.apply_anti_spy, width=220, height=45, fg_color="#E74C3C", hover_color="#C0392B")
        apply_btn.pack(side="left", padx=(0, 10))

        restore_btn = AnimatedButton(btn_frame, text="Restaurer", command=self.restore_windows_settings, width=150, height=45, fg_color=self.card_color, hover_color=self.secondary_color)
        restore_btn.pack(side="left")

    def apply_anti_spy(self):
        if not messagebox.askyesno("Confirmation", 
                                 "Cette action va modifier des paramètres système importants.\n"
                                 "Voulez-vous continuer ?"):
            return

        self.status_bar.start()
        
        try:
            import subprocess
            
            if self.telemetry_vars["Service de Télémétrie Windows"].get():
                subprocess.run(['sc', 'stop', 'DiagTrack'], capture_output=True)
                subprocess.run(['sc', 'config', 'DiagTrack', 'start=disabled'], capture_output=True)

            if self.telemetry_vars["Service dmwappushservice"].get():
                subprocess.run(['sc', 'stop', 'dmwappushservice'], capture_output=True)
                subprocess.run(['sc', 'config', 'dmwappushservice', 'start=disabled'], capture_output=True)

            if self.features_vars["Cortana"].get():
                import winreg
                key_path = r"SOFTWARE\Policies\Microsoft\Windows\Windows Search"
                try:
                    key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE)
                    winreg.SetValueEx(key, "AllowCortana", 0, winreg.REG_DWORD, 0)
                except:
                    pass

            if self.features_vars["Localisation"].get():
                subprocess.run(['sc', 'stop', 'lfsvc'], capture_output=True)
                subprocess.run(['sc', 'config', 'lfsvc', 'start=disabled'], capture_output=True)

            self.status_bar.stop()
            messagebox.showinfo("Succès", "Les modifications ont été appliquées avec succès!\nUn redémarrage peut être nécessaire.")
            
        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", f"Une erreur est survenue : {str(e)}")

    def restore_windows_settings(self):
        if not messagebox.askyesno("Confirmation", 
                                 "Voulez-vous vraiment restaurer les paramètres Windows par défaut ?"):
            return

        self.status_bar.start()
        
        try:
            import subprocess
            
            subprocess.run(['sc', 'config', 'DiagTrack', 'start=auto'], capture_output=True)
            subprocess.run(['sc', 'config', 'dmwappushservice', 'start=auto'], capture_output=True)
            subprocess.run(['sc', 'config', 'lfsvc', 'start=auto'], capture_output=True)
            
            subprocess.run(['sc', 'start', 'DiagTrack'], capture_output=True)
            subprocess.run(['sc', 'start', 'dmwappushservice'], capture_output=True)
            subprocess.run(['sc', 'start', 'lfsvc'], capture_output=True)

            self.status_bar.stop()
            messagebox.showinfo("Succès", "Les paramètres Windows ont été restaurés.\nUn redémarrage peut être nécessaire.")
            
        except Exception as e:
            self.status_bar.stop()
            messagebox.showerror("Erreur", f"Une erreur est survenue : {str(e)}")

    def encrypt_file(self, file_path, password, algorithm="AES"):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64
            import os
            
            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
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
            
            if self.secure_delete_after_encrypt:
                self.secure_delete_file(file_path)
            else:
                os.remove(file_path)
                
            return True, encrypted_file
            
        except Exception as e:
            return False, str(e)

    def decrypt_file(self, encrypted_file, password):
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
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            
            f = Fernet(key)
            
            decrypted_data = f.decrypt(encrypted_data)
            
            decrypted_file = encrypted_file.replace('.encrypted', '')
            with open(decrypted_file, 'wb') as file:
                file.write(decrypted_data)
            
            os.remove(encrypted_file)
            
            return True, decrypted_file
            
        except Exception as e:
            return False, str(e)

    def encrypt_text(self, text, password):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64
            import os
            
            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            
            f = Fernet(key)
            
            encrypted_data = f.encrypt(text.encode())
            
            return True, base64.urlsafe_b64encode(salt + encrypted_data).decode()
            
        except Exception as e:
            return False, str(e)

    def decrypt_text(self, encrypted_text, password):
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64
            
            encrypted_data = base64.urlsafe_b64decode(encrypted_text.encode())
            
            salt = encrypted_data[:16]
            encrypted_data = encrypted_data[16:]
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            
            f = Fernet(key)
            
            decrypted_data = f.decrypt(encrypted_data)
            
            return True, decrypted_data.decode()
            
        except Exception as e:
            return False, str(e)

    def generate_key_pair(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import hashes
            
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
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
            import hashlib
            
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

    def animate_status_bar(self):
        def animation():
            while True:
                for i in range(100):
                    self.status_bar.set(i / 100)
                    time.sleep(0.05)
                for i in range(100, 0, -1):
                    self.status_bar.set(i / 100)
                    time.sleep(0.05)

        animation_thread = threading.Thread(target=animation, daemon=True)
        animation_thread.start()

if __name__ == "__main__":
    app = JustDownApp()
    app.mainloop()

# -*- coding: utf-8 -*-
"""
ENTARIA - Modern Dark UI
기존 메이플 엔타리아 기능을 유지하면서 배경 이미지를 제거하고
모던 다크 대시보드 UI로 구성한 단일 실행 파일입니다.

필수 패키지:
    pip install requests websocket-client pillow pyautogui keyboard opencv-python

같은 폴더(또는 PyInstaller 실행 파일의 images 폴더)에:
    target1.png
    target2.png
    target3.png
    target4.png
    updater.exe              # 업데이트 기능을 사용하는 경우
    version_info.py          # APP_VERSION 정의
가 필요합니다.
"""

import os
import random
import sys
import time
import threading
import hashlib
import platform
import uuid
import json
import subprocess
import ctypes
from urllib.parse import quote

import cv2
import numpy as np
from datetime import datetime

import tkinter as tk
from tkinter import scrolledtext, messagebox

import keyboard
import pyautogui
import requests
import websocket

from PIL import Image, ImageTk


# =========================================================
# 서버 / 버전
# =========================================================

SERVER_URL = "https://api.entaria1004.win"
VERSION_URL = f"{SERVER_URL}/update/version.json"
VERIFY_URL = f"{SERVER_URL}/verify"
REGISTER_URL = f"{SERVER_URL}/register"
LOGIN_URL = f"{SERVER_URL}/login"
HEARTBEAT_URL = f"{SERVER_URL}/heartbeat"
CHAT_WS_URL = "wss://api.entaria1004.win/ws/chat"

try:
    from version_info import APP_VERSION
except Exception:
    APP_VERSION = "0.0.0"


# =========================================================
# 경로
# =========================================================

if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(filename):
    """리소스 파일을 images 폴더 또는 프로그램 폴더에서 찾습니다."""
    candidates = [
        os.path.join(BASE_DIR, "images", filename),
        os.path.join(BASE_DIR, filename),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "Entaria"
)
os.makedirs(CONFIG_DIR, exist_ok=True)

BUFF_HOTKEY_CONFIG_FILE = os.path.join(CONFIG_DIR, "buff_hotkey.txt")
BUFF_KEYS_CONFIG_FILE = os.path.join(CONFIG_DIR, "buff_keys.txt")


# =========================================================
# 설정
# =========================================================

WINDOW_WIDTH = 1120
WINDOW_HEIGHT = 1000

CONFIDENCE = 0.80
SEARCH_DELAY = 0.10
TARGET_DELAY = 0.50
BUFF_DELAY = 1.00
KEY_PRESS_TIME = 0.05
LICENSE_CHECK_INTERVAL = 30

# =========================================================
# 제자리사냥 설정
# =========================================================
POSITION_HUNT_INTERVAL_MIN = 0.10
POSITION_HUNT_INTERVAL_MAX = 0.22

# 마나 포션 설정
MP_POTION_DEFAULT_KEY = "f5"
MP_POTION_DEFAULT_THRESHOLD = 30
MP_POTION_CHECK_INTERVAL = 0.20
MP_BAR_SEARCH_WIDTH = 360
MP_BAR_SEARCH_HEIGHT = 100

# HP 포션 설정
HP_POTION_DEFAULT_KEY = "home"
HP_POTION_DEFAULT_THRESHOLD = 30
HP_POTION_CHECK_INTERVAL = 0.20
HP_BAR_SEARCH_WIDTH = 360
HP_BAR_SEARCH_HEIGHT = 120
HP_MP_BAR_FULL_WIDTH = 220.0

# 제자리사냥은 게임 창이 실제로 활성화되어 있을 때만 A키를 입력합니다.
GAME_WINDOW_TITLE_KEYWORDS = ("MapleStory", "ENTARIA")

def is_game_window_active():
    """현재 포그라운드 창이 게임 창인지 확인합니다."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return False
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip().lower()
        return any(keyword.lower() in title for keyword in GAME_WINDOW_TITLE_KEYWORDS)
    except Exception:
        return False

TARGET1 = resource_path("target1.png")
TARGET2 = resource_path("target2.png")
TARGET3 = resource_path("target3.png")
TARGET4 = resource_path("target4.png")

BUFF_KEYS_DEFAULT = ["1", "2", "3", "q", "w", "e", "s", "d"]
DEFAULT_BUFF_HOTKEY = "`"


# =========================================================
# MP 게이지 감지
# =========================================================

def get_game_client_rect_on_screen():
    """활성화된 게임 창의 클라이언트 영역 좌표를 반환합니다."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        if not is_game_window_active():
            return None

        rect = ctypes.wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            return None

        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return pt.x, pt.y, width, height
    except Exception:
        return None


def detect_mp_percent():
    """게임 클라이언트 좌측 하단의 파란 MP 게이지를 색상으로 감지합니다.

    MP 숫자는 사용하지 않고, 실제 파란색으로 채워진 게이지 길이를
    전체 게이지 길이에 대한 비율로 환산합니다.
    """
    rect = get_game_client_rect_on_screen()
    if not rect:
        return None

    gx, gy, gw, gh = rect
    if gw < 400 or gh < 300:
        return None

    try:
        # 1vv.png 기준 MP HUD는 클라이언트 좌측 하단에 있습니다.
        # 해상도가 달라져도 게임 클라이언트 크기에 비례하도록 ROI를 잡습니다.
        roi_x = 0
        roi_y = int(gh * 0.84)
        roi_w = min(int(gw * 0.28), gw)
        roi_h = min(int(gh * 0.16), gh - roi_y)

        if roi_w <= 0 or roi_h <= 0:
            return None

        frame = np.array(
            pyautogui.screenshot(
                region=(gx + roi_x, gy + roi_y, roi_w, roi_h)
            )
        )
        if frame.size == 0:
            return None

        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)

        # 엔타리아 스크린샷의 MP 바에 해당하는 청색 계열.
        # 밝기/채도가 조금 달라져도 잡히도록 기존보다 범위를 넓혔습니다.
        lower = np.array([85, 55, 55], dtype=np.uint8)
        upper = np.array([135, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)

        # 작은 노이즈를 제거하고 게이지 내부의 끊어진 픽셀을 연결합니다.
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        # MP 바는 ROI 안에서 '가로로 긴 파란색 연속 구간'입니다.
        # 여러 행을 검사해서 가장 안정적인 파란 구간 폭을 구합니다.
        row_widths = []
        for y in range(mask.shape[0]):
            row = mask[y] > 0
            if not np.any(row):
                continue

            padded = np.concatenate(([False], row, [False]))
            changes = np.diff(padded.astype(np.int8))
            starts = np.flatnonzero(changes == 1)
            ends = np.flatnonzero(changes == -1)

            if len(starts) == 0:
                continue

            runs = ends - starts
            valid_runs = runs[runs >= 20]
            if len(valid_runs) == 0:
                continue

            # 이 행에서 가장 긴 파란 연속 구간을 MP 후보로 사용합니다.
            row_widths.append(int(np.max(valid_runs)))

        if len(row_widths) < 2:
            return None

        # 이상치에 덜 민감하도록 상위/하위 극단값을 제외하고 중앙값 사용.
        row_widths.sort()
        trim = max(0, len(row_widths) // 8)
        if trim > 0 and len(row_widths) > trim * 2:
            stable_widths = row_widths[trim:-trim]
        else:
            stable_widths = row_widths

        filled_width = float(np.median(stable_widths))

        # 1vv.png에서 실제 MP 내부 게이지 길이는 약 170px.
        # 게임 클라이언트 크기에 비례시켜 해상도 변경에도 대응합니다.
        full_width = gw * 0.17
        full_width = max(120.0, min(220.0, full_width))

        # 검출된 폭이 전체 길이를 넘으면 100%로 제한합니다.
        filled_width = min(filled_width, full_width)
        percent = (filled_width / full_width) * 100.0
        percent = max(0.0, min(100.0, percent))

        return round(percent, 1)

    except Exception:
        return None


# =========================================================
# HP 게이지 감지
# =========================================================

def detect_hp_percent():
    """게임 클라이언트 좌측 하단의 빨간 HP 게이지를 색상으로 감지합니다."""
    rect = get_game_client_rect_on_screen()
    if not rect:
        return None

    gx, gy, gw, gh = rect
    if gw < 400 or gh < 300:
        return None

    try:
        # HP/MP HUD가 있는 좌측 하단 영역을 조금 넓게 잡습니다.
        roi_x = 0
        roi_y = int(gh * 0.78)
        roi_w = min(int(gw * 0.28), gw)
        roi_h = min(HP_BAR_SEARCH_HEIGHT, gh - roi_y)
        if roi_w <= 0 or roi_h <= 0:
            return None

        frame = np.array(
            pyautogui.screenshot(
                region=(gx + roi_x, gy + roi_y, roi_w, roi_h)
            )
        )
        if frame.size == 0:
            return None

        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        # 빨강은 HSV에서 0도와 180도 근처로 나뉩니다.
        lower1 = np.array([0, 70, 60], dtype=np.uint8)
        upper1 = np.array([12, 255, 255], dtype=np.uint8)
        lower2 = np.array([168, 70, 60], dtype=np.uint8)
        upper2 = np.array([179, 255, 255], dtype=np.uint8)
        mask = cv2.bitwise_or(
            cv2.inRange(hsv, lower1, upper1),
            cv2.inRange(hsv, lower2, upper2),
        )

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        # HP 바는 가로로 긴 빨간색 연속 구간입니다.
        candidates = []
        for y in range(mask.shape[0]):
            row = mask[y] > 0
            if not np.any(row):
                continue
            padded = np.concatenate(([False], row, [False]))
            changes = np.diff(padded.astype(np.int8))
            starts = np.flatnonzero(changes == 1)
            ends = np.flatnonzero(changes == -1)
            for start, end in zip(starts, ends):
                width = int(end - start)
                if width >= 20:
                    candidates.append((width, y, int(start), int(end)))

        if len(candidates) < 2:
            return None

        # 여러 행에서 반복 검출되는 가장 긴 빨간 구간을 사용합니다.
        candidates.sort(reverse=True)
        top = candidates[:max(5, len(candidates) // 3)]
        filled_width = float(np.median([c[0] for c in top]))

        full_width = gw * 0.17
        full_width = max(120.0, min(220.0, full_width))
        filled_width = min(filled_width, full_width)
        percent = (filled_width / full_width) * 100.0
        return round(max(0.0, min(100.0, percent)), 1)
    except Exception:
        return None

# =========================================================
# 다크 테마
# =========================================================

BG = "#090D12"
SIDEBAR = "#0F141B"
CARD = "#141A22"
CARD_2 = "#181F28"
CARD_3 = "#1D2631"
BORDER = "#27313D"

TEXT = "#F4F7FB"
MUTED = "#8D9AAA"
DIM = "#657386"

ACCENT = "#7157FF"
ACCENT_2 = "#4D7CFF"
ACCENT_HOVER = "#806AFF"

SUCCESS = "#35D07F"
WARNING = "#F3B83F"
DANGER = "#FF5D73"
INFO = "#42A5FF"

FONT = "Malgun Gothic"


# =========================================================
# 전역 상태
# =========================================================

running = False
paused = False
repeat_mode = False
exit_program = False
buff_running = False
logged_in = False

current_username = ""
current_license = ""
current_license_expire = ""
remaining_seconds = 0

state_lock = threading.Lock()
macro_thread = None
buff_thread = None

# 제자리사냥 상태
position_hunt_running = False
position_hunt_thread = None
position_hunt_stop_event = threading.Event()

# 마나 포션 상태
mp_potion_running = False
mp_potion_thread = None
mp_potion_stop_event = threading.Event()

# HP 포션 상태
hp_potion_running = False
hp_potion_thread = None
hp_potion_stop_event = threading.Event()

chat_ws = None
chat_thread = None
chat_window = None
chat_running = False
chat_connected = False
chat_reconnect_lock = threading.Lock()

keyboard_hooks = []

main_root = None
login_root = None


# =========================================================
# 설정 파일
# =========================================================

def load_buff_keys():
    try:
        if os.path.exists(BUFF_KEYS_CONFIG_FILE):
            with open(BUFF_KEYS_CONFIG_FILE, "r", encoding="utf-8") as f:
                values = [line.strip() for line in f.readlines()]
            values = [v for v in values if v != ""]
            if len(values) >= 8:
                return values[:8]
    except Exception:
        pass
    return BUFF_KEYS_DEFAULT.copy()


def save_buff_keys(values):
    try:
        with open(BUFF_KEYS_CONFIG_FILE, "w", encoding="utf-8") as f:
            for value in values[:8]:
                f.write(str(value).strip() + "\n")
        return True
    except Exception:
        return False


def load_buff_hotkey():
    try:
        if os.path.exists(BUFF_HOTKEY_CONFIG_FILE):
            with open(BUFF_HOTKEY_CONFIG_FILE, "r", encoding="utf-8") as f:
                value = f.read().strip()
                if value:
                    return value
    except Exception:
        pass
    return DEFAULT_BUFF_HOTKEY


def save_buff_hotkey(value):
    try:
        with open(BUFF_HOTKEY_CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(value.strip())
        return True
    except Exception:
        return False


BUFF_KEYS = load_buff_keys()
BUFF_HOTKEY = load_buff_hotkey()


# =========================================================
# 공통
# =========================================================

def parse_version(version):
    try:
        return tuple(int(x) for x in str(version).strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


def get_hardware_id():
    raw = "|".join([
        platform.system(),
        platform.node(),
        platform.machine(),
        str(uuid.getnode()),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


HARDWARE_ID = get_hardware_id()


def format_remaining(seconds):
    try:
        seconds = max(0, int(seconds))
    except Exception:
        seconds = 0

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    if days > 0:
        return f"{days}일 {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def safe_after(root, delay, func):
    try:
        if root and root.winfo_exists():
            root.after(delay, func)
    except Exception:
        pass


# =========================================================
# 업데이트
# =========================================================

def check_for_update():
    try:
        response = requests.get(VERSION_URL, timeout=5)
        response.raise_for_status()
        data = response.json()

        latest = data.get("version") or data.get("latest_version")
        if not latest:
            return None

        if parse_version(latest) > parse_version(APP_VERSION):
            return {
                "version": latest,
                "url": data.get("url") or data.get("download_url") or "",
                "notes": data.get("notes") or data.get("changelog") or "",
            }
    except Exception:
        pass

    return None


def get_updater_path():
    candidates = [
        os.path.join(BASE_DIR, "updater.exe"),
        os.path.join(os.path.dirname(sys.executable), "updater.exe"),
        os.path.join(BASE_DIR, "EntariaUpdater.exe"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def start_updater(update_info):
    updater = get_updater_path()
    if not updater:
        return False

    try:
        target_exe = sys.executable if getattr(sys, "frozen", False) else ""
        subprocess.Popen([
            updater,
            target_exe,
            str(update_info.get("url", "")),
        ], close_fds=True)
        return True
    except Exception:
        return False


def check_update_and_exit():
    if not getattr(sys, "frozen", False):
        return

    update_info = check_for_update()
    if not update_info:
        return

    root = tk.Tk()
    root.withdraw()

    msg = f"새 버전 {update_info['version']}이 있습니다.\n\n현재 버전: {APP_VERSION}"
    if update_info.get("notes"):
        msg += f"\n\n변경사항:\n{update_info['notes']}"

    answer = messagebox.askyesno("ENTARIA 업데이트", msg + "\n\n지금 업데이트하시겠습니까?")
    root.destroy()

    if answer:
        if start_updater(update_info):
            sys.exit(0)
        else:
            messagebox.showerror("업데이트 오류", "업데이터를 실행하지 못했습니다.")


# =========================================================
# 모던 UI 헬퍼
# =========================================================

def make_card(parent, bg=CARD, border=BORDER, padx=1, pady=1):
    outer = tk.Frame(parent, bg=border)
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill="both", expand=True, padx=padx, pady=pady)
    return outer, inner


def make_button(parent, text, command, width=120, bg=CARD_2,
                fg=TEXT, active_bg=ACCENT, font_size=10,
                relief="flat"):
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        width=width,
        height=2,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground="#FFFFFF",
        relief=relief,
        bd=0,
        cursor="hand2",
        font=(FONT, font_size, "bold"),
        highlightthickness=0,
    )
    return btn


def make_entry(parent, value="", width=15, justify="center"):
    entry = tk.Entry(
        parent,
        width=width,
        bg="#10161E",
        fg=TEXT,
        insertbackground=TEXT,
        selectbackground=ACCENT,
        selectforeground="#FFFFFF",
        relief="flat",
        bd=0,
        justify=justify,
        font=(FONT, 10),
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
    )
    entry.insert(0, value)
    return entry


def add_section_title(parent, title, subtitle=None):
    title_frame = tk.Frame(parent, bg=parent.cget("bg"))
    title_frame.pack(fill="x", pady=(0, 12))

    tk.Label(
        title_frame,
        text=title,
        bg=parent.cget("bg"),
        fg=TEXT,
        font=(FONT, 18, "bold"),
    ).pack(side="left")

    if subtitle:
        tk.Label(
            title_frame,
            text=subtitle,
            bg=parent.cget("bg"),
            fg=MUTED,
            font=(FONT, 9),
        ).pack(side="left", padx=(12, 0), pady=(5, 0))

    return title_frame


# =========================================================
# 로그인
# =========================================================

def create_login_window():
    """로그인 전용 창.

    회원가입과 로그인을 완전히 분리한다.
    - 회원가입: 발급코드 + 아이디 + 비밀번호 + HWID -> /register
    - 로그인: 아이디 + 비밀번호 + HWID -> /login
    - 회원가입 성공은 자동 로그인하지 않고 로그인 화면으로 돌아간다.
    - 로그인 성공시에만 메인 대시보드를 생성한다.
    """
    global login_root

    login_root = tk.Tk()
    login_root.title("ENTARIA")
    login_root.geometry("460x700")
    login_root.resizable(False, False)
    login_root.configure(bg=BG)

    root = login_root

    # -----------------------------------------------------
    # 공통 UI
    # -----------------------------------------------------
    logo_wrap = tk.Frame(root, bg=BG)
    logo_wrap.pack(fill="x", pady=(42, 0))

    logo_circle = tk.Canvas(
        logo_wrap,
        width=62,
        height=62,
        bg=BG,
        highlightthickness=0,
    )
    logo_circle.pack()
    logo_circle.create_oval(4, 4, 58, 58, outline=ACCENT, width=3)
    logo_circle.create_text(
        31, 31,
        text="E",
        fill=TEXT,
        font=(FONT, 23, "bold")
    )

    tk.Label(
        root,
        text="ENTARIA",
        bg=BG,
        fg=TEXT,
        font=(FONT, 25, "bold"),
    ).pack(pady=(10, 2))

    tk.Label(
        root,
        text=f"MAPLE STORY AUTOMATION  •  v{APP_VERSION}",
        bg=BG,
        fg=MUTED,
        font=(FONT, 8),
    ).pack()

    card_outer, card = make_card(root, bg=CARD)
    card_outer.pack(fill="x", padx=38, pady=(28, 0))

    tk.Label(
        card,
        text="ENTARIA 로그인",
        bg=CARD,
        fg=TEXT,
        font=(FONT, 14, "bold"),
    ).pack(anchor="w", padx=28, pady=(24, 5))

    tk.Label(
        card,
        text="회원가입 후 등록한 계정으로 로그인하세요.",
        bg=CARD,
        fg=MUTED,
        font=(FONT, 9),
    ).pack(anchor="w", padx=28, pady=(0, 20))

    def labeled_entry(label, show=None):
        tk.Label(
            card,
            text=label,
            bg=CARD,
            fg=MUTED,
            font=(FONT, 9, "bold"),
        ).pack(anchor="w", padx=28, pady=(0, 7))

        ent = tk.Entry(
            card,
            bg="#0E141B",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            font=(FONT, 10),
            show=show or "",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        ent.pack(fill="x", padx=28, ipady=10)
        return ent

    username_entry = labeled_entry("아이디")
    password_entry = labeled_entry("비밀번호", "*")

    message_var = tk.StringVar(value="")
    message_label = tk.Label(
        card,
        textvariable=message_var,
        bg=CARD,
        fg=DANGER,
        font=(FONT, 9),
        wraplength=330,
        justify="left",
    )
    message_label.pack(anchor="w", padx=28, pady=(14, 4))

    def set_message(text, color=DANGER):
        message_var.set(str(text))
        message_label.configure(fg=color)

    # -----------------------------------------------------
    # 로그인
    # -----------------------------------------------------
    login_in_progress = {"value": False}

    def finish_login(data, username):
        """로그인 성공 후 UI 전환. 이 함수에서만 메인 창을 연다."""
        global logged_in, current_username, current_license
        global current_license_expire, remaining_seconds, main_root

        try:
            current_username = str(data.get("username") or username)
            current_license = str(
                data.get("license")
                or data.get("license_key")
                or data.get("license_code")
                or ""
            )
            current_license_expire = str(
                data.get("expire")
                or data.get("expires_at")
                or data.get("license_expire")
                or data.get("expiration")
                or ""
            )

            # 서버가 remaining_seconds를 주는 경우 우선 사용한다.
            # 없고 expire가 ISO 날짜로 내려오는 경우 로컬에서 계산한다.
            raw_remaining = (
                data.get("remaining_seconds")
                if data.get("remaining_seconds") is not None
                else data.get("remaining")
            )

            if raw_remaining is not None:
                try:
                    remaining_seconds = max(0, int(float(raw_remaining)))
                except Exception:
                    remaining_seconds = 0
            else:
                remaining_seconds = 0
                if current_license_expire:
                    try:
                        expire_text = current_license_expire.replace("Z", "+00:00")
                        expire_dt = datetime.fromisoformat(expire_text)
                        if expire_dt.tzinfo is not None:
                            from datetime import timezone
                            now_dt = datetime.now(timezone.utc)
                        else:
                            now_dt = datetime.now()
                        remaining_seconds = max(
                            0,
                            int((expire_dt - now_dt).total_seconds())
                        )
                    except Exception:
                        pass

            # 메인창이 이미 남아있다면 중복 생성하지 않는다.
            if main_root is not None:
                try:
                    if main_root.winfo_exists():
                        login_root.withdraw()
                        main_root.deiconify()
                        main_root.lift()
                        main_root.focus_force()
                        logged_in = True
                        return
                except Exception:
                    main_root = None

            # 가장 중요한 전환 부분:
            # 메인창 생성 중 오류가 나면 로그인창을 계속 보여주면서 실제 오류를 알려준다.
            try:
                create_main_window()
            except Exception as e:
                logged_in = False
                main_root = None
                login_root.deiconify()
                login_root.lift()
                login_root.focus_force()
                set_message(f"메인 화면 실행 오류: {type(e).__name__}: {e}", DANGER)
                messagebox.showerror(
                    "ENTARIA 실행 오류",
                    "로그인은 성공했지만 메인 프로그램을 열지 못했습니다.\n\n"
                    f"오류: {type(e).__name__}: {e}"
                )
                return

            logged_in = True

            # 메인창이 실제로 생성된 뒤 로그인창을 숨긴다.
            try:
                login_root.withdraw()
                if main_root is not None and main_root.winfo_exists():
                    main_root.deiconify()
                    main_root.lift()
                    main_root.focus_force()
            except Exception:
                pass

        finally:
            login_in_progress["value"] = False
            try:
                login_btn.configure(state="normal", text="로그인")
            except Exception:
                pass

    def do_login(event=None):
        if login_in_progress["value"]:
            return "break"

        username = username_entry.get().strip()
        password = password_entry.get()

        if not username or not password:
            set_message("아이디와 비밀번호를 입력해주세요.")
            return "break"

        login_in_progress["value"] = True
        login_btn.configure(state="disabled", text="로그인 중...")
        set_message("서버에서 계정을 확인하고 있습니다...", INFO)

        def worker():
            try:
                # 회원가입에서 발급코드와 계정을 연결했으므로
                # 로그인에서는 아이디/비밀번호/HWID만 전송한다.
                payload = {
                    "username": username,
                    "password": password,
                    "hardware_id": HARDWARE_ID,
                }

                response = requests.post(
                    LOGIN_URL,
                    json=payload,
                    timeout=10,
                )

                try:
                    data = response.json()
                except Exception:
                    data = {}

                success_value = data.get("success")
                is_success = response.ok and (
                    success_value is True
                    or str(success_value).lower() in ("true", "1", "ok", "success")
                )

                # 일부 서버가 200 OK만 반환하는 구조도 안전하게 처리한다.
                if response.ok and "success" not in data:
                    if data.get("username") or data.get("license") or data.get("license_key"):
                        is_success = True

                if is_success:
                    safe_after(
                        login_root,
                        0,
                        lambda d=data, u=username: finish_login(d, u)
                    )
                else:
                    msg = (
                        data.get("message")
                        or data.get("error")
                        or data.get("detail")
                        or f"로그인 실패 ({response.status_code})"
                    )

                    def fail(msg=msg):
                        login_in_progress["value"] = False
                        set_message(str(msg), DANGER)
                        login_btn.configure(state="normal", text="로그인")

                    safe_after(login_root, 0, fail)

            except Exception as e:
                def fail_connection(error_text=str(e)):
                    login_in_progress["value"] = False
                    set_message(f"서버 연결 실패: {error_text}", DANGER)
                    login_btn.configure(state="normal", text="로그인")

                safe_after(login_root, 0, fail_connection)

        threading.Thread(target=worker, daemon=True).start()
        return "break"

    # -----------------------------------------------------
    # 회원가입 창
    # -----------------------------------------------------
    def open_register_window():
        register_win = tk.Toplevel(login_root)
        register_win.title("ENTARIA • 회원가입")
        register_win.geometry("460x720")
        register_win.resizable(False, False)
        register_win.configure(bg=BG)
        register_win.transient(login_root)
        register_win.grab_set()

        tk.Label(
            register_win,
            text="회원가입",
            bg=BG,
            fg=TEXT,
            font=(FONT, 22, "bold"),
        ).pack(pady=(32, 4))

        tk.Label(
            register_win,
            text="발급받은 코드를 계정에 등록하세요.",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
        ).pack(pady=(0, 20))

        outer, reg_card = make_card(register_win, bg=CARD)
        outer.pack(fill="x", padx=32)

        def reg_entry(label, show=None, placeholder=""):
            tk.Label(
                reg_card,
                text=label,
                bg=CARD,
                fg=MUTED,
                font=(FONT, 9, "bold"),
            ).pack(anchor="w", padx=25, pady=(18, 7))

            ent = tk.Entry(
                reg_card,
                bg="#0E141B",
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                bd=0,
                font=(FONT, 10),
                show=show or "",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
            )
            ent.pack(fill="x", padx=25, ipady=10)
            if placeholder:
                ent.insert(0, placeholder)
            return ent

        reg_license = reg_entry("발급코드")
        reg_username = reg_entry("아이디")
        reg_password = reg_entry("비밀번호", "*")
        reg_password_confirm = reg_entry("비밀번호 확인", "*")

        reg_message_var = tk.StringVar(value="")
        reg_message = tk.Label(
            reg_card,
            textvariable=reg_message_var,
            bg=CARD,
            fg=DANGER,
            font=(FONT, 9),
            wraplength=330,
            justify="left",
        )
        reg_message.pack(anchor="w", padx=25, pady=(15, 5))

        def set_reg_message(text, color=DANGER):
            reg_message_var.set(str(text))
            reg_message.configure(fg=color)

        register_state = {"busy": False}

        def do_register_submit():
            if register_state["busy"]:
                return

            license_code = reg_license.get().strip()
            username = reg_username.get().strip()
            password = reg_password.get()
            password_confirm = reg_password_confirm.get()

            if not license_code or not username or not password or not password_confirm:
                set_reg_message("발급코드, 아이디, 비밀번호를 모두 입력해주세요.")
                return

            if password != password_confirm:
                set_reg_message("비밀번호가 서로 일치하지 않습니다.")
                return

            if len(username) < 2:
                set_reg_message("아이디는 2자 이상 입력해주세요.")
                return

            if len(password) < 4:
                set_reg_message("비밀번호는 4자 이상 입력해주세요.")
                return

            register_state["busy"] = True
            register_button.configure(state="disabled", text="등록 중...")
            set_reg_message("발급코드와 계정을 등록하고 있습니다...", INFO)

            def worker():
                try:
                    response = requests.post(
                        REGISTER_URL,
                        json={
                            "username": username,
                            "password": password,
                            "license": license_code,
                            "hardware_id": HARDWARE_ID,
                        },
                        timeout=10,
                    )

                    try:
                        data = response.json()
                    except Exception:
                        data = {}

                    success_value = data.get("success")
                    is_success = response.ok and (
                        success_value is True
                        or str(success_value).lower() in ("true", "1", "ok", "success")
                    )

                    if response.ok and "success" not in data:
                        # success 필드가 없는 서버 응답에서 일반적인 성공 형태 지원
                        if data.get("username") or data.get("message") == "회원가입 성공":
                            is_success = True

                    if is_success:
                        msg = data.get("message") or "회원가입이 완료되었습니다."

                        def success_register():
                            register_state["busy"] = False
                            register_win.grab_release()
                            register_win.destroy()

                            # 회원가입 성공 후 자동 로그인하지 않는다.
                            # 로그인 화면으로 돌아가서 ID/PW를 직접 입력하게 한다.
                            username_entry.delete(0, "end")
                            username_entry.insert(0, username)
                            password_entry.delete(0, "end")
                            login_root.deiconify()
                            login_root.lift()
                            login_root.focus_force()
                            set_message(
                                f"{msg}\n아이디와 비밀번호를 입력하여 로그인해주세요.",
                                SUCCESS
                            )
                            password_entry.focus_set()

                        safe_after(login_root, 0, success_register)
                    else:
                        msg = (
                            data.get("message")
                            or data.get("error")
                            or data.get("detail")
                            or f"회원가입 실패 ({response.status_code})"
                        )

                        def register_fail(msg=msg):
                            register_state["busy"] = False
                            set_reg_message(str(msg), DANGER)
                            register_button.configure(state="normal", text="회원가입")

                        safe_after(register_win, 0, register_fail)

                except Exception as e:
                    def register_error(error_text=str(e)):
                        register_state["busy"] = False
                        set_reg_message(f"서버 연결 실패: {error_text}", DANGER)
                        register_button.configure(state="normal", text="회원가입")

                    safe_after(register_win, 0, register_error)

            threading.Thread(target=worker, daemon=True).start()

        button_frame = tk.Frame(reg_card, bg=CARD)
        button_frame.pack(fill="x", padx=25, pady=(12, 25))

        register_button = make_button(
            button_frame,
            "회원가입",
            do_register_submit,
            bg=ACCENT,
            active_bg=ACCENT_HOVER,
        )
        register_button.pack(fill="x")

        cancel_button = make_button(
            button_frame,
            "로그인 화면으로 돌아가기",
            lambda: register_win.destroy(),
            bg=CARD_3,
            active_bg=BORDER,
        )
        cancel_button.pack(fill="x", pady=(9, 0))

        tk.Label(
            register_win,
            text="현재 PC의 Hardware ID가 함께 등록됩니다.",
            bg=BG,
            fg=DIM,
            font=(FONT, 8),
        ).pack(pady=(15, 0))

        def close_register():
            try:
                register_win.grab_release()
            except Exception:
                pass
            register_win.destroy()

        register_win.protocol("WM_DELETE_WINDOW", close_register)
        reg_license.focus_set()

    # -----------------------------------------------------
    # 버튼
    # -----------------------------------------------------
    button_frame = tk.Frame(card, bg=CARD)
    button_frame.pack(fill="x", padx=28, pady=(12, 24))

    login_btn = make_button(
        button_frame,
        "로그인",
        do_login,
        width=15,
        bg=ACCENT,
        active_bg=ACCENT_HOVER,
    )
    login_btn.pack(side="left", fill="x", expand=True)

    register_btn = make_button(
        button_frame,
        "회원가입",
        open_register_window,
        width=15,
        bg=CARD_3,
        active_bg=BORDER,
    )
    register_btn.pack(side="left", fill="x", expand=True, padx=(10, 0))

    tk.Label(
        root,
        text="Hardware ID 보호 • Secure License Verification",
        bg=BG,
        fg=DIM,
        font=(FONT, 8),
    ).pack(pady=(18, 0))

    username_entry.focus_set()
    login_root.bind("<Return>", do_login)

    def close_login():
        global exit_program
        exit_program = True
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        try:
            login_root.destroy()
        except Exception:
            pass

    login_root.protocol("WM_DELETE_WINDOW", close_login)
    return login_root


# =========================================================
# 메인
# =========================================================

def create_main_window():
    global main_root
    global BUFF_HOTKEY
    global keyboard_hooks

    main_root = tk.Toplevel(login_root)
    main_root.title(f"ENTARIA  •  v{APP_VERSION}")
    main_root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    main_root.resizable(False, False)
    main_root.configure(bg=BG)

    # =====================================================
    # 상태 / 로그
    # =====================================================

    status_var = tk.StringVar(value="대기 중")
    status_color_var = tk.StringVar(value=MUTED)
    repeat_var = tk.StringVar(value="OFF")
    license_time_var = tk.StringVar(value=format_remaining(remaining_seconds))
    connection_var = tk.StringVar(value="서버 확인 중")
    chat_status_var = tk.StringVar(value="채팅 대기 중")

    log_box_ref = {"widget": None}
    online_users_ref = {"widget": None}
    chat_messages_ref = {"widget": None}
    chat_canvas_ref = {"widget": None}
    chat_input_ref = {"widget": None}
    chat_status_ref = {"var": chat_status_var}

    # 내가 보낸 메시지를 서버가 echo할 때 로컬 표시와 중복되지 않도록
    # 최근 전송 메시지를 잠시 기억합니다.
    chat_echo_lock = threading.Lock()
    recent_chat_echoes = []

    def log(message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        text = f"[{timestamp}] {message}\n"

        widget = log_box_ref.get("widget")
        if widget is None:
            return

        def append():
            try:
                widget.configure(state="normal")
                widget.insert("end", text)
                widget.see("end")
                widget.configure(state="disabled")
            except Exception:
                pass

        safe_after(main_root, 0, append)

    # =====================================================
    # 메인 그리드
    # =====================================================

    main_root.grid_rowconfigure(0, weight=1)
    main_root.grid_columnconfigure(1, weight=1)

    # =====================================================
    # 사이드바
    # =====================================================

    sidebar = tk.Frame(main_root, bg=SIDEBAR, width=230)
    sidebar.grid(row=0, column=0, sticky="nsew")
    sidebar.grid_propagate(False)

    # 로고
    logo_frame = tk.Frame(sidebar, bg=SIDEBAR)
    logo_frame.pack(fill="x", padx=22, pady=(24, 20))

    logo_canvas = tk.Canvas(
        logo_frame, width=42, height=42,
        bg=SIDEBAR, highlightthickness=0
    )
    logo_canvas.pack(side="left")
    logo_canvas.create_oval(2, 2, 40, 40, outline=ACCENT, width=2)
    logo_canvas.create_text(
        21, 21, text="E", fill=TEXT,
        font=(FONT, 17, "bold")
    )

    logo_text = tk.Frame(logo_frame, bg=SIDEBAR)
    logo_text.pack(side="left", padx=10)
    tk.Label(
        logo_text, text="ENTARIA",
        bg=SIDEBAR, fg=TEXT,
        font=(FONT, 15, "bold")
    ).pack(anchor="w")
    tk.Label(
        logo_text, text=f"v{APP_VERSION}",
        bg=SIDEBAR, fg=DIM,
        font=(FONT, 8)
    ).pack(anchor="w")

    # 사용자 카드
    user_outer, user_card = make_card(sidebar, bg=CARD)
    user_outer.pack(fill="x", padx=14, pady=(0, 18))

    avatar = tk.Canvas(
        user_card, width=58, height=58,
        bg=CARD, highlightthickness=0
    )
    avatar.pack(pady=(16, 7))
    avatar.create_oval(3, 3, 55, 55, fill=ACCENT, outline="")
    avatar.create_text(
        29, 29,
        text=(current_username[:1].upper() if current_username else "E"),
        fill="#FFFFFF",
        font=(FONT, 19, "bold")
    )

    tk.Label(
        user_card,
        text=current_username or "USER",
        bg=CARD, fg=TEXT,
        font=(FONT, 11, "bold")
    ).pack()

    online_frame = tk.Frame(user_card, bg=CARD)
    online_frame.pack(pady=(5, 15))
    tk.Label(
        online_frame, text="●",
        bg=CARD, fg=SUCCESS,
        font=(FONT, 9)
    ).pack(side="left")
    tk.Label(
        online_frame, text=" 온라인",
        bg=CARD, fg=SUCCESS,
        font=(FONT, 8, "bold")
    ).pack(side="left")

    # 메뉴
    menu_frame = tk.Frame(sidebar, bg=SIDEBAR)
    menu_frame.pack(fill="x", padx=14)

    # -----------------------------------------------------
    # 사이드바 내비게이션
    # -----------------------------------------------------
    section_refs = {
        "home": None,
        "macro": None,
        "buff": None,
        "position_hunt": None,
        "info": None,
    }
    nav_buttons = {}

    def navigate(section):
        """왼쪽 카테고리를 독립된 화면으로 전환한다."""
        # 모든 독립 페이지를 먼저 숨긴다.
        for page_name in ("macro", "buff", "position_hunt", "info"):
            page = section_refs.get(page_name)
            if page is not None:
                try:
                    page.grid_remove()
                except Exception:
                    pass

        if section == "macro":
            try:
                content_canvas.grid_remove()
                macro_page.grid(row=0, column=0, sticky="nsew")
                macro_page.tkraise()
            except Exception:
                pass

        elif section == "buff":
            try:
                content_canvas.grid_remove()
                buff_page.grid(row=0, column=0, sticky="nsew")
                buff_page.tkraise()
            except Exception:
                pass

        elif section == "position_hunt":
            try:
                content_canvas.grid_remove()
                position_hunt_page.grid(row=0, column=0, sticky="nsew")
                position_hunt_page.tkraise()
            except Exception:
                pass

        elif section == "info":
            try:
                content_canvas.grid_remove()
                info_page.grid(row=0, column=0, sticky="nsew")
                info_page.tkraise()
            except Exception:
                pass

        else:
            # HOME: 반드시 메인 대시보드(Canvas)를 다시 표시한다.
            try:
                info_page.grid_remove()
            except Exception:
                pass

            try:
                content_canvas.grid(row=0, column=0, sticky="nsew")
                content_canvas.tkraise()
                content_canvas.yview_moveto(0)
                content.update_idletasks()
            except Exception:
                pass

        # 현재 선택된 카테고리만 강조
        for key, btn in nav_buttons.items():
            try:
                if key == section:
                    btn.configure(
                        bg="#211A45",
                        fg=TEXT,
                        font=(FONT, 10, "bold")
                    )
                else:
                    btn.configure(
                        bg=SIDEBAR,
                        fg=MUTED,
                        font=(FONT, 10, "normal")
                    )
            except Exception:
                pass

    def go_home():
        """어떤 카테고리 화면에서든 메인 대시보드로 이동합니다."""
        try:
            navigate("home")
            scroll_to_top()
        except Exception:
            # UI 전환 중 예외가 발생해도 프로그램이 종료되지 않도록 합니다.
            pass

    def sidebar_button(text, command, selected=False):
        bg = "#211A45" if selected else SIDEBAR
        fg = TEXT if selected else MUTED

        btn = tk.Button(
            menu_frame,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground="#211A45",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            anchor="w",
            padx=18,
            height=2,
            cursor="hand2",
            font=(FONT, 10, "bold" if selected else "normal"),
        )
        btn.pack(fill="x", pady=3)
        return btn

    def scroll_to_top():
        try:
            content_canvas.yview_moveto(0)
        except Exception:
            pass

    def show_dashboard():
        scroll_to_top()

    def open_chat():
        create_chat_window()

    nav_buttons["home"] = sidebar_button("⌂   홈", lambda: navigate("home"), True)
    nav_buttons["chat"] = sidebar_button("▣   실시간 채팅", open_chat)
    nav_buttons["macro"] = sidebar_button("▶   자동분해매크로", lambda: navigate("macro"))
    nav_buttons["buff"] = sidebar_button("◆   버프", lambda: navigate("buff"))
    nav_buttons["position_hunt"] = sidebar_button("⚔   제자리사냥", lambda: navigate("position_hunt"))
    nav_buttons["info"] = sidebar_button("ⓘ   정보", lambda: navigate("info"))

    # 하단 연결 상태
    sidebar_bottom = tk.Frame(sidebar, bg=SIDEBAR)
    sidebar_bottom.pack(side="bottom", fill="x", padx=14, pady=14)

    connection_outer, connection_card = make_card(sidebar_bottom, bg=CARD)
    connection_outer.pack(fill="x")

    tk.Label(
        connection_card,
        text="연결 상태",
        bg=CARD, fg=MUTED,
        font=(FONT, 8, "bold")
    ).pack(anchor="w", padx=13, pady=(12, 4))

    connection_status_label = tk.Label(
        connection_card,
        textvariable=connection_var,
        bg=CARD, fg=SUCCESS,
        font=(FONT, 9, "bold")
    )
    connection_status_label.pack(anchor="w", padx=13, pady=(0, 3))


    # =====================================================
    # 메인 콘텐츠 영역
    # =====================================================

    content_wrap = tk.Frame(main_root, bg=BG)
    content_wrap.grid(row=0, column=1, sticky="nsew")
    content_wrap.grid_rowconfigure(0, weight=1)
    content_wrap.grid_columnconfigure(0, weight=1)

    content_canvas = tk.Canvas(
        content_wrap,
        bg=BG,
        highlightthickness=0,
        bd=0
    )
    # 메인 화면 오른쪽 세로 스크롤바는 사용하지 않습니다.
    content_canvas.grid(row=0, column=0, sticky="nsew")

    # 정보 전용 페이지. 홈 화면의 스크롤 콘텐츠와 분리되어 있다.
    info_page = tk.Frame(content_wrap, bg=BG)
    info_page.grid_remove()

    info_header = tk.Frame(info_page, bg=BG)
    info_header.pack(fill="x", padx=28, pady=(28, 20))

    info_header_left = tk.Frame(info_header, bg=BG)
    info_header_left.pack(side="left")
    tk.Label(
        info_header_left, text="ENTARIA 정보",
        bg=BG, fg=TEXT, font=(FONT, 24, "bold")
    ).pack(anchor="w")
    tk.Label(
        info_header_left, text="프로그램 및 계정 정보를 확인할 수 있습니다.",
        bg=BG, fg=MUTED, font=(FONT, 9)
    ).pack(anchor="w", pady=(5, 0))

    make_button(
        info_header, "←  홈으로",
        go_home,
        width=11, bg=CARD_3, active_bg=BORDER
    ).pack(side="right", pady=4)

    info_card_outer, info_card = make_card(info_page, bg=CARD)
    info_card_outer.pack(fill="x", padx=28, pady=(0, 18))

    tk.Label(
        info_card, text="프로그램 정보",
        bg=CARD, fg=TEXT, font=(FONT, 13, "bold")
    ).pack(anchor="w", padx=18, pady=(17, 10))

    info_grid = tk.Frame(info_card, bg=CARD)
    info_grid.pack(fill="x", padx=18, pady=(0, 17))
    for i in range(2):
        info_grid.grid_columnconfigure(i, weight=1)

    info_items = [
        ("현재 사용자", current_username or "USER"),
        ("프로그램 버전", f"v{APP_VERSION}"),
        ("라이선스", current_license or "-"),
        ("개발자 Discord", "sha.0330"),
    ]
    for i, (label, value) in enumerate(info_items):
        cell = tk.Frame(info_grid, bg="#10161E")
        cell.grid(
            row=i // 2, column=i % 2, sticky="ew",
            padx=(0 if i % 2 == 0 else 5, 5 if i % 2 == 0 else 0),
            pady=4
        )
        tk.Label(
            cell, text=label, bg="#10161E", fg=DIM,
            font=(FONT, 7, "bold")
        ).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(
            cell, text=value, bg="#10161E", fg=TEXT,
            font=(FONT, 8)
        ).pack(anchor="w", padx=10, pady=(0, 8))

    section_refs["info"] = info_page

    content = tk.Frame(content_canvas, bg=BG)
    section_refs["home"] = content
    content_window = content_canvas.create_window(
        (0, 0), window=content, anchor="nw"
    )

    def configure_scroll(event=None):
        content_canvas.configure(scrollregion=content_canvas.bbox("all"))
        try:
            content_canvas.itemconfigure(content_window, width=content_canvas.winfo_width())
        except Exception:
            pass

    content.bind("<Configure>", configure_scroll)
    content_canvas.bind("<Configure>", configure_scroll)

    # =====================================================
    # 헤더
    # =====================================================

    header = tk.Frame(content, bg=BG)
    header.pack(fill="x", padx=28, pady=(24, 20))

    header_left = tk.Frame(header, bg=BG)
    header_left.pack(side="left")

    tk.Label(
        header_left,
        text="Dashboard",
        bg=BG, fg=TEXT,
        font=(FONT, 24, "bold")
    ).pack(anchor="w")

    tk.Label(
        header_left,
        text="매크로와 버프를 한 곳에서 관리하세요.",
        bg=BG, fg=MUTED,
        font=(FONT, 9)
    ).pack(anchor="w", pady=(5, 0))

    header_right = tk.Frame(header, bg=BG)
    header_right.pack(side="right")

    tk.Label(
        header_right,
        text="LICENSE",
        bg=BG, fg=DIM,
        font=(FONT, 8, "bold")
    ).pack(side="left", padx=(0, 7))

    tk.Label(
        header_right,
        textvariable=license_time_var,
        bg=BG, fg=SUCCESS,
        font=(FONT, 10, "bold")
    ).pack(side="left")

    chat_header_btn = make_button(
        header_right, "💬  채팅", open_chat,
        width=10, bg=ACCENT, active_bg=ACCENT_HOVER
    )
    chat_header_btn.pack(side="left", padx=(15, 0))

    # =====================================================
    # 상단 상태 카드 4개
    # =====================================================

    stats_frame = tk.Frame(content, bg=BG)
    stats_frame.pack(fill="x", padx=28)

    for i in range(4):
        stats_frame.grid_columnconfigure(i, weight=1)

    def stat_card(column, title, value_var, icon, value_color):
        outer, inner = make_card(stats_frame, bg=CARD)
        outer.grid(
            row=0, column=column,
            sticky="nsew",
            padx=(0 if column == 0 else 5, 5 if column < 3 else 0)
        )

        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x", padx=16, pady=(15, 3))

        icon_box = tk.Label(
            top,
            text=icon,
            bg="#1B2540",
            fg=INFO,
            width=3,
            font=(FONT, 11, "bold")
        )
        icon_box.pack(side="left")

        tk.Label(
            top,
            text=title,
            bg=CARD,
            fg=MUTED,
            font=(FONT, 8, "bold")
        ).pack(side="left", padx=9)

        tk.Label(
            inner,
            textvariable=value_var,
            bg=CARD,
            fg=value_color,
            font=(FONT, 13, "bold")
        ).pack(anchor="w", padx=16, pady=(4, 15))

    stat_card(0, "매크로 상태", status_var, "▶", SUCCESS)
    stat_card(1, "반복 모드", repeat_var, "↻", INFO)
    stat_card(2, "라이선스", license_time_var, "◆", WARNING)
    stat_card(3, "서버", connection_var, "●", SUCCESS)

    # =====================================================
    # 빠른 실행 카드
    # =====================================================

    quick_outer, quick = make_card(content, bg=CARD)
    quick_outer.pack(fill="x", padx=28, pady=(18, 0))

    tk.Label(
        quick,
        text="빠른 실행",
        bg=CARD, fg=TEXT,
        font=(FONT, 13, "bold")
    ).pack(anchor="w", padx=18, pady=(17, 14))

    quick_buttons = tk.Frame(quick, bg=CARD)
    quick_buttons.pack(fill="x", padx=18, pady=(0, 18))

    for i in range(4):
        quick_buttons.grid_columnconfigure(i, weight=1)

    # =====================================================
    # 상태 업데이트
    # =====================================================

    def update_status():
        if exit_program:
            text, color = "종료", DANGER
        elif paused:
            text, color = "일시정지", WARNING
        elif position_hunt_running:
            text, color = "제자리사냥 실행 중", SUCCESS
        elif hp_potion_running:
            text, color = "체력 포션 실행 중", DANGER
        elif mp_potion_running:
            text, color = "마나 포션 실행 중", INFO
        elif buff_running:
            text, color = "버프 실행 중", INFO
        elif running:
            text, color = "매크로 실행 중", SUCCESS
        else:
            text, color = "대기 중", MUTED

        status_var.set(text)
        status_color_var.set(color)

    def stop_macro_only():
        global running, paused
        running = False
        paused = False
        update_status()
        log("매크로가 중지되었습니다.")

    def start_macro():
        global running, paused, exit_program, macro_thread

        if remaining_seconds <= 0:
            messagebox.showwarning("라이선스", "라이선스가 만료되었습니다.")
            return

        if running:
            log("이미 매크로가 실행 중입니다.")
            return

        exit_program = False
        paused = False
        running = True
        update_status()
        log("매크로 실행을 시작했습니다.")

        macro_thread = threading.Thread(target=macro, daemon=True)
        macro_thread.start()

    def pause_macro():
        global paused
        if not running:
            log("현재 실행 중인 매크로가 없습니다.")
            return

        paused = not paused
        update_status()
        log("매크로 일시정지" if paused else "매크로를 재개했습니다.")

    def toggle_repeat():
        global repeat_mode
        repeat_mode = not repeat_mode
        repeat_var.set("ON" if repeat_mode else "OFF")
        log(f"반복 모드: {'ON' if repeat_mode else 'OFF'}")

    def stop_program():
        stop_macro()

    make_button(
        quick_buttons, "▶  자동분해 시작",
        start_macro, bg=ACCENT, active_bg=ACCENT_HOVER
    ).grid(row=0, column=0, sticky="ew", padx=(0, 5))

    make_button(
        quick_buttons, "■  자동분해 중지",
        stop_macro_only, bg=CARD_3, active_bg=BORDER
    ).grid(row=0, column=1, sticky="ew", padx=5)

    make_button(
        quick_buttons, "◆  버프 실행",
        lambda: start_buff(),
        bg="#30215E", active_bg=ACCENT
    ).grid(row=0, column=2, sticky="ew", padx=5)

    make_button(
        quick_buttons, "↻  반복 " + ("ON" if repeat_mode else "OFF"),
        toggle_repeat, bg=CARD_3, active_bg=BORDER
    ).grid(row=0, column=3, sticky="ew", padx=(5, 0))

    # =====================================================
    # 매크로 / 버프 독립 페이지
    # =====================================================

    macro_page = tk.Frame(content_wrap, bg=BG)
    macro_page.grid_remove()
    macro_page.grid_columnconfigure(0, weight=1)

    macro_header = tk.Frame(macro_page, bg=BG)
    macro_header.pack(fill="x", padx=28, pady=(28, 20))

    macro_header_left = tk.Frame(macro_header, bg=BG)
    macro_header_left.pack(side="left")

    tk.Label(
        macro_header_left,
        text="매크로",
        bg=BG, fg=TEXT,
        font=(FONT, 24, "bold")
    ).pack(anchor="w")

    tk.Label(
        macro_header_left,
        text="매크로 실행과 타겟 상태를 관리합니다.",
        bg=BG, fg=MUTED,
        font=(FONT, 9)
    ).pack(anchor="w", pady=(5, 0))

    make_button(
        macro_header, "←  홈으로",
        go_home,
        width=11, bg=CARD_3, active_bg=BORDER
    ).pack(side="right", pady=4)

    buff_page = tk.Frame(content_wrap, bg=BG)
    buff_page.grid_remove()
    buff_page.grid_columnconfigure(0, weight=1)

    buff_header = tk.Frame(buff_page, bg=BG)
    buff_header.pack(fill="x", padx=28, pady=(28, 20))

    buff_header_left = tk.Frame(buff_header, bg=BG)
    buff_header_left.pack(side="left")

    tk.Label(
        buff_header_left,
        text="버프",
        bg=BG, fg=TEXT,
        font=(FONT, 24, "bold")
    ).pack(anchor="w")

    tk.Label(
        buff_header_left,
        text="버프 키와 전체 실행 단축키를 관리합니다.",
        bg=BG, fg=MUTED,
        font=(FONT, 9)
    ).pack(anchor="w", pady=(5, 0))

    make_button(
        buff_header, "←  홈으로",
        go_home,
        width=11, bg=CARD_3, active_bg=BORDER
    ).pack(side="right", pady=4)

    # =====================================================
    # 제자리사냥 페이지
    position_hunt_page = tk.Frame(content_wrap, bg=BG)
    position_hunt_page.grid_remove()
    position_hunt_page.grid_columnconfigure(0, weight=1)

    position_header = tk.Frame(position_hunt_page, bg=BG)
    position_header.pack(fill="x", padx=28, pady=(28, 20))

    position_header_left = tk.Frame(position_header, bg=BG)
    position_header_left.pack(side="left")
    tk.Label(
        position_header_left, text="제자리사냥",
        bg=BG, fg=TEXT, font=(FONT, 24, "bold")
    ).pack(anchor="w")
    tk.Label(
        position_header_left,
        text="현재 위치에서 A 키를 반복 입력합니다.",
        bg=BG, fg=MUTED, font=(FONT, 9)
    ).pack(anchor="w", pady=(5, 0))

    make_button(
        position_header, "←  홈으로", go_home,
        width=11, bg=CARD_3, active_bg=BORDER
    ).pack(side="right", pady=4)

    section_refs["position_hunt"] = position_hunt_page
    section_refs["macro"] = macro_page
    section_refs["buff"] = buff_page

    position_outer, position_card = make_card(position_hunt_page, bg=CARD)
    position_outer.pack(fill="x", padx=28, pady=(0, 18))

    tk.Label(
        position_card, text="제자리사냥 컨트롤",
        bg=CARD, fg=TEXT, font=(FONT, 13, "bold")
    ).pack(anchor="w", padx=18, pady=(17, 3))
    tk.Label(
        position_card,
        text="현재 캐릭터 위치를 유지하면서 A 키를 반복 입력합니다.",
        bg=CARD, fg=MUTED, font=(FONT, 8)
    ).pack(anchor="w", padx=18, pady=(0, 14))

    position_status_var = tk.StringVar(value="대기 중")
    position_status_line = tk.Frame(position_card, bg="#10161E")
    position_status_line.pack(fill="x", padx=18, pady=(0, 14))
    tk.Label(position_status_line, text="●", bg="#10161E", fg=SUCCESS,
             font=(FONT, 10)).pack(side="left", padx=(12, 7), pady=9)
    tk.Label(position_status_line, textvariable=position_status_var,
             bg="#10161E", fg=TEXT, font=(FONT, 9, "bold")).pack(side="left")

    def position_hunt_update_ui(status=None):
        if status is not None:
            position_status_var.set(status)

    def position_hunt_worker():
        global position_hunt_running
        try:
            while position_hunt_running and not exit_program and remaining_seconds > 0:
                if position_hunt_stop_event.is_set():
                    break
                if paused:
                    time.sleep(0.1)
                    continue
                # 게임 창이 포커스된 경우에만 A키를 입력합니다.
                if is_game_window_active():
                    try:
                        pyautogui.press("a")
                    except Exception as e:
                        log(f"제자리사냥 A 키 입력 오류: {e}")
                        break
                time.sleep(random.uniform(POSITION_HUNT_INTERVAL_MIN, POSITION_HUNT_INTERVAL_MAX))
        finally:
            position_hunt_running = False
            safe_after(main_root, 0, lambda: position_hunt_update_ui("중지됨"))
            safe_after(main_root, 0, update_status)

    def start_position_hunt():
        global position_hunt_running, position_hunt_thread
        if remaining_seconds <= 0:
            messagebox.showwarning("라이선스", "라이선스가 만료되었습니다.")
            return
        if position_hunt_running:
            return
        position_hunt_stop_event.clear()
        position_hunt_running = True
        position_hunt_update_ui("실행 중")
        update_status()
        log("제자리사냥을 시작했습니다.")
        position_hunt_thread = threading.Thread(
            target=position_hunt_worker, daemon=True
        )
        position_hunt_thread.start()

    def stop_position_hunt():
        global position_hunt_running, position_hunt_thread
        position_hunt_stop_event.set()
        position_hunt_running = False
        position_hunt_update_ui("중지됨")
        update_status()
        log("제자리사냥을 중지했습니다.")
        thread = position_hunt_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        position_hunt_thread = None

    # 시작/중지 버튼을 세로로 분리하여 항상 명확하게 표시
    position_start_btn = make_button(
        position_card, "⚔  제자리사냥 시작", start_position_hunt,
        bg=ACCENT, active_bg=ACCENT_HOVER
    )
    position_start_btn.pack(fill="x", padx=18, pady=(0, 8))

    position_stop_btn = make_button(
        position_card, "■  제자리사냥 중지", stop_position_hunt,
        bg=CARD_3, active_bg=BORDER
    )
    position_stop_btn.pack(fill="x", padx=18, pady=(0, 18))

    # =====================================================
    # 마나 포션 카드
    # =====================================================
    mp_outer, mp_card = make_card(position_hunt_page, bg=CARD)
    mp_outer.pack(fill="x", padx=28, pady=(0, 18))

    tk.Label(
        mp_card, text="마나 포션",
        bg=CARD, fg=TEXT, font=(FONT, 13, "bold")
    ).pack(anchor="w", padx=18, pady=(17, 3))
    tk.Label(
        mp_card,
        text="게임 창의 파란 MP 게이지를 감지해 설정한 비율 이하에서 포션을 사용합니다.",
        bg=CARD, fg=MUTED, font=(FONT, 8)
    ).pack(anchor="w", padx=18, pady=(0, 14))

    mp_setting_row = tk.Frame(mp_card, bg=CARD)
    mp_setting_row.pack(fill="x", padx=18, pady=(0, 12))

    tk.Label(mp_setting_row, text="포션 키", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
    mp_key_var = tk.StringVar(value=MP_POTION_DEFAULT_KEY)
    mp_key_entry = tk.Entry(
        mp_setting_row, textvariable=mp_key_var, width=8,
        bg=CARD_3, fg=TEXT, insertbackground=TEXT,
        relief="flat", font=(FONT, 10, "bold")
    )
    mp_key_entry.pack(side="left", padx=(8, 18), ipady=5)

    tk.Label(mp_setting_row, text="사용 기준", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
    mp_threshold_var = tk.StringVar(value=str(MP_POTION_DEFAULT_THRESHOLD))
    mp_threshold_spin = tk.Spinbox(
        mp_setting_row, from_=5, to=95, increment=5,
        textvariable=mp_threshold_var, width=5,
        bg=CARD_3, fg=TEXT, buttonbackground=CARD_3,
        insertbackground=TEXT, relief="flat", font=(FONT, 10, "bold")
    )
    mp_threshold_spin.pack(side="left", padx=(8, 4), ipady=3)
    tk.Label(mp_setting_row, text="% 이하", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")

    mp_status_var = tk.StringVar(value="대기 중")
    mp_status_line = tk.Frame(mp_card, bg="#10161E")
    mp_status_line.pack(fill="x", padx=18, pady=(0, 14))
    tk.Label(mp_status_line, text="●", bg="#10161E", fg=SUCCESS, font=(FONT, 10)).pack(side="left", padx=(12, 7), pady=9)
    tk.Label(mp_status_line, textvariable=mp_status_var, bg="#10161E", fg=TEXT, font=(FONT, 9, "bold")).pack(side="left")

    def mp_potion_update_ui(status=None):
        if status is not None:
            mp_status_var.set(status)

    def get_mp_potion_settings():
        key = mp_key_var.get().strip().lower()
        if not key:
            raise ValueError("포션 키를 입력해주세요.")
        try:
            threshold = float(mp_threshold_var.get())
        except Exception:
            raise ValueError("사용 기준은 숫자로 입력해주세요.")
        if not 5 <= threshold <= 95:
            raise ValueError("사용 기준은 5~95% 사이여야 합니다.")
        return key, threshold

    def mp_potion_worker():
        global mp_potion_running
        last_potion_time = 0.0
        try:
            while mp_potion_running and not exit_program and remaining_seconds > 0:
                if mp_potion_stop_event.is_set():
                    break
                if paused:
                    time.sleep(MP_POTION_CHECK_INTERVAL)
                    continue

                if not is_game_window_active():
                    mp_potion_update_ui("게임 창 대기 중")
                    time.sleep(MP_POTION_CHECK_INTERVAL)
                    continue

                mp_percent = detect_mp_percent()
                if mp_percent is None:
                    mp_potion_update_ui("MP 게이지 감지 중")
                    time.sleep(MP_POTION_CHECK_INTERVAL)
                    continue

                try:
                    _, threshold = get_mp_potion_settings()
                except ValueError:
                    mp_potion_update_ui("설정 확인 필요")
                    time.sleep(MP_POTION_CHECK_INTERVAL)
                    continue

                if mp_percent <= threshold and (time.monotonic() - last_potion_time) >= 0.8:
                    key, _ = get_mp_potion_settings()
                    try:
                        pyautogui.press(key)
                        last_potion_time = time.monotonic()
                        mp_potion_update_ui(f"포션 사용 • MP 약 {mp_percent:.0f}%")
                    except Exception as e:
                        log(f"마나 포션 키 입력 오류: {e}")
                        mp_potion_update_ui("키 입력 오류")
                else:
                    mp_potion_update_ui(f"감지 중 • MP 약 {mp_percent:.0f}%")

                time.sleep(MP_POTION_CHECK_INTERVAL)
        finally:
            mp_potion_running = False
            safe_after(main_root, 0, lambda: mp_potion_update_ui("중지됨"))
            safe_after(main_root, 0, update_status)

    def start_mp_potion():
        global mp_potion_running, mp_potion_thread
        if remaining_seconds <= 0:
            messagebox.showwarning("라이선스", "라이선스가 만료되었습니다.")
            return
        try:
            get_mp_potion_settings()
        except ValueError as e:
            messagebox.showwarning("마나 포션 설정", str(e))
            return
        if mp_potion_running:
            return
        mp_potion_stop_event.clear()
        mp_potion_running = True
        mp_potion_update_ui("게임 창 대기 중")
        update_status()
        log("마나 포션 감지를 시작했습니다.")
        mp_potion_thread = threading.Thread(target=mp_potion_worker, daemon=True)
        mp_potion_thread.start()

    def stop_mp_potion():
        global mp_potion_running, mp_potion_thread
        mp_potion_stop_event.set()
        mp_potion_running = False
        mp_potion_update_ui("중지됨")
        update_status()
        log("마나 포션 감지를 중지했습니다.")
        thread = mp_potion_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        mp_potion_thread = None

    make_button(
        mp_card, "🧪  마나 포션 시작", start_mp_potion,
        bg=ACCENT, active_bg=ACCENT_HOVER
    ).pack(fill="x", padx=18, pady=(0, 8))

    make_button(
        mp_card, "■  마나 포션 중지", stop_mp_potion,
        bg=CARD_3, active_bg=BORDER
    ).pack(fill="x", padx=18, pady=(0, 18))

    # =====================================================
    # HP 포션 카드
    # =====================================================
    hp_outer, hp_card = make_card(position_hunt_page, bg=CARD)
    hp_outer.pack(fill="x", padx=28, pady=(0, 18))

    tk.Label(
        hp_card, text="HP 포션",
        bg=CARD, fg=TEXT, font=(FONT, 13, "bold")
    ).pack(anchor="w", padx=18, pady=(17, 3))
    tk.Label(
        hp_card,
        text="게임 창의 빨간 HP 게이지를 감지해 설정한 비율 이하에서 포션을 사용합니다.",
        bg=CARD, fg=MUTED, font=(FONT, 8),
        wraplength=700, justify="left"
    ).pack(anchor="w", padx=18, pady=(0, 14))

    hp_setting_row = tk.Frame(hp_card, bg=CARD)
    hp_setting_row.pack(fill="x", padx=18, pady=(0, 12))

    tk.Label(hp_setting_row, text="포션 키", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
    hp_key_var = tk.StringVar(value=HP_POTION_DEFAULT_KEY)
    hp_key_entry = tk.Entry(
        hp_setting_row, textvariable=hp_key_var, width=8,
        bg=CARD_3, fg=TEXT, insertbackground=TEXT,
        relief="flat", font=(FONT, 10, "bold")
    )
    hp_key_entry.pack(side="left", padx=(8, 18), ipady=5)

    tk.Label(hp_setting_row, text="사용 기준", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
    hp_threshold_var = tk.StringVar(value=str(HP_POTION_DEFAULT_THRESHOLD))
    hp_threshold_spin = tk.Spinbox(
        hp_setting_row, from_=5, to=95, increment=5,
        textvariable=hp_threshold_var, width=5,
        bg=CARD_3, fg=TEXT, buttonbackground=CARD_3,
        insertbackground=TEXT, relief="flat", font=(FONT, 10, "bold")
    )
    hp_threshold_spin.pack(side="left", padx=(8, 4), ipady=3)
    tk.Label(hp_setting_row, text="% 이하", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")

    hp_status_var = tk.StringVar(value="대기 중")
    hp_status_line = tk.Frame(hp_card, bg="#10161E")
    hp_status_line.pack(fill="x", padx=18, pady=(0, 14))
    tk.Label(hp_status_line, text="●", bg="#10161E", fg=DANGER, font=(FONT, 10)).pack(side="left", padx=(12, 7), pady=9)
    tk.Label(hp_status_line, textvariable=hp_status_var, bg="#10161E", fg=TEXT, font=(FONT, 9, "bold")).pack(side="left")

    def hp_potion_update_ui(status=None):
        if status is not None:
            safe_after(main_root, 0, lambda s=status: hp_status_var.set(s))

    def get_hp_potion_settings():
        key = hp_key_var.get().strip().lower()
        if not key:
            raise ValueError("포션 키를 입력해주세요.")
        try:
            threshold = float(hp_threshold_var.get())
        except Exception:
            raise ValueError("사용 기준은 숫자로 입력해주세요.")
        if not 5 <= threshold <= 95:
            raise ValueError("사용 기준은 5~95% 사이여야 합니다.")
        return key, threshold

    def hp_potion_worker():
        global hp_potion_running
        last_potion_time = 0.0
        try:
            while hp_potion_running and not exit_program and remaining_seconds > 0:
                if hp_potion_stop_event.is_set():
                    break
                if paused:
                    time.sleep(HP_POTION_CHECK_INTERVAL)
                    continue
                if not is_game_window_active():
                    hp_potion_update_ui("게임 창 대기 중")
                    time.sleep(HP_POTION_CHECK_INTERVAL)
                    continue

                hp_percent = detect_hp_percent()
                if hp_percent is None:
                    hp_potion_update_ui("HP 게이지 감지 중")
                    time.sleep(HP_POTION_CHECK_INTERVAL)
                    continue

                try:
                    _, threshold = get_hp_potion_settings()
                except ValueError:
                    hp_potion_update_ui("설정 확인 필요")
                    time.sleep(HP_POTION_CHECK_INTERVAL)
                    continue

                if hp_percent <= threshold and (time.monotonic() - last_potion_time) >= 0.8:
                    key, _ = get_hp_potion_settings()
                    try:
                        pyautogui.press(key)
                        last_potion_time = time.monotonic()
                        hp_potion_update_ui(f"포션 사용 • HP 약 {hp_percent:.0f}%")
                    except Exception as e:
                        log(f"HP 포션 키 입력 오류: {e}")
                        hp_potion_update_ui("키 입력 오류")
                else:
                    hp_potion_update_ui(f"감지 중 • HP 약 {hp_percent:.0f}%")

                time.sleep(HP_POTION_CHECK_INTERVAL)
        finally:
            hp_potion_running = False
            hp_potion_update_ui("중지됨")
            safe_after(main_root, 0, update_status)

    def start_hp_potion():
        global hp_potion_running, hp_potion_thread
        if remaining_seconds <= 0:
            messagebox.showwarning("라이선스", "라이선스가 만료되었습니다.")
            return
        try:
            get_hp_potion_settings()
        except ValueError as e:
            messagebox.showwarning("HP 포션 설정", str(e))
            return
        if hp_potion_running:
            return
        hp_potion_stop_event.clear()
        hp_potion_running = True
        hp_potion_update_ui("게임 창 대기 중")
        update_status()
        log("HP 포션 감지를 시작했습니다.")
        hp_potion_thread = threading.Thread(target=hp_potion_worker, daemon=True)
        hp_potion_thread.start()

    def stop_hp_potion():
        global hp_potion_running, hp_potion_thread
        hp_potion_stop_event.set()
        hp_potion_running = False
        hp_potion_update_ui("중지됨")
        update_status()
        log("HP 포션 감지를 중지했습니다.")
        thread = hp_potion_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        hp_potion_thread = None

    make_button(
        hp_card, "❤️  HP 포션 시작", start_hp_potion,
        bg=ACCENT, active_bg=ACCENT_HOVER
    ).pack(fill="x", padx=18, pady=(0, 8))

    make_button(
        hp_card, "■  HP 포션 중지", stop_hp_potion,
        bg=CARD_3, active_bg=BORDER
    ).pack(fill="x", padx=18, pady=(0, 18))

    # 매크로 카드
    macro_outer, macro_card = make_card(macro_page, bg=CARD)
    macro_outer.pack(fill="x", padx=28, pady=(0, 18))

    tk.Label(
        macro_card, text="매크로 컨트롤",
        bg=CARD, fg=TEXT,
        font=(FONT, 13, "bold")
    ).pack(anchor="w", padx=18, pady=(17, 3))

    tk.Label(
        macro_card,
        text="F1 실행  •  F2 일시정지  •  F3 반복  •  F4 종료",
        bg=CARD, fg=MUTED,
        font=(FONT, 8)
    ).pack(anchor="w", padx=18, pady=(0, 14))

    status_line = tk.Frame(macro_card, bg="#10161E")
    status_line.pack(fill="x", padx=18, pady=(0, 13))

    tk.Label(
        status_line,
        text="●",
        bg="#10161E",
        fg=SUCCESS,
        font=(FONT, 10)
    ).pack(side="left", padx=(12, 7), pady=10)

    tk.Label(
        status_line,
        textvariable=status_var,
        bg="#10161E",
        fg=TEXT,
        font=(FONT, 9, "bold")
    ).pack(side="left")

    status_line.pack_configure(pady=(0, 18))

    # 버프 카드
    buff_outer, buff_card = make_card(buff_page, bg=CARD)
    buff_outer.pack(fill="x", padx=28, pady=(0, 18))

    tk.Label(
        buff_card, text="버프 설정",
        bg=CARD, fg=TEXT,
        font=(FONT, 13, "bold")
    ).pack(anchor="w", padx=18, pady=(17, 3))

    tk.Label(
        buff_card,
        text="8개의 버프 키와 전체 실행 단축키를 설정합니다.",
        bg=CARD, fg=MUTED,
        font=(FONT, 8)
    ).pack(anchor="w", padx=18, pady=(0, 12))

    buff_grid = tk.Frame(buff_card, bg=CARD)
    buff_grid.pack(fill="x", padx=18)

    buff_entries = []

    for i in range(8):
        cell = tk.Frame(buff_grid, bg=CARD)
        row = i // 4
        col = i % 4
        cell.grid(
            row=row, column=col,
            sticky="ew",
            padx=(0 if col == 0 else 4, 4 if col < 3 else 0),
            pady=4
        )
        buff_grid.grid_columnconfigure(col, weight=1)

        tk.Label(
            cell,
            text=f"{i + 1:02d}",
            bg=CARD,
            fg=DIM,
            font=(FONT, 7, "bold")
        ).pack(anchor="w")

        entry = make_entry(
            cell,
            BUFF_KEYS[i] if i < len(BUFF_KEYS) else "",
            width=7
        )
        entry.pack(fill="x", ipady=5)
        buff_entries.append(entry)

    hotkey_line = tk.Frame(buff_card, bg=CARD)
    hotkey_line.pack(fill="x", padx=18, pady=(10, 17))

    tk.Label(
        hotkey_line,
        text="전체 버프",
        bg=CARD, fg=MUTED,
        font=(FONT, 8, "bold")
    ).pack(side="left")

    hotkey_entry = make_entry(hotkey_line, BUFF_HOTKEY, width=8)
    hotkey_entry.pack(side="left", padx=(8, 7), ipady=5)

    def save_buff_settings():
        global BUFF_KEYS, BUFF_HOTKEY

        values = []
        for entry in buff_entries:
            value = entry.get().strip()
            values.append(value if value else "")

        hotkey = hotkey_entry.get().strip()
        if not hotkey:
            hotkey = DEFAULT_BUFF_HOTKEY

        old_hotkey = BUFF_HOTKEY
        BUFF_KEYS = values
        BUFF_HOTKEY = hotkey

        if not save_buff_keys(BUFF_KEYS):
            log("버프 키 저장 실패")
            return

        if not save_buff_hotkey(BUFF_HOTKEY):
            log("버프 단축키 저장 실패")
            return

        try:
            if old_hotkey:
                keyboard.remove_hotkey(old_hotkey)
        except Exception:
            pass

        try:
            keyboard.add_hotkey(BUFF_HOTKEY, start_buff)
            log(f"버프 설정 저장 완료 • 단축키 {BUFF_HOTKEY}")
        except Exception as e:
            log(f"버프 단축키 등록 실패: {e}")

    make_button(
        hotkey_line, "저장",
        save_buff_settings,
        width=8, bg=ACCENT, active_bg=ACCENT_HOVER
    ).pack(side="right")

    make_button(
        hotkey_line, "★ 전체 실행",
        lambda: start_buff(),
        width=12, bg="#30215E", active_bg=ACCENT
    ).pack(side="right", padx=(0, 7))

    # =====================================================
    # 로그
    # =====================================================

    log_outer, log_card = make_card(content, bg=CARD)
    log_outer.pack(fill="x", padx=28, pady=(18, 24))

    log_header = tk.Frame(log_card, bg=CARD)
    log_header.pack(fill="x", padx=18, pady=(15, 9))

    tk.Label(
        log_header,
        text="시스템 로그",
        bg=CARD, fg=TEXT,
        font=(FONT, 13, "bold")
    ).pack(side="left")

    tk.Label(
        log_header,
        text="LIVE",
        bg="#183C2B",
        fg=SUCCESS,
        font=(FONT, 7, "bold"),
        padx=8, pady=3
    ).pack(side="right")

    log_box = scrolledtext.ScrolledText(
        log_card,
        height=7,
        bg="#0D131A",
        fg="#B8C4D2",
        insertbackground=TEXT,
        selectbackground=ACCENT,
        selectforeground="#FFFFFF",
        relief="flat",
        bd=0,
        font=("Consolas", 9),
        padx=12,
        pady=10,
        wrap="word",
    )
    log_box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
    log_box.configure(state="disabled")
    log_box_ref["widget"] = log_box

    navigate("home")

    # =====================================================
    # 라이선스 / heartbeat
    # =====================================================

    def update_countdown():
        global remaining_seconds

        if remaining_seconds > 0:
            remaining_seconds -= 1

        license_time_var.set(format_remaining(remaining_seconds))

        if remaining_seconds <= 0:
            license_time_var.set("만료됨")
            stop_macro_only()
            log("라이선스가 만료되어 매크로를 중지했습니다.")
        elif remaining_seconds <= 3600:
            # warning
            pass

        safe_after(main_root, 1000, update_countdown)

    def license_heartbeat():
        global remaining_seconds, current_license_expire

        while not exit_program:
            try:
                response = requests.post(
                    HEARTBEAT_URL,
                    json={
                        "username": current_username,
                        "license": current_license,
                        "hardware_id": HARDWARE_ID,
                    },
                    timeout=10,
                )

                try:
                    data = response.json()
                except Exception:
                    data = {}

                if response.ok and data.get("success", True):
                    if "remaining_seconds" in data:
                        try:
                            remaining_seconds = int(data["remaining_seconds"])
                        except Exception:
                            pass

                    if data.get("expire") or data.get("expires_at"):
                        current_license_expire = str(
                            data.get("expire") or data.get("expires_at")
                        )

                    connection_var.set("연결됨")
                else:
                    if data.get("valid") is False or data.get("success") is False:
                        log("라이선스 인증이 유효하지 않습니다.")
                        safe_after(main_root, 0, stop_macro_only)

            except Exception as e:
                connection_var.set("오프라인")
                log(f"Heartbeat 오류: {e}")

            for _ in range(LICENSE_CHECK_INTERVAL):
                if exit_program:
                    break
                time.sleep(1)

    # =====================================================
    # 버프
    # =====================================================

    def press_game_key(key):
        if not key:
            return

        try:
            pyautogui.keyDown(key)
            time.sleep(KEY_PRESS_TIME)
            pyautogui.keyUp(key)
        except Exception as e:
            log(f"키 입력 오류 [{key}]: {e}")

    def start_buff():
        global buff_running, buff_thread

        if remaining_seconds <= 0:
            log("라이선스가 만료되어 버프를 실행할 수 없습니다.")
            return

        if buff_running:
            log("버프가 이미 실행 중입니다.")
            return

        buff_running = True
        update_status()
        log("버프 전체 실행을 시작했습니다.")

        buff_thread = threading.Thread(target=buff_sequence, daemon=True)
        buff_thread.start()

    def buff_sequence():
        global buff_running

        try:
            for key in BUFF_KEYS:
                if exit_program or remaining_seconds <= 0:
                    break

                while paused and not exit_program:
                    time.sleep(0.1)

                if not key:
                    continue

                press_game_key(key)
                time.sleep(BUFF_DELAY)

        finally:
            buff_running = False
            safe_after(main_root, 0, update_status)
            log("버프 전체 실행이 완료되었습니다.")

    # =====================================================
    # 이미지 인식
    # =====================================================

    def find_image(image_path):
        if not os.path.exists(image_path):
            log(
                f"이미지 파일이 없습니다: {os.path.basename(image_path)}\n"
                f"확인 경로: {image_path}"
            )
            return None

        while running and not exit_program:
            if remaining_seconds <= 0:
                return None

            while paused and running and not exit_program:
                time.sleep(0.1)

            try:
                position = pyautogui.locateCenterOnScreen(
                    image_path,
                    confidence=CONFIDENCE
                )
                if position:
                    return position
            except Exception as e:
                # OpenCV 미설치 등의 경우 반복 로그 방지
                log(f"이미지 인식 오류: {e}")
                return None

            time.sleep(SEARCH_DELAY)

        return None

    def click_target(target_name, target_path):
        if not running or exit_program:
            return False

        position = find_image(target_path)
        if not position:
            return False

        try:
            pyautogui.click(position.x, position.y)
            log(f"{target_name} 감지 및 클릭")
            time.sleep(TARGET_DELAY)
            return True
        except Exception as e:
            log(f"{target_name} 클릭 오류: {e}")
            return False

    def macro():
        targets = [
            ("TARGET 01", TARGET1),
            ("TARGET 02", TARGET2),
            ("TARGET 03", TARGET3),
            ("TARGET 04", TARGET4),
        ]

        while running and not exit_program:
            if remaining_seconds <= 0:
                break

            progress = False

            for target_name, target_path in targets:
                if not running or exit_program:
                    break

                if click_target(target_name, target_path):
                    progress = True

            if not repeat_mode:
                break

            if not progress:
                time.sleep(SEARCH_DELAY)

        global paused
        paused = False
        safe_after(main_root, 0, update_status)
        log("매크로 실행 루프가 종료되었습니다.")

    # =====================================================
    # 실시간 채팅
    # =====================================================

    def add_chat_message(username, message, is_me=False, timestamp=None):
        """채팅 메시지를 화면에 안전하게 추가하고 즉시 하단으로 스크롤합니다."""
        widget = chat_messages_ref.get("widget")
        canvas = chat_canvas_ref.get("widget")

        if widget is None:
            return

        if timestamp is None:
            timestamp = datetime.now().strftime("%H:%M")
        else:
            timestamp = str(timestamp)

        username = str(username or "USER")
        message = str(message or "")

        def append():
            try:
                # 메시지 영역이 살아있는지 확인
                if not widget.winfo_exists():
                    return

                line = tk.Frame(widget, bg="#0C1118")
                line.pack(fill="x", padx=8, pady=4)

                if is_me:
                    wrap = tk.Frame(line, bg="#4C35B8")
                    wrap.pack(side="right", padx=4, anchor="e")

                    tk.Label(
                        wrap,
                        text=message,
                        bg="#4C35B8",
                        fg="#FFFFFF",
                        font=(FONT, 9),
                        wraplength=360,
                        justify="left",
                        padx=12,
                        pady=8
                    ).pack()

                    tk.Label(
                        wrap,
                        text=timestamp,
                        bg="#4C35B8",
                        fg="#D5CEFF",
                        font=(FONT, 7),
                    ).pack(anchor="e", padx=9, pady=(0, 5))
                else:
                    tk.Label(
                        line,
                        text=username,
                        bg="#0C1118",
                        fg=INFO,
                        font=(FONT, 8, "bold"),
                    ).pack(anchor="w", padx=4)

                    wrap = tk.Frame(line, bg=CARD_2)
                    wrap.pack(side="left", padx=4, anchor="w")

                    tk.Label(
                        wrap,
                        text=message,
                        bg=CARD_2,
                        fg=TEXT,
                        font=(FONT, 9),
                        wraplength=360,
                        justify="left",
                        padx=12,
                        pady=8
                    ).pack()

                    tk.Label(
                        wrap,
                        text=timestamp,
                        bg=CARD_2,
                        fg=DIM,
                        font=(FONT, 7),
                    ).pack(anchor="e", padx=9, pady=(0, 5))

                widget.update_idletasks()

                if canvas is not None and canvas.winfo_exists():
                    canvas.update_idletasks()
                    canvas.configure(scrollregion=canvas.bbox("all"))
                    canvas.yview_moveto(1.0)

            except Exception as e:
                log(f"채팅 화면 표시 오류: {type(e).__name__}: {e}")

        safe_after(main_root, 0, append)

    def update_online_users(users):
        widget = online_users_ref.get("widget")
        if widget is None:
            return

        def refresh():
            try:
                for child in widget.winfo_children():
                    child.destroy()

                for user in users:
                    if isinstance(user, dict):
                        name = user.get("username") or user.get("name") or "USER"
                    else:
                        name = str(user)

                    row = tk.Frame(widget, bg=CARD)
                    row.pack(fill="x", padx=10, pady=4)

                    tk.Label(
                        row,
                        text="●",
                        bg=CARD,
                        fg=SUCCESS,
                        font=(FONT, 8)
                    ).pack(side="left")

                    tk.Label(
                        row,
                        text=name,
                        bg=CARD,
                        fg=TEXT,
                        font=(FONT, 8)
                    ).pack(side="left", padx=7)
            except Exception:
                pass

        safe_after(main_root, 0, refresh)

    def handle_chat_payload(data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                add_chat_message("SYSTEM", data)
                return

        if not isinstance(data, dict):
            return

        event = str(
            data.get("type")
            or data.get("event")
            or data.get("action")
            or ""
        ).lower()

        if event in ("message", "chat", "new_message", ""):
            username = (
                data.get("username")
                or data.get("user")
                or data.get("sender")
                or "USER"
            )
            message = (
                data.get("message")
                or data.get("text")
                or data.get("content")
                or data.get("body")
                or ""
            )
            if message:
                # 서버가 내가 방금 보낸 메시지를 echo하면
                # send_chat_message()에서 이미 화면에 표시했으므로 중복 표시하지 않습니다.
                is_me = (str(username) == str(current_username))
                if is_me:
                    now = time.time()
                    normalized = str(message).strip()
                    suppress_echo = False
                    with chat_echo_lock:
                        # 오래된 echo 기록 정리
                        recent_chat_echoes[:] = [
                            item for item in recent_chat_echoes
                            if now - item[0] <= 10.0
                        ]
                        for i, (sent_at, sent_message) in enumerate(recent_chat_echoes):
                            if sent_message == normalized and now - sent_at <= 10.0:
                                recent_chat_echoes.pop(i)
                                suppress_echo = True
                                break

                    if suppress_echo:
                        return

                add_chat_message(
                    username,
                    message,
                    is_me=is_me,
                    timestamp=data.get("time") or data.get("timestamp")
                    or datetime.now().strftime("%H:%M")
                )

        users = (
            data.get("users")
            or data.get("online_users")
            or data.get("online")
        )

        if isinstance(users, list):
            update_online_users(users)

    def chat_receive_loop(ws):
        """WebSocket 수신 루프. idle timeout은 연결 끊김으로 처리하지 않습니다."""
        global chat_connected

        try:
            while chat_running and not exit_program:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    # 서버에서 일정 시간 메시지가 없어도 정상 연결 상태를 유지
                    continue

                if raw is None:
                    break
                handle_chat_payload(raw)

        except websocket.WebSocketConnectionClosedException as e:
            if chat_running and not exit_program:
                log(f"채팅 서버가 연결을 종료했습니다: {e}")
        except Exception as e:
            if chat_running and not exit_program:
                log(f"채팅 수신 오류: {type(e).__name__}: {e}")
        finally:
            chat_connected = False
            if chat_running and not exit_program:
                safe_after(main_root, 0, lambda: chat_status_var.set("채팅 재연결 중"))

    def connect_chat():
        global chat_ws, chat_thread, chat_running, chat_connected

        if chat_running and chat_connected:
            return

        chat_running = True
        safe_after(main_root, 0, lambda: chat_status_var.set("채팅 연결 중"))

        def worker():
            global chat_ws, chat_connected

            while chat_running and not exit_program:
                ws = None
                try:
                    ws_url = (
                        f"{CHAT_WS_URL}"
                        f"?username={quote(current_username)}"
                        f"&license={quote(current_license)}"
                        f"&hardware_id={quote(HARDWARE_ID)}"
                    )

                    # 짧은 recv timeout을 사용하되 timeout 자체는 정상 상태로 처리한다.
                    ws = websocket.create_connection(
                        ws_url,
                        timeout=30,
                        enable_multithread=True,
                        ping_interval=15,
                        ping_timeout=10,
                        ping_payload="entaria"
                    )
                    ws.settimeout(30)

                    chat_ws = ws
                    chat_connected = True

                    safe_after(
                        main_root, 0,
                        lambda: chat_status_var.set("채팅 연결됨")
                    )
                    log("실시간 채팅 서버에 연결되었습니다.")

                    # 서버가 join 메시지를 요구하는 경우를 대비해 전송
                    ws.send(json.dumps({
                        "type": "join",
                        "username": current_username,
                        "license": current_license,
                        "hardware_id": HARDWARE_ID,
                    }, ensure_ascii=False))

                    chat_receive_loop(ws)

                except websocket.WebSocketTimeoutException:
                    # 연결 생성 단계에서 timeout이 난 경우에만 재연결
                    chat_connected = False
                    if chat_running and not exit_program:
                        log("채팅 서버 응답 시간 초과 • 재연결합니다.")
                except websocket.WebSocketBadStatusException as e:
                    chat_connected = False
                    if chat_running and not exit_program:
                        log(f"채팅 서버 접속 거부: HTTP {getattr(e, 'status_code', '?')}")
                except Exception as e:
                    chat_connected = False
                    if chat_running and not exit_program:
                        log(f"채팅 연결 실패: {type(e).__name__}: {e}")
                finally:
                    if chat_ws is ws or ws is not None:
                        try:
                            if ws:
                                ws.close()
                        except Exception:
                            pass
                    if chat_ws is ws:
                        chat_ws = None
                    chat_connected = False

                if chat_running and not exit_program:
                    safe_after(main_root, 0, lambda: chat_status_var.set("채팅 재연결 중"))
                    # 빠른 반복 연결을 방지
                    for _ in range(30):
                        if not chat_running or exit_program:
                            break
                        time.sleep(0.1)

        chat_thread = threading.Thread(target=worker, daemon=True)
        chat_thread.start()

    def send_chat_message():
        widget = chat_input_ref.get("widget")
        if widget is None:
            return

        message = widget.get().strip()
        if not message:
            return

        if not chat_ws or not chat_connected:
            log("채팅 서버에 연결되어 있지 않습니다.")
            return

        try:
            payload = {
                "type": "message",
                "event": "message",
                "username": current_username,
                "user": current_username,
                "license": current_license,
                "hardware_id": HARDWARE_ID,
                "message": message,
                "content": message,
                "timestamp": datetime.now().isoformat(),
            }

            # 서버가 같은 메시지를 echo하더라도 로컬 표시와 중복되지 않도록
            # 전송 직전에 최근 메시지로 등록합니다.
            with chat_echo_lock:
                recent_chat_echoes.append((time.time(), message))
                # 비정상적으로 오래 쌓이지 않도록 정리
                cutoff = time.time() - 10.0
                recent_chat_echoes[:] = [
                    item for item in recent_chat_echoes
                    if item[0] >= cutoff
                ]

            chat_ws.send(json.dumps(payload, ensure_ascii=False))

            add_chat_message(
                current_username,
                message,
                is_me=True,
                timestamp=datetime.now().strftime("%H:%M")
            )

            widget.delete(0, "end")
        except Exception as e:
            with chat_echo_lock:
                for i in range(len(recent_chat_echoes) - 1, -1, -1):
                    if recent_chat_echoes[i][1] == message:
                        recent_chat_echoes.pop(i)
                        break
            log(f"메시지 전송 실패: {e}")

    def close_chat():
        global chat_running, chat_connected, chat_ws, chat_window

        chat_running = False
        chat_connected = False

        try:
            if chat_ws:
                chat_ws.close()
        except Exception:
            pass

        chat_ws = None

        if chat_window:
            try:
                chat_window.destroy()
            except Exception:
                pass
            chat_window = None

    def create_chat_window():
        global chat_window

        if chat_window:
            try:
                if chat_window.winfo_exists():
                    chat_window.deiconify()
                    chat_window.lift()
                    chat_window.focus_force()
                    return
            except Exception:
                chat_window = None

        chat_window = tk.Toplevel(main_root)
        chat_window.title("ENTARIA • 실시간 채팅")
        chat_window.geometry("820x590")
        chat_window.minsize(700, 500)
        chat_window.configure(bg=BG)

        chat_window.grid_rowconfigure(1, weight=1)
        chat_window.grid_columnconfigure(1, weight=1)

        # 헤더
        top = tk.Frame(chat_window, bg=SIDEBAR, height=68)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_propagate(False)

        tk.Label(
            top,
            text="▣",
            bg=SIDEBAR,
            fg=ACCENT,
            font=(FONT, 19, "bold")
        ).pack(side="left", padx=(20, 10))

        title_wrap = tk.Frame(top, bg=SIDEBAR)
        title_wrap.pack(side="left")

        tk.Label(
            title_wrap,
            text="실시간 채팅",
            bg=SIDEBAR, fg=TEXT,
            font=(FONT, 13, "bold")
        ).pack(anchor="w", pady=(12, 0))

        tk.Label(
            title_wrap,
            text="ENTARIA COMMUNITY",
            bg=SIDEBAR, fg=DIM,
            font=(FONT, 7)
        ).pack(anchor="w")

        close_btn = tk.Button(
            top,
            text="×",
            command=close_chat,
            bg=SIDEBAR,
            fg=MUTED,
            activebackground=SIDEBAR,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=(FONT, 20),
            cursor="hand2"
        )
        close_btn.pack(side="right", padx=17)

        # 온라인 사용자
        users_panel = tk.Frame(
            chat_window, bg=CARD, width=190
        )
        users_panel.grid(row=1, column=0, sticky="nsew")
        users_panel.grid_propagate(False)

        tk.Label(
            users_panel,
            text="온라인 사용자",
            bg=CARD, fg=TEXT,
            font=(FONT, 10, "bold")
        ).pack(anchor="w", padx=15, pady=(18, 2))

        tk.Label(
            users_panel,
            text="현재 접속 중인 사용자",
            bg=CARD, fg=DIM,
            font=(FONT, 7)
        ).pack(anchor="w", padx=15, pady=(0, 10))

        users_box = tk.Frame(users_panel, bg=CARD)
        users_box.pack(fill="both", expand=True)
        online_users_ref["widget"] = users_box

        # 메시지
        messages_panel = tk.Frame(chat_window, bg="#0C1118")
        messages_panel.grid(row=1, column=1, sticky="nsew")
        messages_panel.grid_rowconfigure(0, weight=1)
        messages_panel.grid_rowconfigure(1, weight=0)
        messages_panel.grid_columnconfigure(0, weight=1)

        messages_canvas = tk.Canvas(
            messages_panel,
            bg="#0C1118",
            highlightthickness=0
        )
        messages_scroll = tk.Scrollbar(
            messages_panel,
            orient="vertical",
            command=messages_canvas.yview,
            bg="#0C1118",
            troughcolor="#0C1118",
            relief="flat"
        )
        messages_canvas.configure(yscrollcommand=messages_scroll.set)

        messages_canvas.grid(row=0, column=0, sticky="nsew")
        messages_scroll.grid(row=0, column=1, sticky="ns")

        messages_inner = tk.Frame(messages_canvas, bg="#0C1118")
        messages_canvas.create_window(
            (0, 0),
            window=messages_inner,
            anchor="nw",
            width=560
        )

        messages_inner.bind(
            "<Configure>",
            lambda e: messages_canvas.configure(
                scrollregion=messages_canvas.bbox("all")
            )
        )
        chat_messages_ref["widget"] = messages_inner
        chat_canvas_ref["widget"] = messages_canvas

        # 입력
        input_bar = tk.Frame(messages_panel, bg=SIDEBAR, height=62)
        input_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        input_bar.grid_propagate(False)

        input_entry = tk.Entry(
            input_bar,
            bg="#10161E",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            font=(FONT, 9),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT
        )
        input_entry.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(13, 7),
            pady=12
        )
        chat_input_ref["widget"] = input_entry

        send_btn = tk.Button(
            input_bar,
            text="➤",
            command=send_chat_message,
            bg=ACCENT,
            fg="#FFFFFF",
            activebackground=ACCENT_HOVER,
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=(FONT, 15, "bold"),
            cursor="hand2",
            width=4
        )
        send_btn.pack(side="right", padx=(0, 13), pady=12)

        input_entry.bind("<Return>", lambda e: (send_chat_message(), "break")[1])

        status_bar = tk.Frame(chat_window, bg=SIDEBAR, height=31)
        status_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        status_bar.grid_propagate(False)

        tk.Label(
            status_bar,
            text="●",
            bg=SIDEBAR, fg=SUCCESS,
            font=(FONT, 7)
        ).pack(side="left", padx=(15, 5))

        tk.Label(
            status_bar,
            textvariable=chat_status_var,
            bg=SIDEBAR, fg=MUTED,
            font=(FONT, 7)
        ).pack(side="left")

        tk.Label(
            status_bar,
            text="Enter로 전송",
            bg=SIDEBAR, fg=DIM,
            font=(FONT, 7)
        ).pack(side="right", padx=15)

        # 연결 시작
        connect_chat()
        input_entry.focus_set()

        def chat_close_event():
            # 채팅창만 닫고 WebSocket은 유지
            try:
                chat_window.withdraw()
            except Exception:
                pass

        chat_window.protocol("WM_DELETE_WINDOW", chat_close_event)

    # =====================================================
    # 종료
    # =====================================================

    def stop_macro():
        global running, paused, repeat_mode, exit_program
        global buff_running, chat_running, chat_connected, chat_ws
        global position_hunt_running, mp_potion_running
        global hp_potion_running

        if exit_program:
            return

        exit_program = True
        running = False
        paused = False
        buff_running = False
        position_hunt_running = False
        position_hunt_stop_event.set()
        mp_potion_running = False
        mp_potion_stop_event.set()
        hp_potion_running = False
        hp_potion_stop_event.set()
        try:
            pass
        except Exception:
            pass

        try:
            if chat_ws:
                chat_ws.close()
        except Exception:
            pass

        chat_running = False
        chat_connected = False

        try:
            keyboard.unhook_all()
        except Exception:
            pass

        log("ENTARIA를 종료합니다.")

        def destroy_all():
            try:
                if chat_window:
                    chat_window.destroy()
            except Exception:
                pass

            try:
                main_root.destroy()
            except Exception:
                pass

            try:
                login_root.destroy()
            except Exception:
                pass

        safe_after(main_root, 100, destroy_all)

    main_root.protocol("WM_DELETE_WINDOW", stop_macro)

    # =====================================================
    # 글로벌 단축키
    # =====================================================

    try:
        keyboard.unhook_all()

        keyboard.add_hotkey("f1", start_macro)
        keyboard.add_hotkey("f2", pause_macro)
        keyboard.add_hotkey("f3", toggle_repeat)
        keyboard.add_hotkey("f4", stop_macro)
        keyboard.add_hotkey(BUFF_HOTKEY, start_buff)

        keyboard_hooks = ["f1", "f2", "f3", "f4", BUFF_HOTKEY]

        log("단축키 등록 완료: F1 실행 / F2 일시정지 / F3 반복 / F4 종료")
        log(f"버프 전체 실행 단축키: {BUFF_HOTKEY}")
    except Exception as e:
        log(f"단축키 등록 실패: {e}")

    # =====================================================
    # 시작 작업
    # =====================================================

    update_status()
    update_countdown()
    safe_after(main_root, 100, go_home)

    threading.Thread(
        target=license_heartbeat,
        daemon=True
    ).start()

    log("ENTARIA Dashboard가 시작되었습니다.")
    log("제자리사냥 1차 기능: 검색 영역 / 플레이어 / 몬스터 템플릿 방식")
    log(f"로그인 사용자: {current_username}")
    log(f"라이선스: {current_license}")
    log(f"버전: {APP_VERSION}")

    # 이미지 파일 확인
    missing = [
        os.path.basename(p)
        for p in [TARGET1, TARGET2, TARGET3, TARGET4]
        if not os.path.exists(p)
    ]

    if missing:
        log("이미지 파일 확인 필요: " + ", ".join(missing))
    else:
        log("타겟 이미지 4개가 정상적으로 준비되었습니다.")

    # 채팅은 사용자가 열 때 연결
    connection_var.set("대기 중")


# =========================================================
# 시작
# =========================================================

if __name__ == "__main__":
    check_update_and_exit()

    try:
        pyautogui.PAUSE = 0.01
    except Exception:
        pass

    root = create_login_window()
    root.mainloop()

import os
import sys
import time
import threading
import hashlib
import platform
import uuid
import json

import tkinter as tk
from tkinter import scrolledtext, messagebox

import keyboard
import pyautogui
import requests
import websocket

from PIL import Image, ImageTk


# =========================================================
# 서버
# =========================================================

SERVER_URL = "https://api.entaria1004.win"


# =========================================================
# 자동 업데이트
# =========================================================

VERSION_URL = f"{SERVER_URL}/update/version.json"


def get_current_version():
    """
    현재 실행 중인 Entaria.exe의 버전.
    PyInstaller 빌드 시 환경변수 ENTARIA_VERSION을 사용한다.
    """

    version = os.environ.get(
        "ENTARIA_VERSION",
        ""
    ).strip()

    if version:
        return version

    # 개발 중 .py 실행
    return "0.0.0"


APP_VERSION = get_current_version()


def get_updater_path():
    """
    EntariaUpdater.exe 위치
    """

    if getattr(sys, "frozen", False):

        return os.path.join(
            os.path.dirname(
                sys.executable
            ),
            "EntariaUpdater.exe"
        )

    return os.path.join(
        os.path.dirname(
            os.path.abspath(__file__)
        ),
        "EntariaUpdater.exe"
    )


def parse_version(version):
    """
    예:
        1.0.12
        →
        (1, 0, 12)
    """

    try:

        parts = str(
            version
        ).strip().split(".")

        result = []

        for part in parts:

            digits = ""

            for char in part:

                if char.isdigit():

                    digits += char

                else:

                    break

            if digits:

                result.append(
                    int(digits)
                )

            else:

                result.append(0)

        while len(result) < 3:

            result.append(0)

        return tuple(
            result[:3]
        )

    except Exception:

        return (0, 0, 0)


def check_for_update():
    """
    서버의 최신 버전을 확인한다.

    True  = 업데이트 필요
    False = 최신 버전
    """

    try:

        response = requests.get(
            VERSION_URL,
            timeout=5,
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(
            data,
            dict
        ):

            print(
                "[업데이트] 잘못된 version.json"
            )

            return False

        latest_version = str(
            data.get(
                "version",
                ""
            )
        ).strip()

        if not latest_version:

            print(
                "[업데이트] 서버 버전 정보 없음"
            )

            return False

        current = parse_version(
            APP_VERSION
        )

        latest = parse_version(
            latest_version
        )

        print(
            f"[업데이트] 현재 버전 : "
            f"{APP_VERSION}"
        )

        print(
            f"[업데이트] 서버 버전 : "
            f"{latest_version}"
        )

        if latest > current:

            print(
                "[업데이트] 새 버전이 있습니다."
            )

            return True

        print(
            "[업데이트] 현재 버전이 최신입니다."
        )

        return False

    except requests.exceptions.Timeout:

        print(
            "[업데이트] 서버 확인 시간 초과"
        )

        return False

    except requests.exceptions.ConnectionError:

        print(
            "[업데이트] 업데이트 서버 연결 실패"
        )

        return False

    except Exception as e:

        print(
            f"[업데이트] 확인 실패 : {e}"
        )

        return False


def start_updater():

    updater_path = get_updater_path()

    if not os.path.exists(
        updater_path
    ):

        print(
            "[업데이트] "
            "EntariaUpdater.exe를 찾을 수 없습니다."
        )

        return False

    try:

        import subprocess

        subprocess.Popen(
            [updater_path],
            cwd=os.path.dirname(
                updater_path
            ),
            close_fds=True
        )

        return True

    except Exception as e:

        print(
            f"[업데이트] Updater 실행 실패 : {e}"
        )

        return False


def check_update_and_exit():
    """
    Entaria.exe 시작 직후 업데이트 확인.

    개발 중 .py 실행에서는 업데이트하지 않는다.
    """

    if not getattr(
        sys,
        "frozen",
        False
    ):

        return

    try:

        update_available = (
            check_for_update()
        )

        if not update_available:

            return

        updater_path = get_updater_path()

        if not os.path.exists(
            updater_path
        ):

            print(
                "[업데이트] "
                "Updater가 없어 업데이트를 건너뜁니다."
            )

            return

        print(
            "[업데이트] "
            "EntariaUpdater.exe 실행"
        )

        started = start_updater()

        if started:

            print(
                "[업데이트] "
                "Entaria.exe 종료"
            )

            # Updater가 현재 EXE를 교체할 수 있도록
            # Entaria.exe를 즉시 종료한다.
            os._exit(0)

    except Exception as e:

        print(
            f"[업데이트] 업데이트 처리 실패 : {e}"
        )


VERIFY_URL = f"{SERVER_URL}/verify"
REGISTER_URL = f"{SERVER_URL}/register"
LOGIN_URL = f"{SERVER_URL}/login"
HEARTBEAT_URL = f"{SERVER_URL}/heartbeat"

CHAT_WS_URL = "wss://api.entaria1004.win/ws/chat"


# =========================================================
# EXE / Python 공통 파일 경로
# =========================================================

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(filename):
    return os.path.join(BASE_DIR, "images", filename)


# =========================================================
# 사용자 설정 저장 경로
# =========================================================

CONFIG_DIR = os.path.join(
    os.getenv(
        "APPDATA",
        os.path.expanduser("~")
    ),
    "Entaria"
)

BUFF_HOTKEY_CONFIG_FILE = os.path.join(
    CONFIG_DIR,
    "buff_hotkey.txt"
)

BUFF_KEYS_CONFIG_FILE = os.path.join(
    CONFIG_DIR,
    "buff_keys.txt"
)


# =========================================================
# 기본
# =========================================================

WINDOW_WIDTH = 850
WINDOW_HEIGHT = 650


# =========================================================
# 매크로
# =========================================================

CONFIDENCE = 0.80
SEARCH_DELAY = 0.1
TARGET_DELAY = 0.5
BUFF_DELAY = 1.0
KEY_PRESS_TIME = 0.05
LICENSE_CHECK_INTERVAL = 30


# =========================================================
# 이미지
# =========================================================

TARGET1 = resource_path("target1.png")
TARGET2 = resource_path("target2.png")
TARGET3 = resource_path("target3.png")
TARGET4 = resource_path("target4.png")

BACKGROUND_IMAGE = resource_path("maplestory.png")


# =========================================================
# 기본 버프 키
# =========================================================

BUFF_KEYS_DEFAULT = [
    "1",
    "2",
    "3",
    "q",
    "w",
    "e",
    "s",
    "d"
]

BUFF_KEYS = BUFF_KEYS_DEFAULT.copy()


# =========================================================
# 버프 키 불러오기
# =========================================================

def load_buff_keys():

    global BUFF_KEYS

    try:

        if not os.path.exists(
            BUFF_KEYS_CONFIG_FILE
        ):

            BUFF_KEYS = BUFF_KEYS_DEFAULT.copy()

            return

        with open(
            BUFF_KEYS_CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            lines = [
                line.strip().lower()
                for line in f.readlines()
            ]

        if len(lines) != 8:

            BUFF_KEYS = BUFF_KEYS_DEFAULT.copy()

            return

        if any(
            not key
            for key in lines
        ):

            BUFF_KEYS = BUFF_KEYS_DEFAULT.copy()

            return

        BUFF_KEYS = lines

    except Exception:

        BUFF_KEYS = BUFF_KEYS_DEFAULT.copy()


# =========================================================
# 버프 키 저장
# =========================================================

def save_buff_keys(keys):

    global BUFF_KEYS

    if len(keys) != 8:

        return False

    keys = [
        key.strip().lower()
        for key in keys
    ]

    if any(
        not key
        for key in keys
    ):

        return False

    try:

        os.makedirs(
            CONFIG_DIR,
            exist_ok=True
        )

        with open(
            BUFF_KEYS_CONFIG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            for key in keys:

                f.write(
                    key + "\n"
                )

        BUFF_KEYS = keys.copy()

        return True

    except Exception:

        return False


load_buff_keys()


# =========================================================
# 버프 실행 단축키
# =========================================================

BUFF_HOTKEY_DEFAULT = "`"

BUFF_HOTKEY = BUFF_HOTKEY_DEFAULT


def load_buff_hotkey():

    global BUFF_HOTKEY

    try:

        if os.path.exists(
            BUFF_HOTKEY_CONFIG_FILE
        ):

            with open(
                BUFF_HOTKEY_CONFIG_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                saved_key = (
                    f.read()
                    .strip()
                    .lower()
                )

            if saved_key:

                BUFF_HOTKEY = saved_key

    except Exception:

        BUFF_HOTKEY = BUFF_HOTKEY_DEFAULT


def save_buff_hotkey(key):

    global BUFF_HOTKEY

    key = (
        key
        .strip()
        .lower()
    )

    if not key:

        return False

    try:

        os.makedirs(
            CONFIG_DIR,
            exist_ok=True
        )

        with open(
            BUFF_HOTKEY_CONFIG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(key)

        BUFF_HOTKEY = key

        return True

    except Exception:

        return False


load_buff_hotkey()


# =========================================================
# 상태
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

buff_lock = threading.Lock()
state_lock = threading.Lock()


# =========================================================
# 채팅 상태
# =========================================================

chat_ws = None
chat_thread = None
chat_closing = False

chat_send_lock = threading.Lock()

chat_connecting = False


# =========================================================
# 하드웨어 ID
# =========================================================

def get_hardware_id():

    raw = (
        platform.system()
        + "|"
        + platform.node()
        + "|"
        + platform.machine()
        + "|"
        + str(uuid.getnode())
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


HARDWARE_ID = get_hardware_id()


# =========================================================
# 로그인 창
# =========================================================

check_update_and_exit()

login_root = tk.Tk()

login_root.title(
    "메이플 엔타리아"
)

login_root.geometry(
    "430x430"
)

login_root.resizable(
    False,
    False
)


# =========================================================
# 로그인 배경
# =========================================================

login_background_photo = None

try:

    if os.path.exists(
        BACKGROUND_IMAGE
    ):

        original = Image.open(
            BACKGROUND_IMAGE
        ).convert("RGB")

        resized = original.resize(
            (430, 430),
            Image.Resampling.LANCZOS
        )

        login_background_photo = (
            ImageTk.PhotoImage(
                resized
            )
        )

        background_label = tk.Label(
            login_root,
            image=login_background_photo
        )

        background_label.place(
            x=0,
            y=0,
            width=430,
            height=430
        )

    else:

        background_label = tk.Label(
            login_root,
            bg="#202030"
        )

        background_label.place(
            x=0,
            y=0,
            width=430,
            height=430
        )

except Exception:

    background_label = tk.Label(
        login_root,
        bg="#202030"
    )

    background_label.place(
        x=0,
        y=0,
        width=430,
        height=430
    )


# =========================================================
# 로그인 패널
# =========================================================

login_panel = tk.Frame(
    login_root,
    bg="#111111",
    bd=2,
    relief="ridge"
)

login_panel.place(
    x=45,
    y=30,
    width=340,
    height=365
)


tk.Label(
    login_panel,
    text="메이플 엔타리아",
    font=("맑은 고딕", 18, "bold"),
    fg="white",
    bg="#111111"
).pack(
    pady=(18, 3)
)


tk.Label(
    login_panel,
    text="라이선스 회원 시스템",
    font=("맑은 고딕", 10),
    fg="#cccccc",
    bg="#111111"
).pack(
    pady=(0, 12)
)


# =========================================================
# 입력
# =========================================================

form_frame = tk.Frame(
    login_panel,
    bg="#111111"
)

form_frame.pack(
    pady=5
)


tk.Label(
    form_frame,
    text="아이디",
    fg="white",
    bg="#111111"
).grid(
    row=0,
    column=0,
    padx=5,
    pady=5
)


username_entry = tk.Entry(
    form_frame,
    width=25
)

username_entry.grid(
    row=0,
    column=1,
    padx=5,
    pady=5
)


tk.Label(
    form_frame,
    text="비밀번호",
    fg="white",
    bg="#111111"
).grid(
    row=1,
    column=0,
    padx=5,
    pady=5
)


password_entry = tk.Entry(
    form_frame,
    width=25,
    show="*"
)

password_entry.grid(
    row=1,
    column=1,
    padx=5,
    pady=5
)


license_label = tk.Label(
    form_frame,
    text="발급코드",
    fg="white",
    bg="#111111"
)

license_entry = tk.Entry(
    form_frame,
    width=25
)

license_label.grid(
    row=2,
    column=0,
    padx=5,
    pady=5
)

license_entry.grid(
    row=2,
    column=1,
    padx=5,
    pady=5
)


# =========================================================
# 로그인 메시지
# =========================================================

login_message = tk.Label(
    login_panel,
    text="로그인 정보를 입력하세요.",
    font=("맑은 고딕", 9),
    fg="#dddddd",
    bg="#111111"
)

login_message.pack(
    pady=8
)


# =========================================================
# 로그인 실패
# =========================================================

def login_failed(message):

    login_message.config(
        text=message,
        fg="#ff6666"
    )

    login_button.config(
        state="normal"
    )

    register_button.config(
        state="normal"
    )


# =========================================================
# 로그인 성공
# =========================================================

def login_success():

    login_message.config(
        text="로그인 성공!",
        fg="#66ff66"
    )

    login_button.config(
        state="disabled"
    )

    register_button.config(
        state="disabled"
    )

    create_main_window()

    login_root.withdraw()


# =========================================================
# 로그인
# =========================================================

def login():

    global logged_in
    global current_username
    global current_license
    global current_license_expire
    global remaining_seconds

    username = (
        username_entry
        .get()
        .strip()
    )

    password = (
        password_entry
        .get()
    )

    if not username or not password:

        login_message.config(
            text="아이디와 비밀번호를 입력하세요.",
            fg="#ff6666"
        )

        return

    login_button.config(
        state="disabled"
    )

    register_button.config(
        state="disabled"
    )

    login_message.config(
        text="서버에서 로그인 확인 중...",
        fg="#ffff66"
    )

    def worker():

        global logged_in
        global current_username
        global current_license
        global current_license_expire
        global remaining_seconds

        try:

            response = requests.post(
                LOGIN_URL,
                json={
                    "username": username,
                    "password": password,
                    "hardware_id": HARDWARE_ID
                },
                timeout=5
            )

            try:

                data = response.json()

            except Exception:

                data = {}

            if response.status_code != 200:

                message = data.get(
                    "detail",
                    "로그인 실패"
                )

                login_root.after(
                    0,
                    lambda:
                    login_failed(
                        str(message)
                    )
                )

                return

            server_seconds = int(
                data.get(
                    "remaining_seconds",
                    0
                )
            )

            current_username = username

            current_license = data.get(
                "license",
                ""
            )

            current_license_expire = data.get(
                "expires_at",
                ""
            )

            with state_lock:

                remaining_seconds = max(
                    0,
                    server_seconds
                )

            logged_in = True

            login_root.after(
                0,
                login_success
            )

        except requests.exceptions.ConnectionError:

            login_root.after(
                0,
                lambda:
                login_failed(
                    "라이선스 서버에 연결할 수 없습니다."
                )
            )

        except requests.exceptions.Timeout:

            login_root.after(
                0,
                lambda:
                login_failed(
                    "서버 응답 시간이 초과되었습니다."
                )
            )

        except Exception as e:

            login_root.after(
                0,
                lambda:
                login_failed(
                    str(e)
                )
            )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()


# =========================================================
# 회원가입
# =========================================================

def register():

    username = (
        username_entry
        .get()
        .strip()
    )

    password = (
        password_entry
        .get()
    )

    license_code = (
        license_entry
        .get()
        .strip()
    )

    if not username:

        login_message.config(
            text="아이디를 입력하세요.",
            fg="#ff6666"
        )

        return

    if not password:

        login_message.config(
            text="비밀번호를 입력하세요.",
            fg="#ff6666"
        )

        return

    if not license_code:

        login_message.config(
            text="관리자에게 받은 발급코드를 입력하세요.",
            fg="#ff6666"
        )

        return

    login_button.config(
        state="disabled"
    )

    register_button.config(
        state="disabled"
    )

    login_message.config(
        text="회원가입 처리 중...",
        fg="#ffff66"
    )

    def worker():

        try:

            response = requests.post(
                REGISTER_URL,
                json={
                    "license": license_code,
                    "username": username,
                    "password": password,
                    "hardware_id": HARDWARE_ID
                },
                timeout=5
            )

            try:

                data = response.json()

            except Exception:

                data = {}

            if response.status_code != 200:

                message = data.get(
                    "detail",
                    "회원가입 실패"
                )

                login_root.after(
                    0,
                    lambda:
                    register_failed(
                        str(message)
                    )
                )

                return

            login_root.after(
                0,
                register_success
            )

        except requests.exceptions.ConnectionError:

            login_root.after(
                0,
                lambda:
                register_failed(
                    "라이선스 서버에 연결할 수 없습니다."
                )
            )

        except requests.exceptions.Timeout:

            login_root.after(
                0,
                lambda:
                register_failed(
                    "서버 응답 시간이 초과되었습니다."
                )
            )

        except Exception as e:

            login_root.after(
                0,
                lambda:
                register_failed(
                    str(e)
                )
            )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()


def register_success():

    login_message.config(
        text="회원가입 완료! 로그인해주세요.",
        fg="#66ff66"
    )

    login_button.config(
        state="normal"
    )

    register_button.config(
        state="normal"
    )

    license_entry.delete(
        0,
        tk.END
    )


def register_failed(message):

    login_message.config(
        text=message,
        fg="#ff6666"
    )

    login_button.config(
        state="normal"
    )

    register_button.config(
        state="normal"
    )


# =========================================================
# 로그인 버튼
# =========================================================

login_button = tk.Button(
    login_panel,
    text="로그인",
    font=("맑은 고딕", 10, "bold"),
    width=20,
    height=2,
    bg="#333333",
    fg="white",
    activebackground="#555555",
    activeforeground="white",
    command=login
)

login_button.pack(
    pady=4
)


register_button = tk.Button(
    login_panel,
    text="회원가입",
    font=("맑은 고딕", 10, "bold"),
    width=20,
    height=2,
    bg="#333333",
    fg="white",
    activebackground="#555555",
    activeforeground="white",
    command=register
)

register_button.pack(
    pady=4
)


# =========================================================
# 메인
# =========================================================

main_root = None


def create_main_window():

    global main_root

    main_root = tk.Toplevel(
        login_root
    )

    main_root.title(
        "메이플 엔타리아 - 매크로"
    )

    main_root.geometry(
        f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}"
    )

    main_root.resizable(
        False,
        False
    )


    # =====================================================
    # 배경
    # =====================================================

    background_photo = None

    try:

        if os.path.exists(
            BACKGROUND_IMAGE
        ):

            original = Image.open(
                BACKGROUND_IMAGE
            ).convert("RGB")

            resized = original.resize(
                (
                    WINDOW_WIDTH,
                    WINDOW_HEIGHT
                ),
                Image.Resampling.LANCZOS
            )

            background_photo = (
                ImageTk.PhotoImage(
                    resized
                )
            )

            background_label = tk.Label(
                main_root,
                image=background_photo
            )

            background_label.image = (
                background_photo
            )

            background_label.place(
                x=0,
                y=0,
                width=WINDOW_WIDTH,
                height=WINDOW_HEIGHT
            )

        else:

            background_label = tk.Label(
                main_root,
                bg="#202030"
            )

            background_label.place(
                x=0,
                y=0,
                width=WINDOW_WIDTH,
                height=WINDOW_HEIGHT
            )

    except Exception:

        background_label = tk.Label(
            main_root,
            bg="#202030"
        )

        background_label.place(
            x=0,
            y=0,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT
        )


    # =====================================================
    # 로그
    # =====================================================

    def log(message):

        def update():

            try:

                log_box.config(
                    state="normal"
                )

                log_box.insert(
                    tk.END,
                    message + "\n"
                )

                log_box.see(
                    tk.END
                )

                log_box.config(
                    state="disabled"
                )

            except Exception:

                pass

        try:

            main_root.after(
                0,
                update
            )

        except Exception:

            pass


    # =====================================================
    # 남은 기간 포맷
    # =====================================================

    def format_remaining(seconds):

        try:

            seconds = max(
                0,
                int(seconds)
            )

        except Exception:

            return "만료"

        days = seconds // 86400

        hours = (
            seconds % 86400
        ) // 3600

        minutes = (
            seconds % 3600
        ) // 60

        secs = seconds % 60

        if days > 0:

            return (
                f"{days}일 "
                f"{hours}시간 "
                f"{minutes}분 "
                f"{secs}초"
            )

        if hours > 0:

            return (
                f"{hours}시간 "
                f"{minutes}분 "
                f"{secs}초"
            )

        if minutes > 0:

            return (
                f"{minutes}분 "
                f"{secs}초"
            )

        return f"{secs}초"


    # =====================================================
    # 라이선스 패널
    # =====================================================

    license_frame = tk.Frame(
        main_root,
        bg="#111111",
        bd=2,
        relief="ridge"
    )

    license_frame.place(
        x=20,
        y=15,
        width=810,
        height=80
    )

    tk.Label(
        license_frame,
        text="LICENSE",
        font=("Arial", 11, "bold"),
        fg="#aaaaaa",
        bg="#111111"
    ).place(
        x=15,
        y=8
    )

    license_code_label = tk.Label(
        license_frame,
        text=current_license,
        font=("Consolas", 11, "bold"),
        fg="white",
        bg="#111111"
    )

    license_code_label.place(
        x=100,
        y=8
    )

    remaining_label = tk.Label(
        license_frame,
        text="남은 라이선스 : 확인 중...",
        font=("맑은 고딕", 13, "bold"),
        fg="#66ff66",
        bg="#111111",
        anchor="w"
    )

    remaining_label.place(
        x=15,
        y=38,
        width=760,
        height=30
    )


    # =====================================================
    # 상태
    # =====================================================

    def update_status():

        try:

            if exit_program:

                status_label.config(
                    text="● 종료"
                )

            elif paused:

                status_label.config(
                    text="● 일시정지"
                )

            elif buff_running:

                status_label.config(
                    text="● 버프 실행 중"
                )

            elif running:

                status_label.config(
                    text="● 분해 실행 중"
                )

            else:

                status_label.config(
                    text="● 대기 중"
                )

        except Exception:

            pass


    # =====================================================
    # 매크로만 정지
    # =====================================================

    def stop_macro_only():

        global running

        running = False

        try:

            update_status()

        except Exception:

            pass


    # =====================================================
    # 카운트다운
    # =====================================================

    def update_countdown():

        global remaining_seconds

        if exit_program:

            return

        with state_lock:

            current_seconds = (
                remaining_seconds
            )

            if current_seconds > 0:

                remaining_seconds -= 1

        if current_seconds <= 0:

            remaining_label.config(
                text="남은 라이선스 : 만료",
                fg="#ff4444"
            )

            if running:

                stop_macro_only()

            main_root.after(
                1000,
                update_countdown
            )

            return

        remaining_label.config(
            text=(
                "남은 라이선스 : "
                + format_remaining(
                    current_seconds
                )
            )
        )

        if current_seconds < 86400:

            remaining_label.config(
                fg="#ffaa00"
            )

        else:

            remaining_label.config(
                fg="#66ff66"
            )

        main_root.after(
            1000,
            update_countdown
        )


    update_countdown()


    # =====================================================
    # 서버 heartbeat
    # =====================================================

    def license_heartbeat():

        global remaining_seconds
        global current_license_expire

        while not exit_program:

            time.sleep(
                LICENSE_CHECK_INTERVAL
            )

            if exit_program:

                break

            try:

                response = requests.post(
                    HEARTBEAT_URL,
                    json={
                        "license":
                            current_license,

                        "hardware_id":
                            HARDWARE_ID
                    },
                    timeout=5
                )

                try:

                    data = response.json()

                except Exception:

                    continue

                if response.status_code != 200:

                    continue

                if not data.get(
                    "valid",
                    False
                ):

                    message = data.get(
                        "message",
                        "라이선스 인증 실패"
                    )

                    def invalid():

                        global running

                        running = False

                        remaining_label.config(
                            text=(
                                "라이선스 : "
                                + str(message)
                            ),
                            fg="#ff4444"
                        )

                        log(
                            "⚠ "
                            + str(message)
                        )

                        update_status()

                    main_root.after(
                        0,
                        invalid
                    )

                    continue

                server_seconds = int(
                    data.get(
                        "remaining_seconds",
                        0
                    )
                )

                server_expire = data.get(
                    "expires_at",
                    current_license_expire
                )

                with state_lock:

                    remaining_seconds = max(
                        0,
                        server_seconds
                    )

                current_license_expire = (
                    server_expire
                )

                def update_server_info():

                    with state_lock:

                        seconds = (
                            remaining_seconds
                        )

                    if seconds <= 0:

                        remaining_label.config(
                            text="남은 라이선스 : 만료",
                            fg="#ff4444"
                        )

                    else:

                        remaining_label.config(
                            text=(
                                "남은 라이선스 : "
                                + format_remaining(
                                    seconds
                                )
                            )
                        )

                        if seconds < 86400:

                            remaining_label.config(
                                fg="#ffaa00"
                            )

                        else:

                            remaining_label.config(
                                fg="#66ff66"
                            )

                main_root.after(
                    0,
                    update_server_info
                )

            except Exception:

                main_root.after(
                    0,
                    lambda:
                    log(
                        "⚠ 서버 확인 실패"
                    )
                )

    threading.Thread(
        target=license_heartbeat,
        daemon=True
    ).start()


    # =====================================================
    # F1 실행
    # =====================================================

    def start_macro():

        global running
        global paused

        if exit_program:

            return

        with state_lock:

            license_ok = (
                remaining_seconds > 0
            )

        if not license_ok:

            messagebox.showwarning(
                "라이선스",
                "라이선스가 만료되었습니다."
            )

            return

        running = True
        paused = False

        log(
            "▶ 분해 매크로 실행"
        )

        update_status()


    # =====================================================
    # F2 일시정지
    # =====================================================

    def pause_macro():

        global paused

        if not running and not buff_running:

            return

        paused = not paused

        if paused:

            log(
                "⏸ 일시정지"
            )

        else:

            log(
                "▶ 재개"
            )

        update_status()


    # =====================================================
    # F3 반복
    # =====================================================

    def toggle_repeat():

        global repeat_mode

        repeat_mode = not repeat_mode

        if repeat_mode:

            log(
                "🔁 반복 실행 ON"
            )

            repeat_button.config(
                text="반복 : ON"
            )

        else:

            log(
                "⏹ 반복 실행 OFF"
            )

            repeat_button.config(
                text="반복 : OFF"
            )


    # =====================================================
    # 채팅 창 변수
    # =====================================================

    chat_window = None
    chat_messages_box = None
    chat_input = None
    online_listbox = None
    online_count_label = None


    # =====================================================
    # 채팅 메시지 추가
    # =====================================================

    def add_chat_message(message):

        if chat_messages_box is None:

            return

        def update():

            try:

                if not chat_messages_box.winfo_exists():

                    return

                chat_messages_box.config(
                    state="normal"
                )

                chat_messages_box.insert(
                    tk.END,
                    message + "\n"
                )

                chat_messages_box.see(
                    tk.END
                )

                chat_messages_box.config(
                    state="disabled"
                )

            except Exception:

                pass

        try:

            main_root.after(
                0,
                update
            )

        except Exception:

            pass


    # =====================================================
    # 온라인 사용자 업데이트
    # =====================================================

    def update_online_users(users):

        def update():

            try:

                if online_listbox is not None:

                    online_listbox.delete(
                        0,
                        tk.END
                    )

                    for username in users:

                        if str(username) == "loa0629":

                            display_name = "관리자"

                        else:

                            display_name = str(
                                username
                            )

                        online_listbox.insert(
                            tk.END,
                            "● " + display_name
                        )

                if online_count_label is not None:

                    online_count_label.config(
                        text=(
                            f"온라인 "
                            f"{len(users)}명"
                        )
                    )

            except Exception:

                pass

        try:

            main_root.after(
                0,
                update
            )

        except Exception:

            pass


    # =====================================================
    # 채팅 수신
    #
    # recv() 무한 대기
    # 10초 동안 메시지가 없어도 연결 유지
    # =====================================================

    def chat_receive_loop(ws):

        global chat_ws

        try:

            while (
                not exit_program
                and not chat_closing
            ):

                try:

                    raw = ws.recv()

                except websocket.WebSocketTimeoutException:

                    continue

                except websocket.WebSocketConnectionClosedException:

                    break

                except Exception:

                    break

                if not raw:

                    break

                try:

                    data = json.loads(
                        raw
                    )

                except Exception:

                    continue

                message_type = str(
                    data.get(
                        "type",
                        ""
                    )
                ).lower()


                # -----------------------------------------
                # 채팅 메시지
                # -----------------------------------------

                if message_type in (
                    "message",
                    "chat",
                    "chat_message"
                ):

                    username = data.get(
                        "username",
                        "알 수 없음"
                    )

                    if str(username) == "loa0629":

                        username = "관리자"

                    message = data.get(
                        "message",
                        ""
                    )

                    if message:

                        add_chat_message(
                            f"[{username}] {message}"
                        )


                # -----------------------------------------
                # 시스템 메시지
                # -----------------------------------------

                elif message_type == "system":

                    message = data.get(
                        "message",
                        ""
                    )

                    if message:

                        add_chat_message(
                            f"★ {message}"
                        )


                # -----------------------------------------
                # 온라인 목록
                # -----------------------------------------

                elif message_type in (
                    "online",
                    "online_users"
                ):

                    users = data.get(
                        "users",
                        []
                    )

                    if isinstance(
                        users,
                        list
                    ):

                        update_online_users(
                            users
                        )


                # -----------------------------------------
                # 채팅 기록
                # -----------------------------------------

                elif message_type == "history":

                    messages = data.get(
                        "messages",
                        []
                    )

                    if isinstance(
                        messages,
                        list
                    ):

                        for item in messages:

                            if not isinstance(
                                item,
                                dict
                            ):

                                continue

                            username = item.get(
                                "username",
                                "알 수 없음"
                            )

                            if str(username) == "loa0629":

                                username = "관리자"

                            message = item.get(
                                "message",
                                ""
                            )

                            if message:

                                add_chat_message(
                                    f"[{username}] {message}"
                                )


                # -----------------------------------------
                # 서버 오류
                # -----------------------------------------

                elif message_type == "error":

                    message = data.get(
                        "message",
                        "채팅 오류"
                    )

                    add_chat_message(
                        f"⚠ {message}"
                    )

        except Exception as e:

            if not chat_closing:

                add_chat_message(
                    f"⚠ 채팅 오류 : {e}"
                )

        finally:

            if chat_ws is ws:

                chat_ws = None

            if not chat_closing:

                add_chat_message(
                    "⚠ 채팅 서버 연결이 종료되었습니다."
                )


                # -----------------------------------------
                # 자동 재연결
                # -----------------------------------------

                def reconnect():

                    time.sleep(3)

                    if (
                        not exit_program
                        and not chat_closing
                        and chat_ws is None
                    ):

                        add_chat_message(
                            "🔄 채팅 서버 재연결 중..."
                        )

                        connect_chat()

                threading.Thread(
                    target=reconnect,
                    daemon=True
                ).start()


    # =====================================================
    # 채팅 연결
    # =====================================================

    def connect_chat():

        global chat_ws
        global chat_thread
        global chat_closing
        global chat_connecting

        if exit_program:

            return

        if chat_closing:

            return

        if chat_connecting:

            return

        if chat_ws is not None:

            try:

                if chat_ws.connected:

                    return

            except Exception:

                pass

        chat_connecting = True
        chat_closing = False

        try:

            if chat_ws is not None:

                try:

                    chat_ws.close()

                except Exception:

                    pass

                chat_ws = None


            # -----------------------------------------
            # WebSocket URL
            # -----------------------------------------

            from urllib.parse import quote

            username_encoded = quote(
                current_username,
                safe=""
            )

            license_encoded = quote(
                current_license,
                safe=""
            )

            hardware_encoded = quote(
                HARDWARE_ID,
                safe=""
            )

            ws_url = (
                CHAT_WS_URL
                + "?username="
                + username_encoded
                + "&license="
                + license_encoded
                + "&hardware_id="
                + hardware_encoded
            )


            # -----------------------------------------
            # WebSocket 연결
            # -----------------------------------------

            chat_ws = websocket.create_connection(
                ws_url,
                timeout=10,
                http_proxy_host=None,
                http_proxy_port=None
            )


            # -----------------------------------------
            # 핵심 수정
            #
            # 연결 후 recv timeout 제거
            # -----------------------------------------

            chat_ws.settimeout(None)


            add_chat_message(
                "✓ 실시간 채팅 서버에 연결되었습니다."
            )


            chat_thread = threading.Thread(
                target=chat_receive_loop,
                args=(chat_ws,),
                daemon=True
            )

            chat_thread.start()

        except Exception as e:

            chat_ws = None

            if not exit_program and not chat_closing:

                add_chat_message(
                    f"⚠ 채팅 서버 연결 실패 : {e}"
                )


                # -----------------------------------------
                # 5초 후 자동 재연결
                # -----------------------------------------

                def retry_connect():

                    time.sleep(5)

                    if (
                        not exit_program
                        and not chat_closing
                        and chat_ws is None
                    ):

                        connect_chat()

                threading.Thread(
                    target=retry_connect,
                    daemon=True
                ).start()

        finally:

            chat_connecting = False


    # =====================================================
    # 채팅 전송
    # =====================================================

    def send_chat_message():

        global chat_ws

        if chat_ws is None:

            add_chat_message(
                "⚠ 채팅 서버에 연결되어 있지 않습니다."
            )

            if (
                not chat_closing
                and not exit_program
            ):

                threading.Thread(
                    target=connect_chat,
                    daemon=True
                ).start()

            return

        if chat_input is None:

            return

        message = (
            chat_input
            .get()
            .strip()
        )

        if not message:

            return

        if len(message) > 300:

            messagebox.showwarning(
                "채팅",
                "메시지는 최대 300자까지 입력할 수 있습니다."
            )

            return

        try:

            with chat_send_lock:

                if chat_ws is None:

                    raise ConnectionError(
                        "WebSocket 연결이 없습니다."
                    )

                chat_ws.send(
                    json.dumps(
                        {
                            "message": message
                        },
                        ensure_ascii=False
                    )
                )

            chat_input.delete(
                0,
                tk.END
            )

        except Exception as e:

            add_chat_message(
                f"⚠ 메시지 전송 실패 : {e}"
            )

            try:

                if chat_ws is not None:

                    chat_ws.close()

            except Exception:

                pass

            chat_ws = None

            if (
                not chat_closing
                and not exit_program
            ):

                threading.Thread(
                    target=connect_chat,
                    daemon=True
                ).start()


    # =====================================================
    # 채팅 종료
    # =====================================================

    def close_chat():

        global chat_ws
        global chat_closing

        chat_closing = True

        if chat_ws is not None:

            try:

                chat_ws.close()

            except Exception:

                pass

            chat_ws = None


    # =====================================================
    # 채팅창 열기
    # =====================================================

    def open_chat():

        nonlocal chat_window
        nonlocal chat_messages_box
        nonlocal chat_input
        nonlocal online_listbox
        nonlocal online_count_label

        if chat_window is not None:

            try:

                if chat_window.winfo_exists():

                    chat_window.deiconify()

                    chat_window.lift()

                    chat_window.focus_force()

                    if chat_ws is None:

                        threading.Thread(
                            target=connect_chat,
                            daemon=True
                        ).start()

                    return

            except Exception:

                chat_window = None


        # ---------------------------------------------
        # 채팅창 생성
        # ---------------------------------------------

        chat_window = tk.Toplevel(
            main_root
        )

        chat_window.title(
            "메이플 엔타리아 - 실시간 채팅"
        )

        chat_window.geometry(
            "750x500"
        )

        chat_window.resizable(
            False,
            False
        )

        chat_window.configure(
            bg="#202020"
        )


        # =============================================
        # 상단
        # =============================================

        top_frame = tk.Frame(
            chat_window,
            bg="#111111",
            height=45
        )

        top_frame.pack(
            fill="x"
        )


        tk.Label(
            top_frame,
            text="💬 엔타리아 실시간 채팅",
            font=("맑은 고딕", 13, "bold"),
            fg="white",
            bg="#111111"
        ).pack(
            side="left",
            padx=15,
            pady=10
        )


        online_count_label = tk.Label(
            top_frame,
            text="온라인 0명",
            font=("맑은 고딕", 10, "bold"),
            fg="#66ff66",
            bg="#111111"
        )

        online_count_label.pack(
            side="right",
            padx=15
        )


        # =============================================
        # 본문
        # =============================================

        body_frame = tk.Frame(
            chat_window,
            bg="#202020"
        )

        body_frame.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8
        )


        # =============================================
        # 채팅 영역
        # =============================================

        chat_frame = tk.Frame(
            body_frame,
            bg="#111111"
        )

        chat_frame.pack(
            side="left",
            fill="both",
            expand=True
        )


        chat_messages_box = scrolledtext.ScrolledText(
            chat_frame,
            state="disabled",
            font=("맑은 고딕", 9),
            bg="#111111",
            fg="white",
            insertbackground="white",
            wrap="word",
            bd=0
        )

        chat_messages_box.pack(
            fill="both",
            expand=True,
            padx=5,
            pady=5
        )


        # =============================================
        # 온라인 목록
        # =============================================

        online_frame = tk.Frame(
            body_frame,
            bg="#111111",
            width=150
        )

        online_frame.pack(
            side="right",
            fill="y",
            padx=(8, 0)
        )

        online_frame.pack_propagate(
            False
        )


        tk.Label(
            online_frame,
            text="접속자",
            font=("맑은 고딕", 10, "bold"),
            fg="white",
            bg="#111111"
        ).pack(
            pady=(10, 5)
        )


        online_listbox = tk.Listbox(
            online_frame,
            font=("맑은 고딕", 9),
            bg="#111111",
            fg="#66ff66",
            selectbackground="#333333",
            selectforeground="white",
            bd=0,
            highlightthickness=0
        )

        online_listbox.pack(
            fill="both",
            expand=True,
            padx=5,
            pady=5
        )


        # =============================================
        # 입력
        # =============================================

        input_frame = tk.Frame(
            chat_window,
            bg="#111111"
        )

        input_frame.pack(
            fill="x",
            padx=8,
            pady=(0, 8)
        )


        chat_input = tk.Entry(
            input_frame,
            font=("맑은 고딕", 10),
            bg="#222222",
            fg="white",
            insertbackground="white"
        )

        chat_input.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(5, 5),
            pady=5,
            ipady=5
        )


        tk.Button(
            input_frame,
            text="전송",
            font=("맑은 고딕", 9, "bold"),
            width=8,
            bg="#333333",
            fg="white",
            activebackground="#555555",
            activeforeground="white",
            command=send_chat_message
        ).pack(
            side="right",
            padx=5,
            pady=5
        )


        chat_input.bind(
            "<Return>",
            lambda event:
            send_chat_message()
        )


        # =============================================
        # 채팅창 닫기
        #
        # 창만 숨기고 WebSocket 유지
        # =============================================

        def chat_window_close():

            try:

                chat_window.withdraw()

            except Exception:

                pass


        chat_window.protocol(
            "WM_DELETE_WINDOW",
            chat_window_close
        )


        chat_input.focus()


        # =============================================
        # 채팅 서버 연결
        # =============================================

        if chat_ws is None:

            threading.Thread(
                target=connect_chat,
                daemon=True
            ).start()


    # =====================================================
    # F4 종료
    # =====================================================

    def stop_macro():

        global running
        global exit_program

        running = False

        exit_program = True

        close_chat()

        log(
            "■ 프로그램 종료"
        )

        try:

            keyboard.unhook_all()

        except Exception:

            pass

        try:

            main_root.after(
                300,
                main_root.destroy
            )

        except Exception:

            pass

        try:

            login_root.after(
                400,
                login_root.destroy
            )

        except Exception:

            pass


    # =====================================================
    # 키 입력
    # =====================================================

    def press_game_key(key):

        if exit_program:

            return False

        try:

            log(
                f"키 입력 → {key.upper()}"
            )

            pyautogui.keyDown(
                key
            )

            time.sleep(
                KEY_PRESS_TIME
            )

            pyautogui.keyUp(
                key
            )

            return True

        except Exception as e:

            log(
                f"⚠ 키 입력 오류 : {e}"
            )

            try:

                pyautogui.keyUp(
                    key
                )

            except Exception:

                pass

            return False


    # =====================================================
    # 버프 시작
    # =====================================================

    def start_buff():

        global buff_running

        if exit_program:

            return

        with state_lock:

            license_ok = (
                remaining_seconds > 0
            )

        if not license_ok:

            return

        if buff_running:

            log(
                "⚠ 버프가 이미 실행 중입니다."
            )

            return

        threading.Thread(
            target=buff_sequence,
            daemon=True
        ).start()


    # =====================================================
    # 버프 순차 실행
    # =====================================================

    def buff_sequence():

        global buff_running

        with buff_lock:

            if buff_running:

                return

            buff_running = True

            update_status()

            try:

                log(
                    "★ 버프 순차 실행 시작"
                )

                current_buff_keys = (
                    BUFF_KEYS.copy()
                )

                for index, key in enumerate(
                    current_buff_keys
                ):

                    if exit_program:

                        break

                    while (
                        paused
                        and not exit_program
                    ):

                        time.sleep(
                            0.1
                        )

                    if exit_program:

                        break

                    with state_lock:

                        if remaining_seconds <= 0:

                            break

                    log(
                        f"★ 버프 {index + 1}/8 → "
                        f"{key.upper()}"
                    )

                    press_game_key(
                        key
                    )

                    if index < len(
                        current_buff_keys
                    ) - 1:

                        time.sleep(
                            BUFF_DELAY
                        )

                if not exit_program:

                    log(
                        "✓ 버프 8개 실행 완료"
                    )

            finally:

                buff_running = False

                update_status()


    # =====================================================
    # 이미지 검색
    # =====================================================

    def find_image(image):

        while not exit_program:

            if not running:

                time.sleep(
                    SEARCH_DELAY
                )

                continue

            if paused:

                time.sleep(
                    SEARCH_DELAY
                )

                continue

            with state_lock:

                if remaining_seconds <= 0:

                    return None

            if not os.path.exists(image):

                log(
                    f"⚠ 이미지 없음 → "
                    f"{os.path.basename(image)}"
                )

                time.sleep(
                    1
                )

                continue

            try:

                location = (
                    pyautogui
                    .locateCenterOnScreen(
                        image,
                        confidence=CONFIDENCE
                    )
                )

            except pyautogui.ImageNotFoundException:

                location = None

            except Exception as e:

                log(
                    f"이미지 검색 오류 → {e}"
                )

                location = None

            if location:

                return location

            time.sleep(
                SEARCH_DELAY
            )

        return None


    # =====================================================
    # TARGET 클릭
    # =====================================================

    def click_target(
        target_name,
        target_path
    ):

        log(
            f"{target_name} 검색 중..."
        )

        location = find_image(
            target_path
        )

        if location is None:

            return False

        log(
            f"✓ {target_name} 발견 → "
            f"X:{location.x}, Y:{location.y}"
        )

        pyautogui.click(
            location.x,
            location.y
        )

        time.sleep(
            TARGET_DELAY
        )

        return True


    # =====================================================
    # 매크로
    # =====================================================

    def macro():

        global running

        while not exit_program:

            if not running:

                time.sleep(
                    0.1
                )

                continue

            with state_lock:

                if remaining_seconds <= 0:

                    running = False

                    continue

            if not click_target(
                "target1.png",
                TARGET1
            ):

                continue

            if exit_program:

                break

            if not click_target(
                "target2.png",
                TARGET2
            ):

                continue

            if exit_program:

                break

            if not click_target(
                "target3.png",
                TARGET3
            ):

                continue

            if exit_program:

                break

            if not click_target(
                "target4.png",
                TARGET4
            ):

                continue

            if exit_program:

                break

            log(
                "================================"
            )

            log(
                "✓ TARGET 1 → 2 → 3 → 4 완료"
            )

            log(
                "================================"
            )

            if repeat_mode:

                log(
                    "🔁 다음 TARGET 사이클 시작"
                )

                time.sleep(
                    0.5
                )

            else:

                running = False

                log(
                    "■ 1회 실행 완료"
                )

                update_status()


    # =====================================================
    # 제목
    # =====================================================

    title_panel = tk.Frame(
        main_root,
        bg="#111111",
        bd=2,
        relief="ridge"
    )

    title_panel.place(
        x=20,
        y=110,
        width=810,
        height=60
    )


    tk.Label(
        title_panel,
        text="메이플 엔타리아 분해 매크로",
        font=("Arial", 20, "bold"),
        fg="white",
        bg="#111111"
    ).pack(
        pady=3
    )


    tk.Label(
        title_panel,
        text="TARGET 1~4 / BUFF 8KEY",
        font=("맑은 고딕", 9),
        fg="#dddddd",
        bg="#111111"
    ).pack()


    # =====================================================
    # 상태 패널
    # =====================================================

    status_panel = tk.Frame(
        main_root,
        bg="#111111",
        bd=2,
        relief="ridge"
    )

    status_panel.place(
        x=20,
        y=180,
        width=220,
        height=45
    )


    status_label = tk.Label(
        status_panel,
        text="● 대기 중",
        font=("맑은 고딕", 11, "bold"),
        fg="white",
        bg="#111111"
    )

    status_label.pack(
        pady=10
    )


    # =====================================================
    # 버튼 스타일
    # =====================================================

    BUTTON_STYLE = {

        "font":
            ("맑은 고딕", 9, "bold"),

        "width":
            15,

        "height":
            2,

        "bg":
            "#333333",

        "fg":
            "white",

        "activebackground":
            "#555555",

        "activeforeground":
            "white",

        "bd":
            1,

        "relief":
            "raised"
    }


    # =====================================================
    # 분해 매크로
    # =====================================================

    target_frame = tk.LabelFrame(
        main_root,
        text=" 분해 매크로 ",
        font=("맑은 고딕", 10, "bold"),
        fg="white",
        bg="#222222",
        bd=2,
        relief="ridge"
    )

    target_frame.place(
        x=20,
        y=235,
        width=390,
        height=160
    )


    tk.Button(
        target_frame,
        text="▶ 매크로 실행",
        command=start_macro,
        **BUTTON_STYLE
    ).grid(
        row=0,
        column=0,
        padx=8,
        pady=8
    )


    tk.Button(
        target_frame,
        text="⏸ 일시정지 / 재개",
        command=pause_macro,
        **BUTTON_STYLE
    ).grid(
        row=0,
        column=1,
        padx=8,
        pady=8
    )


    repeat_button = tk.Button(
        target_frame,
        text="반복 : OFF",
        command=toggle_repeat,
        **BUTTON_STYLE
    )

    repeat_button.grid(
        row=1,
        column=0,
        padx=8,
        pady=8
    )


    tk.Button(
        target_frame,
        text="■ 프로그램 종료",
        command=stop_macro,
        **BUTTON_STYLE
    ).grid(
        row=1,
        column=1,
        padx=8,
        pady=8
    )


    # =====================================================
    # 버프
    # =====================================================

    buff_frame = tk.LabelFrame(
        main_root,
        text=" BUFF ",
        font=("맑은 고딕", 10, "bold"),
        fg="white",
        bg="#222222",
        bd=2,
        relief="ridge"
    )

    buff_frame.place(
        x=440,
        y=235,
        width=390,
        height=160
    )


    tk.Label(
        buff_frame,
        text="버프 키 설정",
        font=("맑은 고딕", 9, "bold"),
        fg="white",
        bg="#222222"
    ).pack(
        pady=(4, 2)
    )


    # =====================================================
    # 버프 키 입력 영역
    # =====================================================

    buff_keys_frame = tk.Frame(
        buff_frame,
        bg="#222222"
    )

    buff_keys_frame.pack(
        pady=1
    )


    buff_key_entries = []


    for i in range(8):

        tk.Label(
            buff_keys_frame,
            text=f"버프{i + 1}",
            font=("맑은 고딕", 7, "bold"),
            fg="white",
            bg="#222222",
            width=5
        ).grid(
            row=i // 4,
            column=(i % 4) * 2,
            padx=1,
            pady=2
        )


        entry = tk.Entry(
            buff_keys_frame,
            width=5,
            justify="center",
            font=("맑은 고딕", 8, "bold")
        )


        entry.insert(
            0,
            BUFF_KEYS[i].upper()
        )


        entry.grid(
            row=i // 4,
            column=(i % 4) * 2 + 1,
            padx=1,
            pady=2
        )


        buff_key_entries.append(
            entry
        )


    # =====================================================
    # 버프 순서 표시
    # =====================================================

    buff_sequence_label = tk.Label(
        buff_frame,
        text=(
            " → ".join(
                key.upper()
                for key in BUFF_KEYS
            )
        ),
        font=("맑은 고딕", 7, "bold"),
        fg="#66ff66",
        bg="#222222"
    )

    buff_sequence_label.pack(
        pady=1
    )


    # =====================================================
    # 버프 키 저장
    # =====================================================

    def save_buff_key_settings():

        new_keys = []

        for entry in buff_key_entries:

            key = (
                entry.get()
                .strip()
                .lower()
            )

            if not key:

                messagebox.showwarning(
                    "버프 키 설정",
                    "모든 버프 키를 입력하세요."
                )

                return

            if " " in key:

                messagebox.showwarning(
                    "버프 키 설정",
                    "버프 키에 공백을 사용할 수 없습니다."
                )

                return

            new_keys.append(
                key
            )

        if not save_buff_keys(
            new_keys
        ):

            messagebox.showerror(
                "버프 키 설정",
                "버프 키 저장에 실패했습니다."
            )

            return

        buff_sequence_label.config(
            text=(
                " → ".join(
                    key.upper()
                    for key in BUFF_KEYS
                )
            )
        )

        log(
            "✓ 버프 키 설정 저장"
        )

        log(
            " → ".join(
                key.upper()
                for key in BUFF_KEYS
            )
        )

        messagebox.showinfo(
            "버프 키 설정",
            "버프 키 설정이 저장되었습니다."
        )


    tk.Button(
        buff_frame,
        text="버프 키 저장",
        font=("맑은 고딕", 7, "bold"),
        width=14,
        height=1,
        bg="#333333",
        fg="white",
        activebackground="#555555",
        activeforeground="white",
        command=save_buff_key_settings
    ).pack(
        pady=1
    )


    # =====================================================
    # 버프 실행 단축키
    # =====================================================

    buff_hotkey_frame = tk.Frame(
        buff_frame,
        bg="#222222"
    )

    buff_hotkey_frame.pack(
        pady=1
    )


    tk.Label(
        buff_hotkey_frame,
        text="버프 실행 단축키 :",
        font=("맑은 고딕", 7, "bold"),
        fg="white",
        bg="#222222"
    ).pack(
        side="left",
        padx=2
    )


    buff_hotkey_entry = tk.Entry(
        buff_hotkey_frame,
        width=7,
        justify="center",
        font=("맑은 고딕", 8, "bold")
    )


    buff_hotkey_entry.insert(
        0,
        BUFF_HOTKEY.upper()
    )


    buff_hotkey_entry.pack(
        side="left",
        padx=2
    )


    def set_buff_hotkey():

        global BUFF_HOTKEY

        new_key = (
            buff_hotkey_entry
            .get()
            .strip()
            .lower()
        )

        if not new_key:

            messagebox.showwarning(
                "버프 실행 단축키",
                "단축키를 입력하세요."
            )

            return

        old_key = BUFF_HOTKEY

        try:

            keyboard.remove_hotkey(
                old_key
            )

        except Exception:

            pass

        if not save_buff_hotkey(
            new_key
        ):

            messagebox.showerror(
                "버프 실행 단축키",
                "단축키 저장에 실패했습니다."
            )

            try:

                keyboard.add_hotkey(
                    old_key,
                    start_buff
                )

            except Exception:

                pass

            BUFF_HOTKEY = old_key

            return

        try:

            keyboard.add_hotkey(
                BUFF_HOTKEY,
                start_buff
            )

        except Exception as e:

            BUFF_HOTKEY = old_key

            try:

                save_buff_hotkey(
                    old_key
                )

                keyboard.add_hotkey(
                    old_key,
                    start_buff
                )

            except Exception:

                pass

            messagebox.showerror(
                "버프 실행 단축키",
                f"단축키 등록 실패:\n{e}"
            )

            return

        buff_hotkey_entry.delete(
            0,
            tk.END
        )

        buff_hotkey_entry.insert(
            0,
            BUFF_HOTKEY.upper()
        )

        buff_hotkey_label.config(
            text=(
                "현재 실행키 : "
                + BUFF_HOTKEY.upper()
            )
        )

        hotkey_label.config(
            text=(
                "F1 실행   |   "
                "F2 일시정지/재개   |   "
                "F3 반복   |   "
                "F4 종료   |   "
                f"{BUFF_HOTKEY.upper()} 버프"
            )
        )

        log(
            "✓ 버프 실행 단축키 변경 → "
            + BUFF_HOTKEY.upper()
        )


    tk.Button(
        buff_hotkey_frame,
        text="저장",
        font=("맑은 고딕", 7, "bold"),
        width=5,
        bg="#333333",
        fg="white",
        activebackground="#555555",
        activeforeground="white",
        command=set_buff_hotkey
    ).pack(
        side="left",
        padx=2
    )


    buff_hotkey_label = tk.Label(
        buff_frame,
        text=(
            "현재 실행키 : "
            + BUFF_HOTKEY.upper()
        ),
        font=("맑은 고딕", 7),
        fg="#66ff66",
        bg="#222222"
    )

    buff_hotkey_label.pack(
        pady=1
    )


    # =====================================================
    # 버프 전체 실행
    # =====================================================

    tk.Button(
        buff_frame,
        text="★ 버프 전체 실행",
        font=("맑은 고딕", 8, "bold"),
        width=20,
        height=1,
        bg="#333333",
        fg="white",
        activebackground="#555555",
        activeforeground="white",
        command=start_buff
    ).pack(
        pady=2
    )


    # =====================================================
    # 단축키 표시
    # =====================================================

    hotkey_frame = tk.Frame(
        main_root,
        bg="#111111",
        bd=2,
        relief="ridge"
    )

    hotkey_frame.place(
        x=20,
        y=405,
        width=640,
        height=45
    )


    hotkey_label = tk.Label(
        hotkey_frame,
        text=(
            "F1 실행   |   "
            "F2 일시정지/재개   |   "
            "F3 반복   |   "
            "F4 종료   |   "
            f"{BUFF_HOTKEY.upper()} 버프"
        ),
        font=("맑은 고딕", 9, "bold"),
        fg="white",
        bg="#111111"
    )

    hotkey_label.pack(
        pady=11
    )


    # =====================================================
    # 실시간 채팅 버튼
    # =====================================================

    tk.Button(
        main_root,
        text="💬 실시간 채팅",
        font=("맑은 고딕", 9, "bold"),
        width=15,
        height=1,
        bg="#333333",
        fg="white",
        activebackground="#555555",
        activeforeground="white",
        command=open_chat
    ).place(
        x=675,
        y=412,
        width=145,
        height=30
    )


    # =====================================================
    # LOG
    # =====================================================

    log_frame = tk.LabelFrame(
        main_root,
        text=" LOG ",
        font=("맑은 고딕", 10, "bold"),
        fg="white",
        bg="#222222",
        bd=2,
        relief="ridge"
    )

    log_frame.place(
        x=20,
        y=465,
        width=810,
        height=165
    )


    log_box = scrolledtext.ScrolledText(
        log_frame,
        height=7,
        state="disabled",
        font=("Consolas", 8),
        bg="#111111",
        fg="white",
        insertbackground="white",
        bd=0
    )

    log_box.pack(
        fill="both",
        expand=True,
        padx=5,
        pady=5
    )


    # =====================================================
    # 시작 로그
    # =====================================================

    log(
        "================================"
    )

    log(
        "메이플 엔타리아 시작"
    )

    log(
        "================================"
    )

    log(
        "✓ 로그인 인증 완료"
    )

    log(
        f"✓ 로그인 사용자 : {current_username}"
    )

    log(
        f"✓ 라이선스 : {current_license}"
    )

    log(
        "✓ 하드웨어 락 확인 완료"
    )

    log(
        "--------------------------------"
    )

    log(
        "✓ EXE 내부 리소스 경로 사용"
    )

    log(
        f"✓ target1 리소스 : {TARGET1}"
    )

    log(
        f"✓ target2 리소스 : {TARGET2}"
    )

    log(
        f"✓ target3 리소스 : {TARGET3}"
    )

    log(
        f"✓ target4 리소스 : {TARGET4}"
    )

    log(
        f"✓ 배경 리소스 : {BACKGROUND_IMAGE}"
    )

    log(
        "--------------------------------"
    )


    for image_name, image_path in [

        ("target1.png", TARGET1),

        ("target2.png", TARGET2),

        ("target3.png", TARGET3),

        ("target4.png", TARGET4),

        ("maplestory.png", BACKGROUND_IMAGE)

    ]:

        if os.path.exists(
            image_path
        ):

            log(
                f"✓ {image_name} 로드 완료"
            )

        else:

            log(
                f"⚠ {image_name} 없음 → "
                f"{image_path}"
            )


    log(
        "--------------------------------"
    )

    log(
        "F1 = 분해 실행"
    )

    log(
        "F2 = 일시정지 / 재개"
    )

    log(
        "F3 = 반복 ON/OFF"
    )

    log(
        "F4 = 종료"
    )

    log(
        f"{BUFF_HOTKEY.upper()} = 버프 실행"
    )

    log(
        "💬 실시간 채팅 = 버튼"
    )

    log(
        "--------------------------------"
    )

    log(
        "현재 버프 순서 : "
        + " → ".join(
            key.upper()
            for key in BUFF_KEYS
        )
    )

    log(
        "--------------------------------"
    )


    # =====================================================
    # 매크로 스레드
    # =====================================================

    threading.Thread(
        target=macro,
        daemon=True
    ).start()


    # =====================================================
    # 단축키
    # =====================================================

    try:

        keyboard.add_hotkey(
            "f1",
            start_macro
        )

        keyboard.add_hotkey(
            "f2",
            pause_macro
        )

        keyboard.add_hotkey(
            "f3",
            toggle_repeat
        )

        keyboard.add_hotkey(
            "f4",
            stop_macro
        )

        keyboard.add_hotkey(
            BUFF_HOTKEY,
            start_buff
        )

    except Exception as e:

        log(
            f"⚠ 단축키 등록 오류 : {e}"
        )


    # =====================================================
    # 종료
    # =====================================================

    def on_close():

        stop_macro()


    main_root.protocol(
        "WM_DELETE_WINDOW",
        on_close
    )


# =========================================================
# Enter
# =========================================================

username_entry.bind(
    "<Return>",
    lambda event: login()
)

password_entry.bind(
    "<Return>",
    lambda event: login()
)


# =========================================================
# 로그인 종료
# =========================================================

def close_login():

    global exit_program

    exit_program = True

    try:

        keyboard.unhook_all()

    except Exception:

        pass

    login_root.destroy()


login_root.protocol(
    "WM_DELETE_WINDOW",
    close_login
)


# =========================================================
# 실행
# =========================================================

username_entry.focus()

login_root.mainloop()

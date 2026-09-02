import os
import json
import secrets
import hashlib
import asyncio

from datetime import datetime, timezone, timedelta

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect
)

from fastapi.responses import FileResponse

from pydantic import BaseModel

import uvicorn


# =========================================================
# 기본 설정
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DATA_FILE = os.path.join(
    BASE_DIR,
    "licenses.json"
)

HOST = "0.0.0.0"
PORT = 8000


# =========================================================
# 업데이트 파일
# =========================================================

UPDATE_EXE_FILE = os.path.join(
    BASE_DIR,
    "Entaria.exe"
)

UPDATE_VERSION_FILE = os.path.join(
    BASE_DIR,
    "version.json"
)


# =========================================================
# 관리자 API 키
# =========================================================
# license_manager.py와 반드시 동일하게 설정
# =========================================================

ADMIN_KEY = "CHANGE_THIS_ADMIN_KEY"


# =========================================================
# FastAPI
# =========================================================

app = FastAPI(
    title="Entaria License Server"
)


# =========================================================
# 데이터
# =========================================================

def empty_data():

    return {
        "licenses": {},
        "users": {}
    }


def load_data():

    if not os.path.exists(DATA_FILE):

        data = empty_data()

        save_data(data)

        return data

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if "licenses" not in data:
            data["licenses"] = {}

        if "users" not in data:
            data["users"] = {}

        return data

    except Exception:

        return empty_data()


def save_data(data):

    temp_file = DATA_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=4
        )

    os.replace(
        temp_file,
        DATA_FILE
    )


# =========================================================
# 시간
# =========================================================

def now_utc():

    return datetime.now(
        timezone.utc
    )


def iso_now():

    return now_utc().isoformat()


def parse_datetime(value):

    if not value:
        return None

    try:

        dt = datetime.fromisoformat(
            str(value)
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:

        return None


def remaining_seconds(expires_at):

    expire = parse_datetime(
        expires_at
    )

    if expire is None:
        return 0

    seconds = int(
        (
            expire - now_utc()
        ).total_seconds()
    )

    return max(
        0,
        seconds
    )


# =========================================================
# 비밀번호
# =========================================================

def hash_password(password):

    salt = secrets.token_hex(16)

    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200000
    ).hex()

    return salt + ":" + hashed


def check_password(password, stored):

    try:

        salt, saved_hash = stored.split(
            ":",
            1
        )

        new_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            200000
        ).hex()

        return secrets.compare_digest(
            new_hash,
            saved_hash
        )

    except Exception:

        return False


# =========================================================
# 라이선스 코드
# =========================================================

def generate_license():

    while True:

        code = (
            secrets.token_hex(3).upper()
            + "-"
            + secrets.token_hex(3).upper()
            + "-"
            + secrets.token_hex(3).upper()
        )

        data = load_data()

        if code not in data["licenses"]:

            return code


# =========================================================
# IP
# =========================================================

def get_client_ip(request):

    forwarded = request.headers.get(
        "x-forwarded-for"
    )

    if forwarded:

        return forwarded.split(
            ","
        )[0].strip()

    real_ip = request.headers.get(
        "x-real-ip"
    )

    if real_ip:
        return real_ip

    if request.client:
        return request.client.host

    return "unknown"


# =========================================================
# 모델
# =========================================================

class RegisterRequest(BaseModel):

    license: str
    username: str
    password: str
    hardware_id: str


class LoginRequest(BaseModel):

    username: str
    password: str
    hardware_id: str


class VerifyRequest(BaseModel):

    license: str
    hardware_id: str | None = None


class HeartbeatRequest(BaseModel):

    license: str
    hardware_id: str


class CreateLicenseRequest(BaseModel):

    days: int


class UnlockRequest(BaseModel):

    license: str


class ExtendLicenseRequest(BaseModel):

    license: str
    days: int


class DeleteLicenseRequest(BaseModel):

    license: str


# =========================================================
# 라이선스 검증
# =========================================================

def validate_license(
    license_data,
    hardware_id=None
):

    if license_data.get(
        "disabled",
        False
    ):

        return (
            False,
            "비활성화된 라이선스입니다."
        )

    expires_at = license_data.get(
        "expires_at",
        ""
    )

    seconds = remaining_seconds(
        expires_at
    )

    if seconds <= 0:

        return (
            False,
            "라이선스가 만료되었습니다."
        )

    locked_hardware = license_data.get(
        "hardware_id",
        ""
    )

    if locked_hardware:

        if hardware_id != locked_hardware:

            return (
                False,
                "다른 PC에 하드웨어 락이 설정되어 있습니다."
            )

    return True, ""


# =========================================================
# 서버 상태
# =========================================================

@app.get("/")
def root():

    return {
        "server": "Entaria License Server",
        "status": "online",
        "time": iso_now()
    }


# =========================================================
# 회원가입
# =========================================================

@app.post("/register")
def register(
    req: RegisterRequest,
    request: Request
):

    username = req.username.strip()

    license_code = req.license.strip().upper()

    if len(username) < 3:

        raise HTTPException(
            status_code=400,
            detail="아이디는 3자 이상이어야 합니다."
        )

    if len(req.password) < 4:

        raise HTTPException(
            status_code=400,
            detail="비밀번호는 4자 이상이어야 합니다."
        )

    if not req.hardware_id:

        raise HTTPException(
            status_code=400,
            detail="하드웨어 정보를 확인할 수 없습니다."
        )

    data = load_data()

    if username in data["users"]:

        raise HTTPException(
            status_code=400,
            detail="이미 존재하는 아이디입니다."
        )

    license_data = data[
        "licenses"
    ].get(
        license_code
    )

    if not license_data:

        raise HTTPException(
            status_code=400,
            detail="유효하지 않은 발급코드입니다."
        )

    if license_data.get(
        "disabled",
        False
    ):

        raise HTTPException(
            status_code=400,
            detail="비활성화된 발급코드입니다."
        )

    if license_data.get(
        "username"
    ):

        raise HTTPException(
            status_code=400,
            detail="이미 사용 중인 발급코드입니다."
        )

    if remaining_seconds(
        license_data.get(
            "expires_at",
            ""
        )
    ) <= 0:

        raise HTTPException(
            status_code=400,
            detail="만료된 발급코드입니다."
        )

    ip = get_client_ip(request)

    connection = iso_now()

    data["users"][username] = {

        "password_hash":
            hash_password(
                req.password
            ),

        "license":
            license_code,

        "hardware_id":
            req.hardware_id,

        "created_at":
            connection,

        "last_ip":
            ip,

        "last_connection":
            connection
    }

    license_data["username"] = username

    license_data["hardware_id"] = req.hardware_id

    license_data["last_ip"] = ip

    license_data["last_connection"] = connection

    save_data(data)

    seconds = remaining_seconds(
        license_data["expires_at"]
    )

    return {

        "valid": True,

        "message":
            "회원가입이 완료되었습니다.",

        "license":
            license_code,

        "expires_at":
            license_data["expires_at"],

        "remaining_seconds":
            seconds
    }


# =========================================================
# 로그인
# =========================================================

@app.post("/login")
def login(
    req: LoginRequest,
    request: Request
):

    username = req.username.strip()

    data = load_data()

    user = data[
        "users"
    ].get(username)

    if not user:

        raise HTTPException(
            status_code=401,
            detail="아이디 또는 비밀번호가 올바르지 않습니다."
        )

    if not check_password(
        req.password,
        user.get(
            "password_hash",
            ""
        )
    ):

        raise HTTPException(
            status_code=401,
            detail="아이디 또는 비밀번호가 올바르지 않습니다."
        )

    license_code = user.get(
        "license",
        ""
    )

    license_data = data[
        "licenses"
    ].get(
        license_code
    )

    if not license_data:

        raise HTTPException(
            status_code=401,
            detail="연결된 라이선스를 찾을 수 없습니다."
        )

    valid, message = validate_license(
        license_data,
        req.hardware_id
    )

    if not valid:

        raise HTTPException(
            status_code=403,
            detail=message
        )

    if not license_data.get(
        "hardware_id"
    ):

        license_data[
            "hardware_id"
        ] = req.hardware_id

        user[
            "hardware_id"
        ] = req.hardware_id

    ip = get_client_ip(request)

    connection = iso_now()

    license_data[
        "last_ip"
    ] = ip

    license_data[
        "last_connection"
    ] = connection

    user[
        "last_ip"
    ] = ip

    user[
        "last_connection"
    ] = connection

    save_data(data)

    seconds = remaining_seconds(
        license_data["expires_at"]
    )

    return {

        "valid": True,

        "message":
            "로그인 성공",

        "license":
            license_code,

        "expires_at":
            license_data["expires_at"],

        "remaining_seconds":
            seconds,

        "hardware_locked":
            bool(
                license_data.get(
                    "hardware_id"
                )
            )
    }


# =========================================================
# Verify
# =========================================================

@app.post("/verify")
def verify(
    req: VerifyRequest,
    request: Request
):

    code = req.license.strip().upper()

    data = load_data()

    license_data = data[
        "licenses"
    ].get(code)

    if not license_data:

        return {
            "valid": False,
            "message": "라이선스가 존재하지 않습니다."
        }

    valid, message = validate_license(
        license_data,
        req.hardware_id
    )

    if not valid:

        return {
            "valid": False,
            "message": message
        }

    ip = get_client_ip(request)

    connection = iso_now()

    license_data[
        "last_ip"
    ] = ip

    license_data[
        "last_connection"
    ] = connection

    username = license_data.get(
        "username"
    )

    if username:

        user = data[
            "users"
        ].get(username)

        if user:

            user[
                "last_ip"
            ] = ip

            user[
                "last_connection"
            ] = connection

    save_data(data)

    seconds = remaining_seconds(
        license_data["expires_at"]
    )

    return {

        "valid": True,

        "license":
            code,

        "expires_at":
            license_data["expires_at"],

        "remaining_seconds":
            seconds
    }


# =========================================================
# Heartbeat
# =========================================================

@app.post("/heartbeat")
def heartbeat(
    req: HeartbeatRequest,
    request: Request
):

    code = req.license.strip().upper()

    data = load_data()

    license_data = data[
        "licenses"
    ].get(code)

    if not license_data:

        return {
            "valid": False,
            "message": "라이선스를 찾을 수 없습니다."
        }

    valid, message = validate_license(
        license_data,
        req.hardware_id
    )

    if not valid:

        return {

            "valid": False,

            "message":
                message,

            "remaining_seconds":
                remaining_seconds(
                    license_data.get(
                        "expires_at",
                        ""
                    )
                )
        }

    ip = get_client_ip(request)

    connection = iso_now()

    license_data[
        "last_ip"
    ] = ip

    license_data[
        "last_connection"
    ] = connection

    username = license_data.get(
        "username"
    )

    if username:

        user = data[
            "users"
        ].get(username)

        if user:

            user[
                "last_ip"
            ] = ip

            user[
                "last_connection"
            ] = connection

    save_data(data)

    seconds = remaining_seconds(
        license_data["expires_at"]
    )

    return {

        "valid":
            seconds > 0,

        "message":
            "OK"
            if seconds > 0
            else "라이선스가 만료되었습니다.",

        "expires_at":
            license_data["expires_at"],

        "remaining_seconds":
            seconds,

        "last_ip":
            ip,

        "last_connection":
            connection
    }


# =========================================================
# 프로그램 자동 업데이트
# =========================================================

@app.get("/update/version.json")
def update_version():

    if not os.path.exists(
        UPDATE_VERSION_FILE
    ):

        raise HTTPException(
            status_code=404,
            detail="version.json을 찾을 수 없습니다."
        )

    return FileResponse(
        UPDATE_VERSION_FILE,
        media_type="application/json",
        filename="version.json"
    )


@app.get("/update/Entaria.exe")
def update_entaria():

    if not os.path.exists(
        UPDATE_EXE_FILE
    ):

        raise HTTPException(
            status_code=404,
            detail="Entaria.exe를 찾을 수 없습니다."
        )

    return FileResponse(
        UPDATE_EXE_FILE,
        media_type="application/vnd.microsoft.portable-executable",
        filename="Entaria.exe"
    )


# =========================================================
# 관리자 인증
# =========================================================

def check_admin(key):

    if not key or key != ADMIN_KEY:

        raise HTTPException(
            status_code=403,
            detail="관리자 인증 실패"
        )


# =========================================================
# 관리자 - 라이선스 생성
# =========================================================

@app.post("/admin/create_license")
def admin_create_license(
    req: CreateLicenseRequest,
    request: Request
):

    check_admin(
        request.headers.get(
            "X-Admin-Key"
        )
    )

    if req.days <= 0:

        raise HTTPException(
            status_code=400,
            detail="기간은 1일 이상이어야 합니다."
        )

    code = generate_license()

    expire = (
        now_utc()
        + timedelta(
            days=req.days
        )
    )

    data = load_data()

    data["licenses"][code] = {

        "username": "",

        "hardware_id": "",

        "created_at":
            iso_now(),

        "expires_at":
            expire.isoformat(),

        "disabled":
            False,

        "last_ip":
            "",

        "last_connection":
            ""
    }

    save_data(data)

    return {

        "success": True,

        "license":
            code,

        "expires_at":
            expire.isoformat(),

        "remaining_seconds":
            remaining_seconds(
                expire.isoformat()
            )
    }


# =========================================================
# 관리자 - 라이선스 목록
# =========================================================

@app.get("/admin/licenses")
def admin_licenses(
    request: Request
):

    check_admin(
        request.headers.get(
            "X-Admin-Key"
        )
    )

    data = load_data()

    result = []

    for code, item in data[
        "licenses"
    ].items():

        result.append({

            "license":
                code,

            "username":
                item.get(
                    "username",
                    ""
                ),

            "hardware_id":
                item.get(
                    "hardware_id",
                    ""
                ),

            "remaining_seconds":
                remaining_seconds(
                    item.get(
                        "expires_at",
                        ""
                    )
                ),

            "disabled":
                item.get(
                    "disabled",
                    False
                ),

            "last_ip":
                item.get(
                    "last_ip",
                    ""
                ),

            "last_connection":
                item.get(
                    "last_connection",
                    ""
                )
        })

    return {
        "licenses": result
    }


# =========================================================
# 관리자 - 하드웨어 락 해제
# =========================================================

@app.post("/admin/unlock")
def admin_unlock(
    req: UnlockRequest,
    request: Request
):

    check_admin(
        request.headers.get(
            "X-Admin-Key"
        )
    )

    code = req.license.strip().upper()

    data = load_data()

    license_data = data[
        "licenses"
    ].get(code)

    if not license_data:

        raise HTTPException(
            status_code=404,
            detail="라이선스를 찾을 수 없습니다."
        )

    old_hardware = license_data.get(
        "hardware_id",
        ""
    )

    license_data[
        "hardware_id"
    ] = ""

    username = license_data.get(
        "username",
        ""
    )

    if username:

        user = data[
            "users"
        ].get(username)

        if user:

            user[
                "hardware_id"
            ] = ""

    save_data(data)

    return {

        "success": True,

        "message":
            "하드웨어 락이 해제되었습니다.",

        "old_hardware_id":
            old_hardware
    }


# =========================================================
# 관리자 - 라이선스 비활성화
# =========================================================

@app.post("/admin/disable")
def admin_disable(
    req: UnlockRequest,
    request: Request
):

    check_admin(
        request.headers.get(
            "X-Admin-Key"
        )
    )

    code = req.license.strip().upper()

    data = load_data()

    license_data = data[
        "licenses"
    ].get(code)

    if not license_data:

        raise HTTPException(
            status_code=404,
            detail="라이선스를 찾을 수 없습니다."
        )

    license_data[
        "disabled"
    ] = True

    save_data(data)

    return {

        "success": True,

        "message":
            "라이선스가 비활성화되었습니다."
    }


# =========================================================
# 관리자 - 라이선스 삭제
# =========================================================

@app.post("/admin/delete")
def admin_delete_license(
    req: DeleteLicenseRequest,
    request: Request
):

    check_admin(
        request.headers.get(
            "X-Admin-Key"
        )
    )

    code = req.license.strip().upper()

    data = load_data()

    license_data = data[
        "licenses"
    ].get(code)

    if not license_data:

        raise HTTPException(
            status_code=404,
            detail="라이선스를 찾을 수 없습니다."
        )

    username = license_data.get(
        "username",
        ""
    )

    del data["licenses"][code]

    if username:

        user = data[
            "users"
        ].get(username)

        if user:

            user_license = user.get(
                "license",
                ""
            ).strip().upper()

            if user_license == code:

                del data["users"][username]

    save_data(data)

    return {

        "success": True,

        "message":
            "라이선스가 삭제되었습니다.",

        "license":
            code
    }


# =========================================================
# 관리자 - 라이선스 기간 연장
# =========================================================

@app.post("/admin/extend")
def admin_extend_license(
    req: ExtendLicenseRequest,
    request: Request
):

    check_admin(
        request.headers.get(
            "X-Admin-Key"
        )
    )

    if req.days <= 0:

        raise HTTPException(
            status_code=400,
            detail="연장 기간은 1일 이상이어야 합니다."
        )

    code = req.license.strip().upper()

    data = load_data()

    license_data = data[
        "licenses"
    ].get(code)

    if not license_data:

        raise HTTPException(
            status_code=404,
            detail="라이선스를 찾을 수 없습니다."
        )

    current_expire = parse_datetime(
        license_data.get(
            "expires_at",
            ""
        )
    )

    current_time = now_utc()

    if current_expire is None:

        current_expire = current_time

    if current_expire < current_time:

        current_expire = current_time

    new_expire = (
        current_expire
        + timedelta(
            days=req.days
        )
    )

    license_data[
        "expires_at"
    ] = new_expire.isoformat()

    license_data[
        "disabled"
    ] = False

    save_data(data)

    return {

        "success": True,

        "license":
            code,

        "expires_at":
            new_expire.isoformat(),

        "remaining_seconds":
            remaining_seconds(
                new_expire.isoformat()
            )
    }


# =========================================================
# 실시간 채팅
# =========================================================

chat_connections = {}

chat_messages = []

chat_lock = asyncio.Lock()

MAX_CHAT_MESSAGES = 100


# =========================================================
# 채팅 전체 전송
# =========================================================

async def broadcast_chat(message):

    disconnected = []

    async with chat_lock:

        connections = list(
            chat_connections.items()
        )

        for username, websocket in connections:

            try:

                await websocket.send_json(
                    message
                )

            except Exception:

                disconnected.append(
                    username
                )

        for username in disconnected:

            chat_connections.pop(
                username,
                None
            )


# =========================================================
# 온라인 사용자 목록
# =========================================================

async def get_online_users():

    async with chat_lock:

        return list(
            chat_connections.keys()
        )


# =========================================================
# 실시간 WebSocket 채팅
# =========================================================

@app.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket
):

    username = websocket.query_params.get(
        "username",
        ""
    ).strip()

    license_code = websocket.query_params.get(
        "license",
        ""
    ).strip().upper()

    hardware_id = websocket.query_params.get(
        "hardware_id",
        ""
    ).strip()


    # -----------------------------------------------------
    # 기본 인증값 확인
    # -----------------------------------------------------

    if (
        not username
        or not license_code
        or not hardware_id
    ):

        await websocket.close(
            code=1008
        )

        return


    # -----------------------------------------------------
    # 사용자 확인
    # -----------------------------------------------------

    data = load_data()

    user = data[
        "users"
    ].get(
        username
    )

    if not user:

        await websocket.close(
            code=1008
        )

        return


    # -----------------------------------------------------
    # 사용자 라이선스 확인
    # -----------------------------------------------------

    user_license = user.get(
        "license",
        ""
    ).strip().upper()

    if user_license != license_code:

        await websocket.close(
            code=1008
        )

        return


    # -----------------------------------------------------
    # 라이선스 데이터 확인
    # -----------------------------------------------------

    license_data = data[
        "licenses"
    ].get(
        license_code
    )

    if not license_data:

        await websocket.close(
            code=1008
        )

        return


    # -----------------------------------------------------
    # 라이선스 유효성 검사
    # -----------------------------------------------------

    valid, message = validate_license(
        license_data,
        hardware_id
    )

    if not valid:

        await websocket.close(
            code=1008
        )

        return


    # -----------------------------------------------------
    # WebSocket 연결 승인
    # -----------------------------------------------------

    await websocket.accept()


    # -----------------------------------------------------
    # 기존 연결 처리
    # -----------------------------------------------------

    async with chat_lock:

        old_connection = chat_connections.get(
            username
        )

        if old_connection:

            try:

                await old_connection.close()

            except Exception:

                pass


        chat_connections[
            username
        ] = websocket


        history = chat_messages.copy()


    # -----------------------------------------------------
    # 기존 채팅 기록 전송
    # -----------------------------------------------------

    for item in history:

        try:

            await websocket.send_json(
                item
            )

        except Exception:

            return


    # -----------------------------------------------------
    # 온라인 사용자에게 입장 알림
    # -----------------------------------------------------

    await broadcast_chat({

        "type":
            "system",

        "username":
            "SYSTEM",

        "message":
            f"{username}님이 입장했습니다.",

        "time":
            iso_now()

    })


    # -----------------------------------------------------
    # 온라인 사용자 목록 전송
    # -----------------------------------------------------

    online_users = await get_online_users()

    await broadcast_chat({

        "type":
            "online",

        "users":
            online_users,

        "count":
            len(online_users)

    })


    # -----------------------------------------------------
    # 메시지 수신
    # -----------------------------------------------------

    try:

        while True:

            data = await websocket.receive_json()

            message = str(
                data.get(
                    "message",
                    ""
                )
            ).strip()

            if not message:

                continue

            message = message[:300]

            chat_message = {

                "type":
                    "message",

                "username":
                    username,

                "message":
                    message,

                "time":
                    iso_now()

            }

            async with chat_lock:

                chat_messages.append(
                    chat_message
                )

                if len(
                    chat_messages
                ) > MAX_CHAT_MESSAGES:

                    del chat_messages[
                        :-MAX_CHAT_MESSAGES
                    ]

            await broadcast_chat(
                chat_message
            )


    # -----------------------------------------------------
    # 연결 종료
    # -----------------------------------------------------

    except WebSocketDisconnect:

        pass


    except Exception:

        pass


    finally:

        async with chat_lock:

            if chat_connections.get(
                username
            ) is websocket:

                chat_connections.pop(
                    username,
                    None
                )


        await broadcast_chat({

            "type":
                "system",

            "username":
                "SYSTEM",

            "message":
                f"{username}님이 퇴장했습니다.",

            "time":
                iso_now()

        })


        online_users = await get_online_users()

        await broadcast_chat({

            "type":
                "online",

            "users":
                online_users,

            "count":
                len(online_users)

        })


# =========================================================
# 서버 실행
# =========================================================

if __name__ == "__main__":

    print(
        "=========================================="
    )

    print(
        " Entaria License Server"
    )

    print(
        "=========================================="
    )

    print(
        f"http://0.0.0.0:{PORT}"
    )

    print(
        "WebSocket Chat: /ws/chat"
    )

    print(
        "Update API: /update/version.json"
    )

    print(
        "Update API: /update/Entaria.exe"
    )

    uvicorn.run(
        app,
        host=HOST,
        port=PORT
    )

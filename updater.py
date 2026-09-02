import os
import sys
import time
import hashlib
import subprocess
import tempfile
import requests
import re
import ctypes


# =========================================================
# Entaria Updater
# =========================================================

SERVER_URL = "https://api.entaria1004.win"

VERSION_URL = f"{SERVER_URL}/update/version.json"
DOWNLOAD_URL = f"{SERVER_URL}/update/Entaria.exe"

APP_NAME = "Entaria.exe"

UPDATE_TIMEOUT = 30
REPLACE_TIMEOUT = 20


# =========================================================
# 메시지
# =========================================================

def show_message(message, title="Entaria Updater", error=False):
    """
    --windowed 빌드에서도 사용자에게 메시지를 보여준다.
    """
    try:
        flags = 0x10 if error else 0x40

        ctypes.windll.user32.MessageBoxW(
            0,
            str(message),
            title,
            flags
        )

    except Exception:
        pass


# =========================================================
# 프로그램 폴더
# =========================================================

def get_app_dir():
    """
    Updater.exe가 있는 폴더를 Entaria 설치 폴더로 사용한다.

    예:
        C:\\Entaria\\EntariaUpdater.exe
        C:\\Entaria\\Entaria.exe

    Python 실행 시:
        updater.py가 있는 폴더
    """

    if getattr(sys, "frozen", False):
        return os.path.dirname(
            os.path.abspath(sys.executable)
        )

    return os.path.dirname(
        os.path.abspath(__file__)
    )


def get_app_path():
    return os.path.join(
        get_app_dir(),
        APP_NAME
    )


# =========================================================
# 버전 파싱
# =========================================================

def version_key(version):
    """
    1.0.9 < 1.0.10 문제를 방지하기 위한 버전 비교.
    """

    numbers = re.findall(
        r"\d+",
        str(version)
    )

    if not numbers:
        raise ValueError(
            f"잘못된 버전 형식입니다: {version}"
        )

    values = [
        int(x)
        for x in numbers[:8]
    ]

    while len(values) < 8:
        values.append(0)

    return tuple(values)


# =========================================================
# 서버 버전 정보
# =========================================================

def get_version_info():
    """
    서버에서 최신 version.json을 가져온다.
    """

    response = requests.get(
        VERSION_URL,
        params={
            "_": str(
                int(time.time())
            )
        },
        timeout=10,
        headers={
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache"
        }
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError(
            "잘못된 version.json 형식입니다."
        )

    if "version" not in data:
        raise ValueError(
            "version 정보가 없습니다."
        )

    if "sha256" not in data:
        raise ValueError(
            "sha256 정보가 없습니다."
        )

    latest_version = str(
        data["version"]
    ).strip()

    expected_sha256 = str(
        data["sha256"]
    ).strip().lower()

    version_key(
        latest_version
    )

    if not re.fullmatch(
        r"[0-9a-f]{64}",
        expected_sha256
    ):
        raise ValueError(
            "version.json의 SHA-256 형식이 잘못되었습니다."
        )

    return {
        "version": latest_version,
        "sha256": expected_sha256
    }


# =========================================================
# SHA-256
# =========================================================

def calculate_sha256(filepath):
    """
    파일 SHA-256 계산.
    """

    sha256 = hashlib.sha256()

    with open(
        filepath,
        "rb"
    ) as f:

        while True:

            chunk = f.read(
                1024 * 1024
            )

            if not chunk:
                break

            sha256.update(
                chunk
            )

    return sha256.hexdigest().lower()


# =========================================================
# 다운로드
# =========================================================

def download_update(destination):
    """
    최신 Entaria.exe 다운로드.
    """

    with requests.get(
        DOWNLOAD_URL,
        params={
            "_": str(
                int(time.time())
            )
        },
        stream=True,
        timeout=UPDATE_TIMEOUT,
        headers={
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache"
        }
    ) as response:

        response.raise_for_status()

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length:

            try:
                expected_size = int(
                    content_length
                )

                if expected_size <= 0:
                    raise ValueError(
                        "다운로드 파일 크기가 올바르지 않습니다."
                    )

            except ValueError:
                pass

        with open(
            destination,
            "wb"
        ) as f:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if chunk:
                    f.write(chunk)

    if not os.path.exists(
        destination
    ):
        raise FileNotFoundError(
            "Entaria.exe 다운로드 파일이 생성되지 않았습니다."
        )

    if os.path.getsize(
        destination
    ) <= 0:

        raise ValueError(
            "다운로드된 Entaria.exe가 비어 있습니다."
        )


# =========================================================
# 파일 교체 재시도
# =========================================================

def replace_with_retry(
    source,
    destination,
    timeout=REPLACE_TIMEOUT
):
    """
    Windows에서 백신 검사나 기존 프로세스 때문에
    잠시 파일이 잠겨 있는 경우 재시도한다.
    """

    start_time = time.time()

    last_error = None

    while (
        time.time() - start_time
        < timeout
    ):

        try:

            os.replace(
                source,
                destination
            )

            return

        except (
            PermissionError,
            OSError
        ) as e:

            last_error = e

            time.sleep(
                0.5
            )

    if last_error:
        raise last_error

    raise RuntimeError(
        "파일 교체에 실패했습니다."
    )


# =========================================================
# Entaria 종료 대기
# =========================================================

def wait_for_entaria_exit(
    timeout=REPLACE_TIMEOUT
):
    """
    Entaria.exe가 완전히 종료될 때까지 기다린다.

    파일이 아직 Windows에서 사용 중이면
    교체하지 않는다.
    """

    app_path = get_app_path()

    start_time = time.time()

    while (
        time.time() - start_time
        < timeout
    ):

        if not os.path.exists(
            app_path
        ):
            return True

        try:

            # 실제 교체 가능 여부를 확인하기 위해
            # 읽기/쓰기 모드로 열어본다.
            with open(
                app_path,
                "a+b"
            ):
                return True

        except (
            PermissionError,
            OSError
        ):

            time.sleep(
                0.5
            )

    return False


# =========================================================
# EXE 교체
# =========================================================

def replace_exe(new_exe):
    """
    기존 Entaria.exe를 백업한 뒤 새 EXE로 교체한다.

    실패하면 기존 EXE를 복구한다.
    """

    app_dir = get_app_dir()

    app_path = get_app_path()

    backup_path = app_path + ".old"

    os.makedirs(
        app_dir,
        exist_ok=True
    )

    # -----------------------------------------------------
    # 기존 백업 제거
    # -----------------------------------------------------

    if os.path.exists(
        backup_path
    ):

        try:

            os.remove(
                backup_path
            )

        except OSError:
            pass

    moved_old = False

    # -----------------------------------------------------
    # 기존 EXE 백업
    # -----------------------------------------------------

    if os.path.exists(
        app_path
    ):

        start_time = time.time()

        last_error = None

        while (
            time.time() - start_time
            < REPLACE_TIMEOUT
        ):

            try:

                os.replace(
                    app_path,
                    backup_path
                )

                moved_old = True

                break

            except (
                PermissionError,
                OSError
            ) as e:

                last_error = e

                time.sleep(
                    0.5
                )

        if not moved_old:

            if last_error:
                raise last_error

            raise RuntimeError(
                "기존 Entaria.exe를 백업하지 못했습니다."
            )

    # -----------------------------------------------------
    # 새 EXE 설치
    # -----------------------------------------------------

    try:

        replace_with_retry(
            new_exe,
            app_path
        )

    except Exception:

        # 새 파일 설치 실패
        # 기존 EXE 복구

        if moved_old:

            try:

                replace_with_retry(
                    backup_path,
                    app_path
                )

            except Exception:
                pass

        raise

    # -----------------------------------------------------
    # 새 EXE 존재 확인
    # -----------------------------------------------------

    if not os.path.exists(
        app_path
    ):

        # 비상 복구

        if moved_old:

            try:

                replace_with_retry(
                    backup_path,
                    app_path
                )

            except Exception:
                pass

        raise FileNotFoundError(
            "업데이트 후 Entaria.exe를 찾을 수 없습니다."
        )

    # -----------------------------------------------------
    # 백업은 바로 삭제하지 않는다.
    #
    # 새 프로그램 실행 성공 후 삭제한다.
    # -----------------------------------------------------

    return backup_path


# =========================================================
# Entaria 실행
# =========================================================

def start_entaria():
    """
    업데이트 완료 후 Entaria.exe 실행.
    """

    app_dir = get_app_dir()

    app_path = get_app_path()

    if not os.path.exists(
        app_path
    ):

        raise FileNotFoundError(
            f"Entaria.exe를 찾을 수 없습니다.\n\n"
            f"{app_path}"
        )

    creation_flags = (
        getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0
        )
        |
        getattr(
            subprocess,
            "DETACHED_PROCESS",
            0
        )
    )

    process = subprocess.Popen(
        [app_path],
        cwd=app_dir,
        close_fds=True,
        creationflags=creation_flags
    )

    return process


# =========================================================
# 백업 삭제
# =========================================================

def remove_backup(backup_path):
    """
    업데이트 성공 후 기존 EXE 백업 삭제.
    실패해도 업데이트 자체는 성공으로 처리한다.
    """

    if not backup_path:
        return

    if not os.path.exists(
        backup_path
    ):
        return

    try:

        os.remove(
            backup_path
        )

    except OSError:
        pass


# =========================================================
# 임시파일 정리
# =========================================================

def cleanup_file(path):
    if not path:
        return

    try:

        if os.path.exists(
            path
        ):

            os.remove(
                path
            )

    except OSError:
        pass


# =========================================================
# 메인
# =========================================================

def main():

    app_dir = get_app_dir()

    app_path = get_app_path()

    os.makedirs(
        app_dir,
        exist_ok=True
    )

    temp_dir = tempfile.mkdtemp(
        prefix="entaria_update_"
    )

    new_exe = os.path.join(
        temp_dir,
        "Entaria.new.exe"
    )

    backup_path = None

    try:

        # -------------------------------------------------
        # 1. 서버 버전 확인
        # -------------------------------------------------

        version_info = get_version_info()

        latest_version = str(
            version_info["version"]
        )

        expected_sha256 = str(
            version_info["sha256"]
        ).lower()

        # -------------------------------------------------
        # 2. 다운로드
        # -------------------------------------------------

        download_update(
            new_exe
        )

        # -------------------------------------------------
        # 3. SHA-256 검사
        # -------------------------------------------------

        actual_sha256 = calculate_sha256(
            new_exe
        )

        if actual_sha256 != expected_sha256:

            raise ValueError(
                "다운로드된 Entaria.exe의 SHA-256이 "
                "서버 정보와 일치하지 않습니다.\n\n"
                f"서버:\n{expected_sha256}\n\n"
                f"실제:\n{actual_sha256}"
            )

        # -------------------------------------------------
        # 4. Entaria 종료 대기
        # -------------------------------------------------

        if not wait_for_entaria_exit():

            raise RuntimeError(
                "Entaria.exe가 종료되지 않아 "
                "업데이트할 수 없습니다."
            )

        # -------------------------------------------------
        # 5. EXE 교체
        # -------------------------------------------------

        backup_path = replace_exe(
            new_exe
        )

        # -------------------------------------------------
        # 6. 새 EXE 실행
        # -------------------------------------------------

        try:

            start_entaria()

        except Exception:

            # 새 EXE 실행 실패
            # 기존 EXE 복구

            if (
                backup_path
                and os.path.exists(
                    backup_path
                )
            ):

                try:

                    if os.path.exists(
                        app_path
                    ):

                        os.remove(
                            app_path
                        )

                except OSError:
                    pass

                try:

                    os.replace(
                        backup_path,
                        app_path
                    )

                except Exception:
                    pass

            raise

        # -------------------------------------------------
        # 7. 실행 성공
        # -------------------------------------------------

        remove_backup(
            backup_path
        )

        show_message(
            f"Entaria 업데이트가 완료되었습니다.\n\n"
            f"최신 버전: {latest_version}",
            "Entaria 업데이트"
        )

        return 0

    except Exception as e:

        show_message(
            "Entaria 업데이트에 실패했습니다.\n\n"
            f"{e}\n\n"
            "구버전 Entaria는 실행되지 않습니다.",
            "Entaria 업데이트 실패",
            error=True
        )

        return 1

    finally:

        cleanup_file(
            new_exe
        )

        try:

            if os.path.isdir(
                temp_dir
            ):

                os.rmdir(
                    temp_dir
                )

        except OSError:
            pass


# =========================================================
# 실행
# =========================================================

if __name__ == "__main__":
    sys.exit(
        main()
    )

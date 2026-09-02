import os
import sys
import time
import hashlib
import subprocess
import tempfile
import requests


# =========================================================
# Entaria Updater
# =========================================================

SERVER_URL = "https://api.entaria1004.win"

VERSION_URL = f"{SERVER_URL}/update/version.json"
DOWNLOAD_URL = f"{SERVER_URL}/update/Entaria.exe"

APP_NAME = "Entaria.exe"


def get_app_dir():
    """
    Entaria.exe가 설치된 폴더.
    기본 위치:
        C:\\Entaria
    """
    return r"C:\Entaria"


def get_app_path():
    return os.path.join(get_app_dir(), APP_NAME)


def get_version_info():
    """
    서버에서 최신 버전 정보를 가져온다.
    """
    response = requests.get(
        VERSION_URL,
        timeout=10,
        headers={
            "Cache-Control": "no-cache"
        }
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("잘못된 version.json 형식입니다.")

    if "version" not in data:
        raise ValueError("version 정보가 없습니다.")

    if "sha256" not in data:
        raise ValueError("sha256 정보가 없습니다.")

    return data


def calculate_sha256(filepath):
    """
    다운로드한 EXE의 SHA-256을 계산한다.
    """
    sha256 = hashlib.sha256()

    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest().lower()


def download_update(destination):
    """
    최신 Entaria.exe 다운로드.
    """
    with requests.get(
        DOWNLOAD_URL,
        stream=True,
        timeout=30,
        headers={
            "Cache-Control": "no-cache"
        }
    ) as response:

        response.raise_for_status()

        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def replace_exe(new_exe):
    """
    기존 Entaria.exe를 새 파일로 교체한다.
    """
    app_path = get_app_path()

    os.makedirs(get_app_dir(), exist_ok=True)

    backup_path = app_path + ".old"

    # 기존 백업 제거
    if os.path.exists(backup_path):
        try:
            os.remove(backup_path)
        except OSError:
            pass

    # 기존 EXE가 있으면 백업
    if os.path.exists(app_path):
        os.replace(app_path, backup_path)

    try:
        os.replace(new_exe, app_path)

    except Exception:
        # 교체 실패 시 기존 파일 복구
        if os.path.exists(backup_path):
            try:
                os.replace(backup_path, app_path)
            except OSError:
                pass

        raise

    # 교체 성공 후 백업 제거
    if os.path.exists(backup_path):
        try:
            os.remove(backup_path)
        except OSError:
            pass


def start_entaria():
    """
    업데이트 완료 후 Entaria.exe 실행.
    """
    app_path = get_app_path()

    if not os.path.exists(app_path):
        raise FileNotFoundError(
            f"Entaria.exe를 찾을 수 없습니다:\n{app_path}"
        )

    subprocess.Popen(
        [app_path],
        cwd=get_app_dir(),
        close_fds=True
    )


def main():
    print("================================")
    print(" Entaria Updater")
    print("================================")

    app_dir = get_app_dir()

    os.makedirs(app_dir, exist_ok=True)

    temp_dir = tempfile.mkdtemp(prefix="entaria_update_")

    new_exe = os.path.join(
        temp_dir,
        "Entaria.new.exe"
    )

    try:
        print("최신 버전 정보를 확인하는 중...")

        version_info = get_version_info()

        latest_version = str(
            version_info["version"]
        )

        expected_sha256 = str(
            version_info["sha256"]
        ).lower()

        print(f"서버 버전: {latest_version}")

        print("최신 Entaria.exe 다운로드 중...")

        download_update(new_exe)

        print("파일 무결성 검사 중...")

        actual_sha256 = calculate_sha256(new_exe)

        if actual_sha256 != expected_sha256:
            raise ValueError(
                "다운로드된 EXE의 SHA-256이 일치하지 않습니다."
            )

        print("SHA-256 확인 완료.")

        print("Entaria.exe 교체 중...")

        replace_exe(new_exe)

        print("업데이트 완료.")

        print("Entaria.exe 실행 중...")

        start_entaria()

        return 0

    except Exception as e:
        print()
        print("================================")
        print(" 업데이트 실패")
        print("================================")
        print(str(e))
        print()

        # 사용자에게 오류가 너무 빨리 사라지지 않도록 잠시 대기
        time.sleep(5)

        return 1

    finally:
        try:
            if os.path.exists(new_exe):
                os.remove(new_exe)
        except OSError:
            pass

        try:
            os.rmdir(temp_dir)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())

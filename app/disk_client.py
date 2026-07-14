from __future__ import annotations

import logging
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)


class YandexDiskError(RuntimeError):
    pass


class YandexDiskClient:
    API_ROOT = "https://cloud-api.yandex.net/v1/disk"

    def __init__(self, token: str, timeout: int = 60) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"OAuth {token}",
                "Accept": "application/json",
                "User-Agent": "coldex-yandex-meeting-sorter/1.0",
            }
        )
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=5,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "PUT", "POST", "DELETE", "HEAD"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get_disk_info(self) -> dict:
        response = self.session.get(self.API_ROOT, timeout=self.timeout)
        self._raise(response, "Could not access Yandex Disk")
        return response.json()

    def exists(self, path: str) -> bool:
        response = self.session.get(
            f"{self.API_ROOT}/resources",
            params={"path": path, "fields": "type,path,name"},
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return False
        self._raise(response, f"Could not check Yandex Disk path: {path}")
        return True

    def ensure_folder_tree(self, path: str) -> None:
        normalized = "/" + path.strip("/")
        current = ""
        for segment in normalized.strip("/").split("/"):
            if not segment:
                continue
            current += f"/{segment}"
            self.create_folder(current)

    def create_folder(self, path: str) -> None:
        response = self.session.put(
            f"{self.API_ROOT}/resources",
            params={"path": path},
            timeout=self.timeout,
        )
        if response.status_code in (201, 409):
            return
        self._raise(response, f"Could not create Yandex Disk folder: {path}")

    def unique_path(self, desired_path: str) -> str:
        if not self.exists(desired_path):
            return desired_path

        if "." in desired_path.rsplit("/", 1)[-1]:
            stem, extension = desired_path.rsplit(".", 1)
            extension = f".{extension}"
        else:
            stem, extension = desired_path, ""

        index = 2
        while True:
            candidate = f"{stem}_{index}{extension}"
            if not self.exists(candidate):
                return candidate
            index += 1

    def upload_bytes(self, path: str, content: bytes, overwrite: bool = False) -> None:
        link_response = self.session.get(
            f"{self.API_ROOT}/resources/upload",
            params={"path": path, "overwrite": str(overwrite).lower()},
            timeout=self.timeout,
        )
        self._raise(link_response, f"Could not obtain upload URL for: {path}")
        payload = link_response.json()
        upload_url = payload.get("href")
        method = payload.get("method", "PUT")
        if not upload_url:
            raise YandexDiskError(f"Yandex Disk did not return upload URL for: {path}")

        upload_response = self.session.request(
            method=method,
            url=upload_url,
            data=content,
            headers={"Content-Type": "text/plain; charset=utf-8"},
            timeout=self.timeout,
        )
        if upload_response.status_code not in (201, 202):
            self._raise(upload_response, f"Could not upload file to: {path}")

    @staticmethod
    def _raise(response: requests.Response, context: str) -> None:
        if response.ok:
            return
        try:
            details = response.json()
        except ValueError:
            details = response.text[:1000]
        raise YandexDiskError(f"{context}. HTTP {response.status_code}: {details}")

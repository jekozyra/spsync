"""A thin Microsoft Graph client for the drive operations spsync needs."""

from __future__ import annotations

import base64
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from .auth import Auth

GRAPH = "https://graph.microsoft.com/v1.0"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REQUEST_TIMEOUT_SECONDS = 120
MAX_ATTEMPTS = 5
MAX_RETRY_WAIT_SECONDS = 30
RETRY_STATUSES = (429, 503, 504)
ERROR_TEXT_CHARS = 200


class GraphError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


def share_id(url: str) -> str:
    enc = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return "u!" + enc


def _error(resp: httpx.Response) -> GraphError:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        err = {}
    return GraphError(resp.status_code, err.get("code", "error"), err.get("message", resp.text[:ERROR_TEXT_CHARS]))


class Graph:
    def __init__(self, auth: Auth | None = None) -> None:
        self.auth = auth or Auth()
        self.http = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        json: dict | None = None,
    ) -> httpx.Response:
        """Send one request. Refresh the token once on 401, and retry throttled requests with backoff."""
        if not url.startswith("http"):
            url = GRAPH + url
        force = False
        for attempt in range(MAX_ATTEMPTS):
            h = {"Authorization": f"Bearer {self.auth.token(force_refresh=force)}"}
            h.update(headers or {})
            resp = self.http.request(method, url, headers=h, content=content, json=json)
            if resp.status_code == 401 and not force:
                force = True
                continue
            if resp.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
                time.sleep(min(float(resp.headers.get("Retry-After", 2**attempt)), MAX_RETRY_WAIT_SECONDS))
                continue
            if resp.status_code >= 400:
                raise _error(resp)
            return resp
        raise GraphError(resp.status_code, "retry", "Gave up after retries")

    def _req(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        json: dict | None = None,
    ) -> dict:
        resp = self._send(method, url, headers=headers, content=content, json=json)
        return resp.json() if resp.content else {}

    # ---- identity ----
    def me(self) -> dict:
        return self._req("GET", "/me?$select=displayName,mail,userPrincipalName")

    def my_drive_id(self) -> str:
        return self._req("GET", "/me/drive")["id"]

    # ---- items ----
    def item(self, drive_id: str, item_id: str) -> dict:
        return self._req("GET", f"/drives/{drive_id}/items/{item_id}")

    def resolve(self, ref: str) -> dict:
        """Resolve a SharePoint/OneDrive URL, sharing link, or driveId:itemId reference."""
        ref = ref.strip()
        if ref == "me":
            return self._req("GET", "/me/drive/root")
        if not ref.startswith("http") and ":" in ref:
            drive_id, item_id = ref.split(":", 1)
            return self.item(drive_id, item_id)
        try:
            return self._req("GET", f"/shares/{share_id(ref)}/driveItem")
        except GraphError as exc:
            found = self._resolve_doc_aspx(ref)
            if found:
                return found
            raise GraphError(
                exc.status,
                exc.code,
                f"Could not resolve that link. In SharePoint use Share > Copy link, or find the doc with `spsync search`. ({exc.message})",
            ) from exc

    def _resolve_doc_aspx(self, url: str) -> dict | None:
        """Word Online URLs (Doc.aspx?sourcedoc={guid}&file=Name.docx) are not sharing links."""
        u = urlparse(url)
        qs = parse_qs(u.query)
        name = (qs.get("file") or [None])[0]
        guid = (qs.get("sourcedoc") or [""])[0].strip("{}").lower()
        if not name:
            return None
        for hit in self.search(f'filename:"{name}"', size=25, docx_only=False):
            if guid and guid in unquote(hit.get("webUrl", "")).lower():
                return self.item(hit["parentReference"]["driveId"], hit["id"])
            if guid and guid == (hit.get("_sharepointIds") or "").lower():
                return self.item(hit["parentReference"]["driveId"], hit["id"])
        hits = [h for h in self.search(f'filename:"{name}"', size=25, docx_only=False) if h.get("name") == name]
        if len(hits) == 1:
            h = hits[0]
            return self.item(h["parentReference"]["driveId"], h["id"])
        return None

    def download(self, drive_id: str, item_id: str) -> bytes:
        return self._send("GET", f"/drives/{drive_id}/items/{item_id}/content").content

    def upload(self, drive_id: str, item_id: str, data: bytes, etag: str | None) -> dict:
        headers = {"Content-Type": DOCX_MIME}
        if etag:
            headers["If-Match"] = etag
        return self._req("PUT", f"/drives/{drive_id}/items/{item_id}/content", content=data, headers=headers)

    def create(self, drive_id: str, parent_id: str, name: str, data: bytes) -> dict:
        headers = {"Content-Type": DOCX_MIME}
        path = f"/drives/{drive_id}/items/{parent_id}:/{quote(name)}:/content?@microsoft.graph.conflictBehavior=fail"
        return self._req("PUT", path, content=data, headers=headers)

    def search(self, query: str, size: int = 25, docx_only: bool = True) -> list[dict]:
        q = f"{query} filetype:docx" if docx_only else query
        body = {"requests": [{"entityTypes": ["driveItem"], "query": {"queryString": q}, "from": 0, "size": size}]}
        data = self._req("POST", "/search/query", json=body)
        hits = []
        for container in data.get("value", []):
            for hc in container.get("hitsContainers", []):
                for hit in hc.get("hits", []) or []:
                    res = hit.get("resource", {})
                    res["_summary"] = hit.get("summary", "")
                    hits.append(res)
        return hits

    def recent(self) -> list[dict]:
        data = self._req("GET", "/me/drive/recent")
        out = []
        for it in data.get("value", []):
            remote = it.get("remoteItem") or it
            if (remote.get("name") or "").lower().endswith(".docx"):
                out.append(remote)
        return out

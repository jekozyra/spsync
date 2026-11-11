"""A thin Microsoft Graph client for the drive operations spsync needs."""

from __future__ import annotations

import base64
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from .auth import Auth

GRAPH = "https://graph.microsoft.com/v1.0"


class GraphError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


def share_id(url: str) -> str:
    enc = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return "u!" + enc


class Graph:
    def __init__(self, auth: Auth | None = None):
        self.auth = auth or Auth()
        self.http = httpx.Client(timeout=120, follow_redirects=True)

    def _req(self, method: str, url: str, *, raw: bool = False, headers: dict | None = None, **kw):
        if not url.startswith("http"):
            url = GRAPH + url
        force = False
        for attempt in range(5):
            h = {"Authorization": f"Bearer {self.auth.token(force_refresh=force)}"}
            h.update(headers or {})
            resp = self.http.request(method, url, headers=h, **kw)
            if resp.status_code == 401 and not force:
                force = True
                continue
            if resp.status_code in (429, 503, 504) and attempt < 4:
                time.sleep(min(float(resp.headers.get("Retry-After", 2 ** attempt)), 30))
                continue
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("error", {})
                except ValueError:
                    err = {}
                raise GraphError(resp.status_code, err.get("code", "error"), err.get("message", resp.text[:200]))
            if raw:
                return resp
            return resp.json() if resp.content else {}
        raise GraphError(resp.status_code, "retry", "Gave up after retries")

    # ---- identity ----
    def me(self) -> dict:
        return self._req("GET", "/me?$select=displayName,mail,userPrincipalName")

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
            raise GraphError(exc.status, exc.code, f"Could not resolve that link. In SharePoint use Share > Copy link, or find the doc with `spsync search`. ({exc.message})") from exc

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
        return self._req("GET", f"/drives/{drive_id}/items/{item_id}/content", raw=True).content

    def upload(self, drive_id: str, item_id: str, data: bytes, etag: str | None) -> dict:
        headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if etag:
            headers["If-Match"] = etag
        return self._req("PUT", f"/drives/{drive_id}/items/{item_id}/content", content=data, headers=headers)

    def create(self, drive_id: str, parent_id: str, name: str, data: bytes) -> dict:
        headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
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

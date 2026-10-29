"""Minimal MyAccount REST client (standard library only).

Base URL and auth follow the official e2ectl transport:
``https://api.e2enetworks.com/myaccount/api/v1`` with
``Authorization: Bearer <auth_token>`` plus ``project_id``/``location`` query
parameters. When an ``api_key`` is also configured it is sent as the legacy
``apikey`` query parameter for compatibility with older API style.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.e2enetworks.com/myaccount/api/v1"
TIMEOUT_S = 30


class E2EError(Exception):
    pass


def _redact(url: str) -> str:
    """Strip credential-bearing query parameters for logs and errors."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, "***" if k.lower() in ("apikey", "api_key") else v)
            for k, v in query]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path,
         urllib.parse.urlencode(kept), parts.fragment))


class Client:
    def __init__(self, auth_token: str, project_id: str, location: str,
                 api_key: str = "", base_url: str = BASE_URL,
                 timeout_s: int = TIMEOUT_S) -> None:
        if not auth_token:
            raise E2EError("E2E auth token is empty; create one in "
                           "MyAccount > API & IAM")
        # project_id is optional: omitted means the default project. (A wrong
        # id fails with a misleading 401 "suspended due to payment".)
        if not location:
            raise E2EError("E2E location is empty")
        self._auth_token = auth_token
        self._project_id = project_id
        self._location = location
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _url(self, path: str,
             extra: dict[str, str] | None = None) -> str:
        query: dict[str, str] = {"location": self._location}
        if self._project_id:
            query["project_id"] = self._project_id
        if self._api_key:
            query["apikey"] = self._api_key
        if extra:
            query.update({k: v for k, v in extra.items() if v})
        return (f"{self._base_url}{path}"
                f"?{urllib.parse.urlencode(query)}")

    def _request(self, method: str, path: str, body: object = None,
                 extra: dict[str, str] | None = None) -> dict:
        url = self._url(path, extra)
        data = None
        headers = {"Accept": "application/json",
                   "Authorization": f"Bearer {self._auth_token}"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req,
                                        timeout=self._timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001 - best effort only
                detail = ""
            raise E2EError(f"{method} {path} failed: HTTP {exc.code} "
                           f"({_redact(url)}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise E2EError(f"{method} {path} failed: {exc.reason} "
                           f"({_redact(url)})") from exc
        if not isinstance(payload, dict) or "data" not in payload:
            raise E2EError(f"{method} {path}: unexpected response shape: "
                           f"{str(payload)[:300]}")
        if payload.get("code") not in (None, 200, 201):
            raise E2EError(f"{method} {path}: API code "
                           f"{payload.get('code')}: "
                           f"{payload.get('message', '')} "
                           f"{str(payload.get('errors', ''))[:300]}")
        return payload

    # -- catalog ------------------------------------------------------
    def list_os_categories(self) -> dict:
        return self._request("GET", "/images/os-category/")

    def list_os_plans(self, os: str = "", osversion: str = "",
                      category: str = "") -> dict:
        return self._request("GET", "/images/",
                             extra={"os": os, "osversion": osversion,
                                    "category": category})

    # -- nodes --------------------------------------------------------
    def create_node(self, body: dict) -> dict:
        return self._request("POST", "/nodes/", body=body)

    def list_nodes(self) -> dict:
        return self._request("GET", "/nodes/")

    def get_node(self, node_id: str | int) -> dict:
        return self._request("GET", f"/nodes/{node_id}/")

    def node_action(self, node_id: str | int, action: str,
                    name: str = "") -> dict:
        body: dict[str, str] = {"type": action}
        if name:
            body["name"] = name
        return self._request("PUT", f"/nodes/{node_id}/actions/", body=body)

    def power_off(self, node_id: str | int) -> dict:
        """Pause: compute billing stops, disk and data persist."""
        return self.node_action(node_id, "power_off")

    def power_on(self, node_id: str | int) -> dict:
        return self.node_action(node_id, "power_on")

    def delete_node(self, node_id: str | int) -> dict:
        """Kill: irreversible. Releases the auto-allocated public IP."""
        return self._request("DELETE", f"/nodes/{node_id}/")

    def billing_log(self, vm_id: str | int) -> dict:
        return self._request("GET", f"/nodes/nodebillinglog/{vm_id}")


def extract_node_id(payload: dict) -> str:
    """Find the node id in a create/get response, tolerating shape drift."""
    data = payload.get("data", payload)
    if isinstance(data, dict):
        nested = data.get("node_create_response")
        if isinstance(nested, list) and nested and isinstance(
                nested[0], dict):
            for key in ("id", "vm_id", "node_id"):
                if nested[0].get(key) not in (None, ""):
                    return str(nested[0][key])
        for key in ("id", "vm_id", "node_id"):
            if data.get(key) not in (None, ""):
                return str(data[key])
        for value in data.values():
            if isinstance(value, dict):
                for key in ("id", "vm_id", "node_id"):
                    if value.get(key) not in (None, ""):
                        return str(value[key])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        for key in ("id", "vm_id", "node_id"):
            if data[0].get(key) not in (None, ""):
                return str(data[0][key])
    raise E2EError(f"could not find node id in response: "
                   f"{str(payload)[:300]}")


def extract_public_ip(node: dict) -> str:
    """Find the public IPv4 in a get-node response."""
    data = node.get("data", node) if isinstance(node, dict) else {}
    if not isinstance(data, dict):
        return ""
    for key in ("public_ip_address", "public_ip", "ip_address"):
        value = data.get(key)
        if isinstance(value, str) and value and value != "[]":
            return value.split(",")[0].strip().strip("[]'\" ")
        if isinstance(value, list) and value:
            return str(value[0])
    return ""

from azure.identity import DefaultAzureCredential
import urllib.request
import json

_credential = None

def get_token() -> str:
    """Get a fresh Azure management API token. Credential is reused across calls."""
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential.get_token("https://management.azure.com/.default").token


def azure_get(url: str) -> dict:
    """Authenticated GET against Azure management APIs."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {get_token()}"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            return {"ok": True, "data": json.loads(response.read().decode())}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def azure_post(url: str, body: dict) -> dict:
    """Authenticated POST against Azure management APIs."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as response:
            return {"ok": True, "data": json.loads(response.read().decode())}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

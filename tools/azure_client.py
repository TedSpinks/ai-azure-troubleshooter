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


def azure_get_paged(url: str, max_results: int) -> dict:
    """
    Authenticated GET against Azure management APIs with automatic paging.
    Follows nextLink until all results are fetched or max_results is reached.

    Returns:
        ok: True/False
        data: {"value": [...all collected items...]}
        results_truncated: True if stopped due to max_results, False if all pages fetched
    """
    all_values = []
    next_url = url

    while next_url:
        result = azure_get(next_url)
        if not result["ok"]:
            return result

        data = result["data"]
        page_values = data.get("value", [])
        remaining = max_results - len(all_values)

        if len(page_values) >= remaining:
            # Taking this page would hit or exceed the limit
            all_values.extend(page_values[:remaining])
            return {
                "ok": True,
                "data": {"value": all_values},
                "results_truncated": True
            }

        all_values.extend(page_values)
        next_url = data.get("nextLink")

    return {
        "ok": True,
        "data": {"value": all_values},
        "results_truncated": False
    }


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


def azure_post_paged(url: str, body: dict, max_results: int) -> dict:
    """
    Authenticated POST against Azure management APIs with automatic paging.
    Used for OData APIs (e.g. Policy Insights) where nextLink pages are
    fetched via POST rather than GET.

    Returns:
        ok: True/False
        data: {"value": [...all collected items...]}
        results_truncated: True if stopped due to max_results, False if all pages fetched
    """
    all_values = []
    next_url = url
    current_body = body

    while next_url:
        result = azure_post(next_url, current_body)
        if not result["ok"]:
            return result

        data = result["data"]
        page_values = data.get("value", [])
        remaining = max_results - len(all_values)

        if len(page_values) >= remaining:
            all_values.extend(page_values[:remaining])
            return {
                "ok": True,
                "data": {"value": all_values},
                "results_truncated": True
            }

        all_values.extend(page_values)
        # Policy Insights uses @odata.nextLink for subsequent pages
        next_url = data.get("@odata.nextLink") or data.get("nextLink")
        # Subsequent POST pages use empty body — the nextLink URL contains
        # the skiptoken that identifies the next page
        current_body = {}

    return {
        "ok": True,
        "data": {"value": all_values},
        "results_truncated": False
    }

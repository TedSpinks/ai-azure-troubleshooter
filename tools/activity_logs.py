from tools.azure_client import azure_get_paged
import urllib.parse
from datetime import datetime, timedelta, timezone

def get_activity_logs(
    subscription_id: str,
    resource_group: str = None,
    hours_back: int = 24,
    filter_text: str = None,
    correlation_id: str = None,
    max_events: int = 200
) -> dict:
    """
    Fetch Azure activity logs for a subscription or resource group.
    Useful for deployment troubleshooting, DINE policy evaluation history,
    and understanding what changed and when.

    Args:
        subscription_id: Azure subscription ID
        resource_group: Optional — scope to a resource group
        hours_back: How many hours back to look (max ~2160 for 90 days)
        filter_text: Optional — filter results by resource name fragment or
            operation name keyword, e.g. 'mitn-ap-ds1a' or
            'Microsoft.PolicyInsights'. Applied client-side after fetching
            results, so partial names and keywords both work.
        correlation_id: Optional — filter to a specific correlation ID to find
            all operations that were part of the same logical action, including
            parent deployments that triggered a child deployment
        max_events: Maximum number of events to return. Defaults to 200.
            Activity logs can be very high volume — increasing this on broad
            queries (e.g. subscription-wide, long time windows) may be slow.
            Prefer narrowing scope with resource_group, filter_text, or a
            shorter hours_back before increasing max_events.
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours_back)

    time_filter = (
        f"eventTimestamp ge '{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}' "
        f"and eventTimestamp le '{end_time.strftime('%Y-%m-%dT%H:%M:%SZ')}'"
    )
    # When filtering by correlation_id, skip resource group scoping —
    # correlation IDs are globally unique and resource group filtering
    # with AND logic can exclude valid events
    if resource_group and not correlation_id:
        time_filter += f" and resourceGroupName eq '{resource_group}'"
    if correlation_id:
        time_filter += f" and correlationId eq '{correlation_id}'"

    # Always query at subscription scope — the Activity Logs API does not
    # support resource group scope in the URL path. Resource group filtering
    # is handled via the $filter parameter above.
    scope = f"subscriptions/{subscription_id}"

    params = urllib.parse.urlencode({
        "api-version": "2015-04-01",
        "$filter": time_filter,
        "$select": "eventTimestamp,operationName,status,caller,resourceId,resourceGroupName,properties,correlationId"
    })

    result = azure_get_paged(
        f"https://management.azure.com/{scope}/providers/microsoft.insights/eventtypes/management/values?{params}",
        max_results=max_events
    )
    if not result["ok"]:
        return {"error": result["error"]}

    events = result["data"].get("value", [])
    results_truncated = result["results_truncated"]
    total_fetched = len(events)

    all_events = [{
        "timestamp": e.get("eventTimestamp"),
        "operation": e.get("operationName", {}).get("localizedValue"),
        "status": e.get("status", {}).get("localizedValue"),
        "caller": e.get("caller"),
        "resourceId": e.get("resourceId"),
        "resourceGroup": e.get("resourceGroupName"),
        "correlationId": e.get("correlationId"),
        "properties": e.get("properties", {})
    } for e in events]

    # Apply filter_text client-side — matches against resourceId or operation
    # name so partial names and keywords both work reliably
    if filter_text:
        filter_lower = filter_text.lower()
        trimmed = [
            e for e in all_events
            if filter_lower in (e.get("resourceId") or "").lower()
            or filter_lower in (e.get("operation") or "").lower()
        ]
    else:
        trimmed = all_events

    return {
        "events": trimmed,
        "count": len(trimmed),
        "total_fetched": total_fetched,
        "results_truncated": results_truncated,
        "filter_applied": filter_text,
        "summary": (
            f"Found {len(trimmed)} activity log events"
            + (f" matching '{filter_text}'" if filter_text else "")
            + f" (fetched {total_fetched} total from API"
            + (" — result limit reached, further events may exist."
               " Narrow scope with resource_group, filter_text, or hours_back,"
               " or increase max_events)"
               if results_truncated else ")")
            + f" in the last {hours_back} hours"
            + (f" in resource group '{resource_group}'" if resource_group else "")
            + (f" with correlation ID '{correlation_id}'" if correlation_id else "")
        ),
        "history_summary": {
            "count": len(trimmed),
            "total_fetched": total_fetched,
            "results_truncated": results_truncated,
            "filter_applied": filter_text,
            "summary": (
                f"Found {len(trimmed)} activity log events"
                + (f" matching '{filter_text}'" if filter_text else "")
                + f" (fetched {total_fetched} total from API"
                + (" — result limit reached, further events may exist."
                   " Narrow scope with resource_group, filter_text, or hours_back,"
                   " or increase max_events)"
                   if results_truncated else ")")
                + f" in the last {hours_back} hours"
                + (f" in resource group '{resource_group}'" if resource_group else "")
                + (f" with correlation ID '{correlation_id}'" if correlation_id else "")
            )
        }
    }

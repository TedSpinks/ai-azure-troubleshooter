from tools.azure_client import azure_get, azure_get_paged, azure_post
from datetime import datetime, timezone, timedelta
import json

def get_resource_properties(resource_id: str) -> dict:
    """
    Fetch the full ARM properties of any Azure resource by its resource ID.
    Used to compare actual resource state against policy conditions, or to
    inspect the current configuration of any resource for troubleshooting.

    Args:
        resource_id: Full Azure resource ID, e.g.
            /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{name}
    """
    parts = resource_id.strip("/").split("/")
    try:
        prov_idx = next(i for i, p in enumerate(parts) if p.lower() == "providers")
        provider_namespace = parts[prov_idx + 1]
        resource_type = parts[prov_idx + 2]
    except (StopIteration, IndexError):
        return {"error": f"Could not parse provider/type from resource ID: {resource_id}"}

    # Look up the latest stable API version for this resource type
    prov_result = azure_get(
        f"https://management.azure.com/providers/{provider_namespace}?api-version=2021-04-01"
    )

    api_version = "2021-04-01"
    if prov_result["ok"]:
        for rt in prov_result["data"].get("resourceTypes", []):
            if rt.get("resourceType", "").lower() == resource_type.lower():
                versions = rt.get("apiVersions", [])
                stable = [v for v in versions if "preview" not in v.lower()]
                api_version = stable[0] if stable else (versions[0] if versions else api_version)
                break

    result = azure_get(
        f"https://management.azure.com/{resource_id.strip('/')}?api-version={api_version}"
    )
    if not result["ok"]:
        return {"error": result["error"]}

    data = result["data"]
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "type": data.get("type"),
        "location": data.get("location"),
        "tags": data.get("tags", {}),
        "properties": data.get("properties", {}),
        "sku": data.get("sku"),
        "kind": data.get("kind"),
        "identity": data.get("identity"),
        "api_version_used": api_version
    }


def list_resource_groups(
    subscription_id: str,
    name_filter: str = None,
    location_filter: str = None,
    tag_filter: dict = None,
    max_results: int = 500
) -> dict:
    """
    List resource groups in a subscription with optional filtering.
    Use filters to narrow results when the user specifies a region,
    naming pattern, or tag — this reduces the data the agent needs
    to process and keeps investigations focused.

    Args:
        subscription_id: Azure subscription ID
        name_filter: Optional substring to match against resource group
            names (case-insensitive). E.g. "prod" matches "rg-prod-eastus".
        location_filter: Optional Azure region to filter by, e.g. "eastus2".
            Normalizes common aliases (e.g. "east us 2" → "eastus2").
        tag_filter: Optional dict of tag key/value pairs that must all be
            present on the resource group. E.g. {"env": "prod", "team": "platform"}.
        max_results: Maximum number of resource groups to return. Defaults to
            500, which covers most subscriptions in full. Increase if results
            appear truncated.
    """
    params = "api-version=2021-04-01"
    if tag_filter and len(tag_filter) == 1:
        # Single tag — use server-side filter for efficiency
        key, value = next(iter(tag_filter.items()))
        import urllib.parse
        params += f"&$filter=tagName+eq+'{urllib.parse.quote(key)}'+and+tagValue+eq+'{urllib.parse.quote(value)}'"

    result = azure_get_paged(
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourcegroups?{params}",
        max_results=max_results
    )
    if not result["ok"]:
        return {"error": result["error"]}

    groups = result["data"].get("value", [])
    results_truncated = result["results_truncated"]

    # Client-side filtering for name, location, and multi-tag
    if name_filter:
        groups = [
            g for g in groups
            if name_filter.lower() in g.get("name", "").lower()
        ]

    if location_filter:
        normalized = location_filter.replace(" ", "").lower()
        groups = [
            g for g in groups
            if g.get("location", "").replace(" ", "").lower() == normalized
        ]

    if tag_filter and len(tag_filter) > 1:
        def has_all_tags(g):
            resource_tags = {
                k.lower(): v.lower()
                for k, v in g.get("tags", {}).items()
            }
            return all(
                resource_tags.get(k.lower()) == v.lower()
                for k, v in tag_filter.items()
            )
        groups = [g for g in groups if has_all_tags(g)]

    trimmed = []
    for g in groups:
        trimmed.append({
            "name": g.get("name"),
            "location": g.get("location"),
            "provisioning_state": g.get("properties", {}).get("provisioningState"),
            "tags": g.get("tags", {})
        })

    filter_desc = []
    if name_filter:
        filter_desc.append(f"name contains '{name_filter}'")
    if location_filter:
        filter_desc.append(f"location '{location_filter}'")
    if tag_filter:
        filter_desc.append(f"tags {tag_filter}")
    filter_str = f" (filtered by {', '.join(filter_desc)})" if filter_desc else ""

    truncation_note = (
        f" — result limit of {max_results} reached, results are incomplete."
        " Increase max_results or apply filters to narrow scope."
        if results_truncated else ""
    )

    return {
        "resource_groups": trimmed,
        "count": len(trimmed),
        "results_truncated": results_truncated,
        "names": [g["name"] for g in trimmed],
        "filters_applied": {
            "name_filter": name_filter,
            "location_filter": location_filter,
            "tag_filter": tag_filter
        },
        "summary": (
            f"Found {len(trimmed)} resource group(s){filter_str}{truncation_note}: "
            + ", ".join(g["name"] for g in trimmed)
        )
    }


def get_deployment_operations(
    subscription_id: str,
    resource_group: str,
    deployment_name: str = None,
    top: int = 10
) -> dict:
    """
    Get ARM deployment history and per-operation results for a resource group.
    If deployment_name is provided, returns detailed step-by-step operations
    including failure messages. If not provided, lists recent deployments.

    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        deployment_name: Optional — specific deployment to drill into
        top: Maximum number of deployments to return when listing. Defaults to 10.
    """
    base = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Resources/deployments"
    )

    if deployment_name:
        ops_result = azure_get(f"{base}/{deployment_name}/operations?api-version=2021-04-01")
        if not ops_result["ok"]:
            return {"error": ops_result["error"]}

        ops = ops_result["data"].get("value", [])
        trimmed = []
        for op in ops:
            props = op.get("properties", {})
            status_msg = props.get("statusMessage", {})
            error = status_msg.get("error", status_msg) if isinstance(status_msg, dict) else status_msg
            trimmed.append({
                "operation_id": op.get("operationId"),
                "provisioning_state": props.get("provisioningState"),
                "resource_type": props.get("targetResource", {}).get("resourceType"),
                "resource_name": props.get("targetResource", {}).get("resourceName"),
                "timestamp": props.get("timestamp"),
                "duration": props.get("duration"),
                "status_code": props.get("statusCode"),
                "status_message": error
            })

        deploy_result = azure_get(f"{base}/{deployment_name}?api-version=2021-04-01")
        overall = {}
        if deploy_result["ok"]:
            dp = deploy_result["data"].get("properties", {})
            overall = {
                "provisioning_state": dp.get("provisioningState"),
                "timestamp": dp.get("timestamp"),
                "duration": dp.get("duration"),
                "correlation_id": dp.get("correlationId"),
                "error": dp.get("error")
            }

        failed = [o for o in trimmed if o["provisioning_state"] == "Failed"]
        return {
            "deployment_name": deployment_name,
            "overall_status": overall,
            "operations": trimmed,
            "operation_count": len(trimmed),
            "failed_operations": failed,
            "summary": (
                f"Deployment '{deployment_name}' had {len(trimmed)} operations, "
                f"{len(failed)} failed"
            )
        }

    else:
        result = azure_get(f"{base}?api-version=2021-04-01&$top={top}")
        if not result["ok"]:
            return {"error": result["error"]}

        deployments = result["data"].get("value", [])
        trimmed = []
        for d in deployments:
            props = d.get("properties", {})
            trimmed.append({
                "name": d.get("name"),
                "provisioning_state": props.get("provisioningState"),
                "timestamp": props.get("timestamp"),
                "duration": props.get("duration"),
                "correlation_id": props.get("correlationId"),
                "error": props.get("error")
            })

        failed = [d for d in trimmed if d["provisioning_state"] == "Failed"]
        count = len(trimmed)
        if count == 0:
            summary_prefix = f"No deployments found in '{resource_group}'"
        elif count < top:
            summary_prefix = f"Found all {count} deployments in '{resource_group}'"
        else:
            summary_prefix = f"Showing the {top} most recent deployments in '{resource_group}'"

        return {
            "resource_group": resource_group,
            "deployments": trimmed,
            "count": count,
            "failed_count": len(failed),
            "failed_deployments": failed,
            "summary": f"{summary_prefix}, {len(failed)} failed."
        }


def get_deployment_template(
    subscription_id: str,
    resource_group: str,
    deployment_name: str
) -> dict:
    """
    Retrieve the ARM template used for a specific deployment. Use this to
    understand exactly what resources a deployment was trying to create,
    including scope target resources that may have triggered the deployment.

    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group containing the deployment
        deployment_name: Name of the deployment to retrieve the template for
    """
    result = azure_post(
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Resources/deployments/{deployment_name}"
        f"/exportTemplate?api-version=2021-04-01",
        body={}
    )
    if not result["ok"]:
        return {"error": result["error"]}

    template = result["data"].get("template", {})
    resources = template.get("resources", [])

    scope_targets = []
    for resource in resources:
        props = resource.get("properties", {})

        scope = props.get("scope", [])
        if isinstance(scope, list):
            scope_targets.extend(scope)
        elif isinstance(scope, str):
            scope_targets.append(scope)

        scopes = props.get("scopes", [])
        if isinstance(scopes, list):
            scope_targets.extend(scopes)

    scope_targets = [t for t in scope_targets if t.startswith("/subscriptions/")]

    resource_types = list({r.get("type", "unknown") for r in resources})
    resource_names = [r.get("name", "unknown") for r in resources]

    return {
        "deployment_name": deployment_name,
        "template": template,
        "scope_target_resource_ids": scope_targets,
        "resource_types": resource_types,
        "resource_names": resource_names,
        "summary": (
            f"Template for '{deployment_name}' retrieved. "
            f"Deploying: {', '.join(resource_types)}. "
            f"Scope targets: {scope_targets if scope_targets else 'none found'}"
        )
    }


def get_deployment_details(
    subscription_id: str,
    resource_group: str,
    deployment_name: str
) -> dict:
    """
    Get full details of a specific ARM deployment including its correlation ID
    and related metadata. The correlation ID is especially useful for finding
    parent/child deployment relationships — related deployments triggered by
    the same operation share a correlation ID. Use this before calling
    get_activity_logs with a correlation_id to trace a child deployment back
    to the parent operation that caused it.

    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group containing the deployment
        deployment_name: Name of the deployment
    """
    result = azure_get(
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Resources/deployments/{deployment_name}"
        f"?api-version=2021-04-01"
    )
    if not result["ok"]:
        return {"error": result["error"]}

    d = result["data"]
    props = d.get("properties", {})

    return {
        "name": d.get("name"),
        "id": d.get("id"),
        "provisioning_state": props.get("provisioningState"),
        "timestamp": props.get("timestamp"),
        "duration": props.get("duration"),
        "correlation_id": props.get("correlationId"),
        "deployment_mode": props.get("mode"),
        "error": props.get("error"),
        "template_hash": props.get("templateHash"),
        "providers": props.get("providers", []),
        "summary": (
            f"Deployment '{d.get('name')}' — {props.get('provisioningState')}. "
            f"Correlation ID: {props.get('correlationId')}"
        )
    }


def list_resources(
    subscription_id: str,
    resource_group: str,
    resource_type: str = None,
    max_results: int = 500
) -> dict:
    """
    List all resources in a resource group, with optional filtering by
    resource type. Use this when you need to enumerate resources of a
    specific type (e.g. all VMs) without knowing their names — for example,
    when checking policy evaluation details across all VMs in a group.

    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group to list resources in
        resource_type: Optional resource type filter, e.g.
            'Microsoft.Compute/virtualMachines'. Case-insensitive.
        max_results: Maximum number of resources to return. Defaults to 500.
            Increase if results appear truncated.
    """
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/resources?api-version=2021-04-01"
    )
    if resource_type:
        import urllib.parse
        url += f"&$filter=resourceType+eq+'{urllib.parse.quote(resource_type)}'"

    result = azure_get_paged(url, max_results=max_results)
    if not result["ok"]:
        return {"error": result["error"]}

    resources = result["data"].get("value", [])
    results_truncated = result["results_truncated"]

    trimmed = []
    for r in resources:
        trimmed.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "type": r.get("type"),
            "location": r.get("location"),
            "tags": r.get("tags", {})
        })

    filter_str = f" of type '{resource_type}'" if resource_type else ""
    truncation_note = (
        f" — result limit of {max_results} reached, results are incomplete."
        " Increase max_results or filter by resource_type to narrow scope."
        if results_truncated else ""
    )

    return {
        "resources": trimmed,
        "count": len(trimmed),
        "results_truncated": results_truncated,
        "resource_group": resource_group,
        "resource_ids": [r["id"] for r in trimmed],
        "summary": (
            f"Found {len(trimmed)} resource(s){filter_str} "
            f"in '{resource_group}'{truncation_note}"
        )
    }

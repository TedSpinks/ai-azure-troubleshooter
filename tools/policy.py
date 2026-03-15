from tools.azure_client import azure_get, azure_post
import urllib.parse


def get_policy_definition(policy_definition_id: str) -> dict:
    """
    Fetch a policy definition including its full if/then rule.
    Essential for understanding evaluation conditions and effects
    (audit, deny, DINE, modify).

    Args:
        policy_definition_id: Full resource ID of the policy definition
    """
    result = azure_get(
        f"https://management.azure.com{policy_definition_id}?api-version=2021-06-01"
    )
    if not result["ok"]:
        return {"error": result["error"]}

    d = result["data"]
    props = d.get("properties", {})
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "display_name": props.get("displayName"),
        "description": props.get("description"),
        "mode": props.get("mode"),
        "policy_type": props.get("policyType"),
        "if_condition": props.get("policyRule", {}).get("if"),
        "then_effect": props.get("policyRule", {}).get("then"),
        "parameters": props.get("parameters", {}),
        "metadata": props.get("metadata", {})
    }


def get_policy_compliance_state(
    subscription_id: str,
    resource_group: str = None,
    policy_assignment_id: str = None,
    resource_id: str = None
) -> dict:
    """
    Get policy compliance state for a scope or specific resource.
    Primary tool for understanding why resources are compliant,
    non-compliant, or not appearing in compliance at all.

    Args:
        subscription_id: Azure subscription ID
        resource_group: Optional — scope to a resource group
        policy_assignment_id: Optional — filter to one assignment
        resource_id: Optional — single resource lookup
    """
    if resource_id:
        url = (
            f"https://management.azure.com{resource_id}"
            f"/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults"
            f"?api-version=2019-10-01"
        )
    elif resource_group:
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults"
            f"?api-version=2019-10-01"
        )
    else:
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults"
            f"?api-version=2019-10-01"
        )

    body = {"$top": 100}
    if policy_assignment_id:
        body["$filter"] = f"policyAssignmentId eq '{policy_assignment_id}'"

    result = azure_post(url, body)
    if not result["ok"]:
        return {"error": result["error"]}

    states = result["data"].get("value", [])
    summary = {}
    for s in states:
        state = s.get("complianceState", "unknown")
        summary[state] = summary.get(state, 0) + 1

    trimmed = [{
        "resource_id": s.get("resourceId"),
        "resource_type": s.get("resourceType"),
        "resource_group": s.get("resourceGroup"),
        "compliance_state": s.get("complianceState"),
        "policy_assignment_id": s.get("policyAssignmentId"),
        "policy_definition_id": s.get("policyDefinitionId"),
        "policy_definition_action": s.get("policyDefinitionAction"),
        "timestamp": s.get("timestamp"),
        "subscription_id": s.get("subscriptionId")
    } for s in states]

    return {
        "states": trimmed,
        "count": len(trimmed),
        "summary_by_state": summary,
        "summary": f"Found {len(trimmed)} compliance records. Breakdown: {summary}"
    }


def get_policy_evaluation_details(
    subscription_id: str,
    resource_id: str,
    policy_assignment_id: str = None
) -> dict:
    """
    Get detailed evaluation results for a specific resource showing exactly
    which policy conditions passed or failed and what the actual vs expected
    values were. Critical for DINE debugging and non-compliance explanation.

    Args:
        subscription_id: Azure subscription ID
        resource_id: Full resource ID to inspect
        policy_assignment_id: Optional — narrow to one assignment
    """
    url = (
        f"https://management.azure.com{resource_id}"
        f"/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults"
        f"?api-version=2019-10-01&$expand=PolicyEvaluationDetails"
    )

    body = {}
    if policy_assignment_id:
        body["$filter"] = f"policyAssignmentId eq '{policy_assignment_id}'"

    result = azure_post(url, body)
    if not result["ok"]:
        return {"error": result["error"]}

    states = result["data"].get("value", [])
    results = [{
        "resource_id": s.get("resourceId"),
        "compliance_state": s.get("complianceState"),
        "policy_assignment_id": s.get("policyAssignmentId"),
        "policy_definition_id": s.get("policyDefinitionId"),
        "policy_definition_action": s.get("policyDefinitionAction"),
        "evaluation_details": s.get("policyEvaluationDetails", {}),
        "timestamp": s.get("timestamp")
    } for s in states]

    return {
        "results": results,
        "count": len(results),
        "summary": f"Found {len(results)} detailed evaluation records for this resource"
    }


def get_remediation_tasks(
    subscription_id: str,
    resource_group: str = None,
    policy_assignment_id: str = None
) -> dict:
    """
    Get DINE/Modify remediation tasks showing whether remediation was
    attempted, succeeded, or failed — including deployment IDs when a
    DINE policy tried to deploy its ARM template.

    Args:
        subscription_id: Azure subscription ID
        resource_group: Optional — scope to a resource group
        policy_assignment_id: Optional — filter to one assignment
    """
    base = f"/subscriptions/{subscription_id}"
    if resource_group:
        base += f"/resourceGroups/{resource_group}"

    params = {"api-version": "2021-10-01"}
    if policy_assignment_id:
        params["$filter"] = f"properties/policyAssignmentId eq '{policy_assignment_id}'"

    url = (
        f"https://management.azure.com{base}"
        f"/providers/Microsoft.PolicyInsights/remediations"
        f"?{urllib.parse.urlencode(params)}"
    )

    result = azure_get(url)
    if not result["ok"]:
        return {"error": result["error"]}

    tasks = result["data"].get("value", [])
    trimmed = []
    for t in tasks:
        props = t.get("properties", {})
        trimmed.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "policy_assignment_id": props.get("policyAssignmentId"),
            "policy_definition_reference_id": props.get("policyDefinitionReferenceId"),
            "provisioning_state": props.get("provisioningState"),
            "created_on": props.get("createdOn"),
            "last_updated_on": props.get("lastUpdatedOn"),
            "total_deployments": props.get("deploymentStatus", {}).get("totalDeployments"),
            "successful_deployments": props.get("deploymentStatus", {}).get("successfulDeployments"),
            "failed_deployments": props.get("deploymentStatus", {}).get("failedDeployments"),
            "resource_discovery_mode": props.get("resourceDiscoveryMode"),
            "filters": props.get("filters", {})
        })

    return {
        "tasks": trimmed,
        "count": len(trimmed),
        "summary": f"Found {len(trimmed)} remediation tasks"
    }

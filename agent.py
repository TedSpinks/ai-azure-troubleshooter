import os
import json
from dotenv import load_dotenv
from contextlib import nullcontext

from tools.activity_logs import get_activity_logs
from tools.policy import (
    get_policy_definition,
    get_policy_compliance_state,
    get_policy_evaluation_details,
    get_remediation_tasks,
)
from tools.resources import (
    get_resource_properties,
    get_deployment_operations,
    get_deployment_template,
    get_deployment_details,
    list_resource_groups,
    list_resources,
)

env_file = os.environ.get("ENV_FILE", ".env")
load_dotenv(env_file)

# ── Configuration ─────────────────────────────────────────────────────────────
# BACKEND controls which agent loop is used:
#   foundry  — Microsoft Foundry Agents API (home tenant, full tracing)
#   aoai     — Azure OpenAI direct (cross-tenant, no tracing)
#
# Set BACKEND in your .env file or shell environment.

BACKEND         = os.environ.get("BACKEND", "aoai")
SUBSCRIPTION_ID = os.environ["AZURE_SUBSCRIPTION_ID"]

# Foundry-specific config (only required when BACKEND=foundry)
PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
FOUNDRY_MODEL    = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-4.1")

# Azure OpenAI config (only required when BACKEND=aoai)
AOAI_ENDPOINT    = os.environ.get("AZURE_OPENAI_ENDPOINT")
AOAI_API_KEY     = os.environ.get("AZURE_OPENAI_API_KEY")
AOAI_DEPLOYMENT  = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")
AOAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

# ── Tool registry ─────────────────────────────────────────────────────────────
# Maps function name (what the agent calls) to the actual Python function.
# To add a new tool later: add the function here and add its definition
# to TOOL_DEFINITIONS below.

TOOL_FUNCTIONS = {
    "get_activity_logs": lambda args: get_activity_logs(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_group=args.get("resource_group"),
        hours_back=args.get("hours_back", 48),
        filter_text=args.get("filter_text"),
        correlation_id=args.get("correlation_id"),
        max_events=args.get("max_events", 200),
    ),
    "get_policy_definition": lambda args: get_policy_definition(
        policy_definition_id=args["policy_definition_id"],
    ),
    "get_policy_compliance_state": lambda args: get_policy_compliance_state(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_group=args.get("resource_group"),
        policy_assignment_id=args.get("policy_assignment_id"),
        resource_id=args.get("resource_id"),
        max_results=args.get("max_results", 500),
    ),
    "get_policy_evaluation_details": lambda args: get_policy_evaluation_details(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_id=args["resource_id"],
        policy_assignment_id=args.get("policy_assignment_id"),
        max_results=args.get("max_results", 200),
    ),
    "get_remediation_tasks": lambda args: get_remediation_tasks(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_group=args.get("resource_group"),
        policy_assignment_id=args.get("policy_assignment_id"),
        max_results=args.get("max_results", 100),
    ),
    "get_resource_properties": lambda args: get_resource_properties(
        resource_id=args["resource_id"],
    ),
    "get_deployment_operations": lambda args: get_deployment_operations(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_group=args["resource_group"],
        deployment_name=args.get("deployment_name"),
        top=args.get("top", 10),
    ),
    "list_resource_groups": lambda args: list_resource_groups(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        name_filter=args.get("name_filter"),
        location_filter=args.get("location_filter"),
        tag_filter=args.get("tag_filter"),
        max_results=args.get("max_results", 500),
    ),
    "list_resources": lambda args: list_resources(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_group=args["resource_group"],
        resource_type=args.get("resource_type"),
        max_results=args.get("max_results", 500),
    ),
    "get_deployment_template": lambda args: get_deployment_template(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_group=args["resource_group"],
        deployment_name=args["deployment_name"],
    ),
    "get_deployment_details": lambda args: get_deployment_details(
        subscription_id=args.get("subscription_id", SUBSCRIPTION_ID),
        resource_group=args["resource_group"],
        deployment_name=args["deployment_name"],
    ),
}

# ── Tool definitions ──────────────────────────────────────────────────────────
# These are what the LLM sees — names, descriptions, and parameter schemas.
# The quality of these descriptions directly affects how well the agent
# decides when and how to call each tool.

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_activity_logs",
            "description": (
                "Fetch Azure activity logs for a subscription or resource group. "
                "Use this to see what operations occurred, who performed them, and "
                "whether they succeeded or failed. Essential for deployment "
                "troubleshooting and understanding what changed and when. "
                "Use correlation_id to find all operations related to the same "
                "logical action — including parent deployments that triggered "
                "child deployments. "
                "Note: activity logs are only available for the last 90 days."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_group": {
                        "type": "string",
                        "description": (
                            "Scope logs to a specific resource group. "
                            "Do NOT provide this when using correlation_id — "
                            "correlation ID searches must run at subscription scope "
                            "to find all related events. Only use resource_group "
                            "for time-based searches without a correlation_id."
                        )
                    },
                    "hours_back": {
                        "type": "integer",
                        "description": "How many hours back to search. Default 48. Max ~2160 (90 days)."
                    },
                    "filter_text": {
                        "type": "string",
                        "description": (
                            "Optional keyword to filter results by resource name "
                            "fragment or operation name. Applied client-side after "
                            "fetching — partial names and keywords both work, e.g. "
                            "'mitn-ap-ds1a' to narrow to a specific resource, or "
                            "'Microsoft.PolicyInsights' to find policy events. "
                            "Note: if the API returns 200 events before filtering, "
                            "results may be incomplete — narrow the time window or "
                            "resource group scope if this occurs."
                        )
                    },
                    "correlation_id": {
                        "type": "string",
                        "description": (
                            "Filter activity logs to a specific correlation ID to find all "
                            "operations that were part of the same logical action, including "
                            "parent deployments that triggered a child deployment. "
                            "When providing this, omit resource_group — the search must run "
                            "at subscription scope to return complete results."
                        )
                    },
                    "max_events": {
                        "type": "integer",
                        "description": (
                            "Maximum number of events to return. Defaults to 200. "
                            "Activity logs can be very high volume — increase only when "
                            "results_truncated is true and narrowing scope is not sufficient. "
                            "Prefer narrowing with resource_group, filter_text, or hours_back first."
                        )
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_deployment_details",
            "description": (
                "Get full details of a specific ARM deployment including its correlation ID. "
                "Only call this if the correlation ID is not already available from the "
                "deployment list results — get_deployment_operations includes correlation IDs "
                "in its output and should be checked first. Use this tool when you need the "
                "correlation ID to pass to get_activity_logs to trace what triggered a deployment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_group": {
                        "type": "string",
                        "description": "Resource group containing the deployment."
                    },
                    "deployment_name": {
                        "type": "string",
                        "description": "Name of the deployment to retrieve details for."
                    }
                },
                "required": ["resource_group", "deployment_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy_definition",
            "description": (
                "Fetch a policy definition including its full if/then rule. "
                "Use this to understand exactly what conditions a policy evaluates "
                "and what effect it applies (audit, deny, DeployIfNotExists, modify). "
                "Always call this when explaining why a resource is or isn't compliant, "
                "or when debugging why a DINE policy did or didn't fire."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "policy_definition_id": {
                        "type": "string",
                        "description": (
                            "Full resource ID of the policy definition, e.g. "
                            "/providers/Microsoft.Authorization/policyDefinitions/{name} "
                            "for built-ins, or "
                            "/subscriptions/{sub}/providers/Microsoft.Authorization/policyDefinitions/{name} "
                            "for custom policies."
                        )
                    }
                },
                "required": ["policy_definition_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy_compliance_state",
            "description": (
                "Get policy compliance state for a scope or specific resource. "
                "Use this to see which resources are compliant, non-compliant, or "
                "not evaluated — and which policy assignments are involved. "
                "If a resource isn't appearing in compliance at all, check here first "
                "then cross-reference with the policy definition's mode and conditions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_group": {
                        "type": "string",
                        "description": "Scope to a specific resource group."
                    },
                    "policy_assignment_id": {
                        "type": "string",
                        "description": "Filter results to a specific policy assignment."
                    },
                    "resource_id": {
                        "type": "string",
                        "description": "Get compliance state for one specific resource."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum number of compliance records to return. Defaults to 500. "
                            "Increase if results_truncated is true, or narrow scope with "
                            "resource_group or policy_assignment_id."
                        )
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy_evaluation_details",
            "description": (
                "Get detailed evaluation results for a specific resource showing "
                "exactly which policy conditions passed or failed, and what the "
                "actual vs expected values were. Use this after get_policy_compliance_state "
                "identifies a non-compliant or unexpectedly compliant resource. "
                "Critical for explaining the precise reason for any compliance state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_id": {
                        "type": "string",
                        "description": "Full resource ID of the resource to inspect."
                    },
                    "policy_assignment_id": {
                        "type": "string",
                        "description": "Optional — narrow results to one assignment."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum number of evaluation records to return. Defaults to 200, "
                            "which is generous for a single resource. Increase if results_truncated is true."
                        )
                    }
                },
                "required": ["resource_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_remediation_tasks",
            "description": (
                "Get DINE and Modify remediation tasks for a scope. "
                "Shows whether remediation was attempted, is in progress, succeeded, "
                "or failed — including how many deployments were triggered and how many "
                "failed. Use this when investigating why a DINE policy did not apply "
                "or produced unexpected results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_group": {
                        "type": "string",
                        "description": "Scope to a specific resource group."
                    },
                    "policy_assignment_id": {
                        "type": "string",
                        "description": "Filter to a specific policy assignment."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum number of remediation tasks to return. Defaults to 100, "
                            "which covers most environments in full. Increase if results_truncated is true."
                        )
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_resource_properties",
            "description": (
                "Fetch the full ARM properties of any Azure resource. "
                "Use this to compare the resource's actual configuration against "
                "policy conditions, or to inspect its current state when something "
                "looks wrong after a deployment. Automatically resolves the correct "
                "API version for the resource type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": (
                            "Full Azure resource ID, e.g. "
                            "/subscriptions/{sub}/resourceGroups/{rg}/"
                            "providers/Microsoft.Storage/storageAccounts/{name}"
                        )
                    }
                },
                "required": ["resource_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_deployment_operations",
            "description": (
                "Get ARM deployment history and per-operation results. "
                "If deployment_name is provided, returns step-by-step operations "
                "including detailed failure messages for each resource. "
                "If not provided, lists recent deployments in the resource group "
                "with their overall status, timestamps, and correlation IDs. "
                "Always start without a deployment_name to identify which deployment "
                "to investigate, then drill in with the name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_group": {
                        "type": "string",
                        "description": "Resource group to inspect."
                    },
                    "deployment_name": {
                        "type": "string",
                        "description": "Specific deployment name to drill into. Omit to list recent deployments."
                    },
                    "top": {
                        "type": "integer",
                        "description": "Maximum number of deployments to return when listing. Defaults to 10. Increase if the user wants to see further back in history."
                    }
                },
                "required": ["resource_group"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_resource_groups",
            "description": (
                "List resource groups in the subscription with optional filtering. "
                "Always call this first if the user hasn't specified a resource group "
                "and you need to know what exists. Use filters to narrow results when "
                "the user mentions a region, naming pattern, or tags — this keeps "
                "the investigation focused and reduces unnecessary data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "name_filter": {
                        "type": "string",
                        "description": (
                            "Optional substring to match against resource group names "
                            "(case-insensitive). Use when the user mentions a naming "
                            "pattern, e.g. 'prod', 'eastus', 'platform'."
                        )
                    },
                    "location_filter": {
                        "type": "string",
                        "description": (
                            "Optional Azure region to scope results to, e.g. 'eastus2'. "
                            "Use when the user is investigating a region-specific issue."
                        )
                    },
                    "tag_filter": {
                        "type": "object",
                        "description": (
                            "Optional dict of tag key/value pairs that must all be "
                            "present on the resource group. Use when the user refers "
                            "to resources by environment, team, or cost center tags. "
                            "E.g. {\"environment\": \"production\", \"team\": \"platform\"}."
                        )
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum number of resource groups to return. Defaults to 500, "
                            "which covers most subscriptions in full. Increase if "
                            "results_truncated is true in the response."
                        )
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_resources",
            "description": (
                "List all resources in a resource group, optionally filtered by "
                "resource type. Use this when you need to enumerate resources of a "
                "specific type without knowing their names — for example, to get "
                "all VMs in a resource group before checking policy evaluation "
                "details or resource properties for each one. The result includes "
                "a resource_ids field containing the full ARM resource IDs ready "
                "to pass directly to other tools. "
                "Note: the ARM resources list API does not support deeply nested "
                "sub-resource types such as "
                "Microsoft.RecoveryServices/vaults/backupFabrics/protectionContainers/protectedItems. "
                "For these, an empty result may not mean the resource does not exist — "
                "a dedicated API call may be required to get accurate results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_group": {
                        "type": "string",
                        "description": "Resource group to list resources in."
                    },
                    "resource_type": {
                        "type": "string",
                        "description": (
                            "Optional resource type to filter by, e.g. "
                            "'Microsoft.Compute/virtualMachines'. "
                            "Omit to return all resources in the group."
                        )
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum number of resources to return. Defaults to 500. "
                            "Increase if results_truncated is true in the response."
                        )
                    }
                },
                "required": ["resource_group"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_deployment_template",
            "description": (
                "Retrieve the ARM template used for a specific deployment. "
                "Use this to understand exactly what resources a deployment was "
                "trying to create, including scope target resources that may have "
                "triggered the deployment. The result includes a scope_target_resource_ids "
                "field containing the full ARM resource IDs of any existing resources "
                "the deployment was targeting or monitoring."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "string",
                        "description": "Azure subscription ID. Uses default if not provided."
                    },
                    "resource_group": {
                        "type": "string",
                        "description": "Resource group containing the deployment."
                    },
                    "deployment_name": {
                        "type": "string",
                        "description": "Name of the deployment to retrieve the template for."
                    }
                },
                "required": ["resource_group", "deployment_name"]
            }
        }
    },
]

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an Azure troubleshooting assistant specializing in \
Azure Policy and deployment diagnostics. You have access to tools that can read \
live data from Azure — activity logs, policy definitions, compliance states, \
evaluation details, remediation tasks, resource properties, deployment operations, \
and deployment templates.

The default Azure subscription ID is already configured — you never need to ask \
the user for it. All tools will use it automatically unless the user explicitly \
mentions a different subscription. Similarly, if the user mentions a resource group \
by name, use it directly without asking for confirmation.

When an investigation requires looking at resource groups and the user has not \
specified one, always ask whether they would like to provide specific resource \
group names or have you query across all resource groups in the subscription. \
Briefly mention that you can also filter by name pattern, Azure region, or tags. \
For example: "Would you like to specify particular resource groups, or should I \
query across all of them? I can also filter by name pattern (e.g. 'prod'), region \
(e.g. 'eastus2'), or tags (e.g. environment=production) if that helps narrow \
things down." If the user asks you to query all resource groups, call \
list_resource_groups first, then proceed — but be mindful that checking every \
resource group individually can be slow. Use filters when the user provides hints \
about naming patterns, regions, or tags.

Your job is to help the user investigate and explain the following types of problems:

1. WHY A RESOURCE IS NOT SHOWING UP IN COMPLIANCE, OR HAS AN UNEXPECTED COMPLIANCE STATE
   - Fetch the policy definition to understand its if/then conditions and mode
   - Fetch the resource's actual properties and compare them to the policy conditions
   - Check the policy assignment scope to confirm the resource is actually in scope
   - Check evaluation details to see exactly which conditions passed or failed
   - Common reasons: policy mode mismatch (Indexed vs All), resource type not covered,
     resource not yet evaluated, exemption in place, assignment scope excludes the resource

2. WHAT DINE OR MODIFY POLICIES WERE EVALUATED DURING A DEPLOYMENT
   - Check activity logs around the deployment time filtered to the resource group
   - Look for Microsoft.PolicyInsights events
   - Fetch relevant policy definitions to explain what each policy does

3. WHY A DINE POLICY DID NOT APPLY OR FAILED
   - Fetch the policy definition to understand its deployIfNotExists conditions
     and the ARM template in then.details
   - Use get_deployment_template to inspect the ARM template the DINE policy was
     trying to deploy — this helps identify template errors or missing dependencies
   - Check remediation tasks to see if deployment was attempted and what happened
   - Check activity logs for the deployment the DINE policy should have triggered
   - Check the managed identity permissions — DINE policies need a managed identity
     with sufficient RBAC on the target scope

4. GENERAL DEPLOYMENT TROUBLESHOOTING
   - If no resource group is specified, ask the user to provide one or more,
     or offer to query all — mentioning available filters
   - When listing deployments, always open your response with the exact summary
     line returned by the tool — do not paraphrase or reformat it. For example:
     "Found all 3 deployments in 'rg-test-cus-foundry01', 1 failed" or "Showing
     the 10 most recent deployments in 'rg-test-cus-foundry01', 1 failed." Then
     include each deployment with its timestamp beneath it.
   - Whenever a failed deployment appears in results — whether from listing
     deployments or when first asked about a specific one — always end your
     response by offering a thorough investigation: "Would you like me to do
     a thorough investigation? I can identify what triggered this deployment
     and confirm the causal relationship."
   - Reserve get_deployment_template, get_resource_properties, and
     get_activity_logs for the thorough investigation — do not call them
     as part of the initial summary.
   - When the user accepts a thorough investigation, call all of the following
     in a single turn before responding:
     (a) get_deployment_template to see what was being deployed
     (b) get_resource_properties on each resource ID listed in the
         scope_target_resource_ids field of the template result — use
         those exact IDs as-is, do not construct or modify them. If the
         field is empty, note that no scope targets were found and skip
         this step.
     (c) get_activity_logs with the failed deployment's correlationId —
         omit resource_group when using correlationId
     Then synthesize all findings into a root cause analysis:
     - Compare timestamps: calculate and state the exact time difference between
       the scope target's creation and the failed deployment. If the scope target
       was created shortly before the deployment, state that directly as evidence
       of a causal relationship — e.g. "the [resource type] was created X minutes
       before the deployment, strongly suggesting it triggered this automatically."
     - Identify the caller from the activity logs and keep investigating until
       one of the following stopping conditions is reached:
       (d) A named user, service principal, or managed identity (including a bare
           GUID) — report the identity, the operation they performed, and the
           timestamp. Note that a bare GUID typically indicates automation such
           as a CI/CD pipeline, scheduled runbook, or platform service. Stop here.
       (e) A Microsoft.PolicyInsights caller — follow the DINE policy
           investigation steps in IMPORTANT BEHAVIORS before stopping.
       (f) If the caller cannot be determined — state what additional information
           would be needed and why. Stop here.
     Do not summarize findings until a stopping condition is reached.
   - Before summarizing any deployment failure investigation, verify that
     get_resource_properties has been called on every resource ID in the
     scope_target_resource_ids field returned by get_deployment_template.
     If it has not, make those calls before responding. If the field was
     empty, note that and proceed.
   - To find what triggered a deployment, use the correlationId already present
     in the deployment list results. Only call get_deployment_details if the
     correlationId is not already available.

IMPORTANT BEHAVIORS:
- Before starting a multi-step investigation, briefly tell the user what you are
  going to look at and why — one or two sentences is enough. This helps the user
  course-correct if you have misunderstood the problem.
- Always ask clarifying questions before investigating if you need more context,
  such as the resource name, time window, or policy name.
- When you call a tool and get results, explain what you found in plain English
  before deciding what to call next.
- If activity logs are unavailable because the event is older than 90 days,
  say so clearly and explain what you can and cannot determine without them.
- When you identify a root cause, explain it clearly and suggest a specific
  remediation step.
- If you find something unexpected or interesting in the data that the user
  did not ask about, mention it briefly — it may be relevant.
- Do not guess. If the data does not support a conclusion, say what you found
  and what additional information would be needed.
- If you need a capability that no current tool provides, describe exactly which
  Azure REST API endpoint would provide the data, what parameters it needs, and
  what you would do with the result — not a generic framework description.
- When get_activity_logs reveals that the caller of the triggering operation
  was Microsoft.PolicyInsights or similar Azure Policy infrastructure (rather
  than a user or service principal), the deployment was triggered by a DINE
  (DeployIfNotExists) or Modify policy — not a human action. In this case:
  1. Note the policy assignment ID from the activity log event properties
  2. Call get_policy_evaluation_details to understand why the policy
     determined the resource was non-compliant
  3. Call get_remediation_tasks to see the remediation task that triggered
     the deployment and its current status
  4. Call get_policy_definition to retrieve the policy's if/then rule so
     you can explain exactly what condition triggered the deployment and
     what it was trying to enforce
  Your answer is not complete until you can explain: which policy fired,
  why it considered the resource non-compliant, and what it was trying to
  remediate.
"""

# ── Tool execution ────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, arguments: str, tracer=None) -> str:
    """Execute a tool call requested by the agent and return the result as a string."""
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Could not parse tool arguments: {e}"})

    fn = TOOL_FUNCTIONS.get(tool_name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    print(f"  → calling {tool_name}({json.dumps(args, indent=None)})")

    # If tracing is not configured, run the tool without instrumentation
    ctx = tracer.start_as_current_span(f"tool.{tool_name}") if tracer else nullcontext()

    with ctx as span:
        try:
            result = fn(args)
            result_str = json.dumps(result, default=str)

            if tracer and span:
                span.set_attribute("tool.name", tool_name)
                span.set_attribute("tool.arguments", json.dumps(args, default=str))
                span.set_attribute("tool.success", True)
                span.set_attribute("tool.result_length", len(result_str))
                # Summary gives enough signal (e.g. "Found 28 compliance records")
                # without logging potentially sensitive resource data to telemetry.
                summary = result.get("summary") or result.get("error") or "ok"
                span.set_attribute("tool.result_summary", str(summary))

                # Full result logging — DISABLED by default.
                # Enable temporarily for deep debugging only. Be aware that this
                # will write full Azure resource data (IDs, properties, policy
                # definitions) into Application Insights. Do not enable in
                # production environments where telemetry data is broadly accessible.
                # span.set_attribute("tool.result", result_str)

            return result_str

        except Exception as e:
            if tracer and span:
                span.set_attribute("tool.success", False)
                span.set_attribute("tool.error", str(e))
                span.record_exception(e)
            return json.dumps({"error": f"Tool execution failed: {e}"})

# ── Backend: Foundry ──────────────────────────────────────────────────────────

def setup_tracing():
    """Wire up OpenTelemetry to send traces to Application Insights."""
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry import trace as otel_trace

    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        print("Warning: No Application Insights connection string found, tracing disabled.")
        return None
    configure_azure_monitor(connection_string=connection_string)
    print("Tracing enabled → Application Insights")
    # Return a tracer scoped to this module, created AFTER configure_azure_monitor
    # so it is guaranteed to emit to the correct provider.
    return otel_trace.get_tracer(__name__)


def run_foundry():
    from azure.identity import DefaultAzureCredential
    from azure.ai.agents import AgentsClient
    from opentelemetry import trace as otel_trace

    if not PROJECT_ENDPOINT:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT is required for the foundry backend.")

    tracer = setup_tracing()  # may be None if no connection string
    credential = DefaultAzureCredential()
    client = AgentsClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    print(f"Environment : {env_file}")
    print(f"Subscription: {SUBSCRIPTION_ID}")
    print(f"Backend     : Foundry ({FOUNDRY_MODEL} @ {PROJECT_ENDPOINT})")

    print("Creating agent...")
    agent = client.create_agent(
        model=FOUNDRY_MODEL,
        name="azure-troubleshooter",
        instructions=SYSTEM_PROMPT,
        tools=TOOL_DEFINITIONS,
    )
    print(f"Agent created: {agent.id}")

    thread = client.threads.create()
    print(f"Thread created: {thread.id}")
    print("\nAzure Troubleshooting Assistant ready.")
    print("Describe your problem and I'll investigate. Type 'exit' to quit.\n")
    print("-" * 60)

    try:
        while True:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ("exit", "quit", "q"):
                break
            if not user_input:
                continue

            client.messages.create(
                thread_id=thread.id,
                role="user",
                content=user_input,
            )

            run = client.runs.create(
                thread_id=thread.id,
                agent_id=agent.id,
            )

            while run.status in ("queued", "in_progress", "requires_action"):
                run = client.runs.get(
                    thread_id=thread.id,
                    run_id=run.id,
                )

                if run.status == "requires_action":
                    tool_calls = run.required_action.submit_tool_outputs.tool_calls
                    tool_outputs = []

                    for tc in tool_calls:
                        result = execute_tool(tc.function.name, tc.function.arguments, tracer)
                        tool_outputs.append({
                            "tool_call_id": tc.id,
                            "output": result,
                        })

                    run = client.runs.submit_tool_outputs(
                        thread_id=thread.id,
                        run_id=run.id,
                        tool_outputs=tool_outputs,
                    )

                elif run.status in ("queued", "in_progress"):
                    import time
                    time.sleep(1)

            if run.status == "completed":
                messages = client.messages.list(thread_id=thread.id)
                for msg in messages:
                    if msg.role == "assistant":
                        for block in msg.content:
                            if hasattr(block, "text"):
                                print(f"\nAssistant: {block.text.value}")
                        break

                # Flush telemetry after each completed interaction so traces appear
                # in the portal during the session, not just on exit.
                provider = otel_trace.get_tracer_provider()
                if hasattr(provider, "force_flush"):
                    provider.force_flush(timeout_millis=5000)

            elif run.status == "failed":
                print(f"\n[Run failed: {run.last_error}]")

    finally:
        print("\nCleaning up...")
        client.delete_agent(agent.id)
        # Flush any pending telemetry before exit — without this, spans
        # buffered by BatchSpanProcessor are lost when the script exits.
        provider = otel_trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=10000)
            print("Telemetry flushed.")
        print("Done.")

# ── Backend: Azure OpenAI ─────────────────────────────────────────────────────

def run_aoai():
    from openai import AzureOpenAI

    if not AOAI_ENDPOINT:
        raise ValueError("AZURE_OPENAI_ENDPOINT is required for the aoai backend.")
    if not AOAI_API_KEY:
        raise ValueError("AZURE_OPENAI_API_KEY is required for the aoai backend.")

    client = AzureOpenAI(
        azure_endpoint=AOAI_ENDPOINT,
        api_key=AOAI_API_KEY,
        api_version=AOAI_API_VERSION,
    )

    print(f"Environment : {env_file}")
    print(f"Subscription: {SUBSCRIPTION_ID}")
    print(f"Backend     : Azure OpenAI ({AOAI_DEPLOYMENT} @ {AOAI_ENDPOINT})")
    print("\nAzure Troubleshooting Assistant ready.")
    print("Describe your problem and I'll investigate. Type 'exit' to quit.\n")
    print("-" * 60)

    # Conversation history — persists for the session, reset on restart
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit", "quit", "q"):
            print("\nDone.")
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # Inner loop — keep calling the model until it stops requesting tools
        while True:
            response = client.chat.completions.create(
                model=AOAI_DEPLOYMENT,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )

            message = response.choices[0].message

            # Always append the raw assistant message to history so tool
            # call IDs are preserved for the follow-up submission
            messages.append(message)

            if not message.tool_calls:
                # No tool calls — model has finished its response
                print(f"\nAssistant: {message.content}")
                break

            # Execute every tool call the model requested
            for tc in message.tool_calls:
                result = execute_tool(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            # Loop back — model will now process the tool results

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if BACKEND == "foundry":
        run_foundry()
    elif BACKEND == "aoai":
        run_aoai()
    else:
        raise ValueError(f"Unknown BACKEND '{BACKEND}'. Must be 'foundry' or 'aoai'.")

# Azure Policy & Deployment Troubleshooting Agent

An AI-powered troubleshooting assistant that investigates Azure Policy compliance issues and ARM deployment failures using live data from your Azure environment. You describe the problem in plain English; the agent reasons through it, calls the appropriate Azure APIs, and synthesizes a root cause explanation.

The script runs locally and authenticates to Azure via your active `az login` session. For connecting to the LLM, it supports two backends: **Azure OpenAI direct** (API key, any Entra ID tenant) and **Microsoft Foundry** (only the `az login` tenant). Both connect to GPT-4.1 hosted in Microsoft Foundry, Microsoft's AI platform on Azure. Azure OpenAI is the default for cross-tenant troubleshooting; use the Foundry backend during development for its built-in OpenTelemetry tracing to Application Insights.

Many organizations are cautious about consumer AI services retaining sensitive data. This tool mitigates that risk: it is stateless by design, and Microsoft Foundry's [enterprise terms](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy) explicitly prohibit using your data to train models. Foundry also adds data residency, compliance, and governance controls.

> **Just here to get started?** Jump to [Setup](#setup).

---

## What It Does

The agent is designed to investigate four categories of problems:

1. **Why a resource is not showing up in compliance, or has an unexpected compliance state** — fetches the policy definition, compares its conditions against the resource's actual properties, checks evaluation details to identify exactly which conditions passed or failed.

2. **What DINE or Modify policies were evaluated during a deployment** — searches activity logs for Microsoft.PolicyInsights events and explains what each policy was trying to enforce.

3. **Why a DINE policy did not apply or failed** — inspects the policy definition, the ARM template the policy tried to deploy, remediation tasks, and managed identity permissions.

4. **General deployment troubleshooting** — lists deployments, drills into failed ones, retrieves the ARM template, identifies what triggered the deployment, and traces the caller through activity logs.

---

## Project Structure

```
agent.py                # Single entry point — supports both backends
tools/
  __init__.py
  azure_client.py       # Shared auth + HTTP helpers
  activity_logs.py      # get_activity_logs
  policy.py             # Policy-specific tools
  resources.py          # ARM resource + deployment tools
.env                    # Your first tenant configuration
.env.other              # Example of a second tenant configuration
```

---

## Tools Available to the Agent

| Tool | Purpose |
|------|---------|
| `get_activity_logs` | Fetch activity logs by time window or correlation ID |
| `get_policy_definition` | Fetch a policy's full if/then rule and effect |
| `get_policy_compliance_state` | Get compliance state for a scope or resource |
| `get_policy_evaluation_details` | See exactly which conditions passed or failed |
| `get_remediation_tasks` | Check DINE/Modify remediation task status |
| `get_resource_properties` | Fetch full ARM properties of any resource |
| `get_deployment_operations` | List deployments or drill into a specific one |
| `get_deployment_template` | Retrieve the ARM template used in a deployment |
| `get_deployment_details` | Get full deployment details including correlation ID |
| `list_resource_groups` | List resource groups with optional filtering |

---

## Backend Options

The agent supports two backends, controlled by the `BACKEND` environment variable in your `.env` file. The backend determines how the LLM is accessed — the Azure tools always authenticate to ARM using `DefaultAzureCredential()` regardless of which backend is in use.

---

### Default: Azure OpenAI Direct (`BACKEND=aoai`)

Uses the Azure OpenAI service directly via the OpenAI Python SDK. The conversation history is managed as a Python list in memory. This is the default backend because it matches the primary use case: an Azure engineer connecting to multiple tenants for troubleshooting.

**Why this is the default:**

Azure engineers often work across many subscriptions in different Entra ID tenants. The Foundry Agents API requires a token from the same tenant as the Foundry resource, which means it cannot be used for cross-tenant work. The Azure OpenAI endpoint is just an HTTPS URL authenticated with an API key — it has no dependency on which tenant your Azure CLI is logged into, so it works from any tenant without configuration changes. A single Azure OpenAI resource in your home tenant serves all troubleshooting scenarios regardless of which tenant you are currently investigating.

**Pros:**
- Works across Entra ID tenant boundaries — the primary use case for this tool
- No server-side state — nothing to clean up if the script crashes
- Same model as Foundry (GPT-4.1)
- Simpler conversation loop — no agent/thread lifecycle to manage

**Cons:**
- No built-in tracing to Application Insights
- Conversation history is in-memory only — lost when the script exits

**Required `.env` variables:**
```
AZURE_SUBSCRIPTION_ID=<subscription-to-troubleshoot>
AZURE_OPENAI_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com
AZURE_OPENAI_API_KEY=<api-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
AZURE_OPENAI_API_VERSION=2024-05-01-preview
```

`BACKEND=aoai` is optional since `aoai` is the default — the script uses it automatically if `BACKEND` is not set.

**Note:** `AZURE_OPENAI_ENDPOINT` is the base hostname only — do not include the `/openai/deployments/...` path shown in the Foundry portal's Target URI field. The SDK constructs the full path from the endpoint, deployment name, and API version you provide separately.

---

### Microsoft Foundry (`BACKEND=foundry`)

Uses the Microsoft Foundry Agents API. The agent and conversation thread are created as persistent server-side objects in Foundry. This backend is recommended during active development when tracing and observability matter.

**When to use Foundry:**

During development and prompt tuning, Foundry provides full OpenTelemetry tracing to Application Insights. Each tool call is recorded as a span with the tool name, arguments, result summary, and success/failure status. This makes it easy to see exactly what the agent is doing turn by turn, catch regressions in tool calling behavior early, and diagnose cases where the agent is not following its investigation instructions correctly. For production cross-tenant troubleshooting, switch to the `aoai` backend.

**Pros:**
- Full tracing and observability via Application Insights — essential during development
- Agent runs visible in Foundry portal for debugging
- Conversation thread managed server-side — history persists across turns automatically
- Native Azure integration

**Cons:**
- Requires a Foundry resource in the same tenant you are authenticating to
- Cannot be used across Entra ID tenant boundaries
- If the script crashes before cleanup, the agent object persists in Foundry and must be deleted manually

**Required `.env` variables:**
```
BACKEND=foundry
AZURE_SUBSCRIPTION_ID=<subscription-to-troubleshoot>
FOUNDRY_PROJECT_ENDPOINT=https://<your-foundry>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL_DEPLOYMENT=gpt-4.1
APPLICATIONINSIGHTS_CONNECTION_STRING=<optional — disables tracing if omitted>
```

---

## Setup

### Prerequisites

- Python 3.10 or later
- Azure CLI installed and logged in (`az login`)
- A Microsoft Foundry project with a GPT-4.1 deployment (see Step 3 below)

---

### Step 1 — Clone the repo and create a virtual environment

```bash
git clone <repo-url>
cd ai-azure-troubleshooter

python3 -m venv .venv
source .venv/bin/activate
```

---

### Step 2 — Install dependencies

Minimal install (aoai backend only — suitable for cross-tenant use):

```bash
pip install azure-identity openai python-dotenv
```

Full install (supports both backends, for development):

```bash
pip install azure-identity \
            azure-ai-agents \
            azure-monitor-opentelemetry \
            opentelemetry-sdk \
            openai \
            python-dotenv
```

---

### Step 3 — Microsoft Foundry setup

Both backends use the same Microsoft Foundry resource. If you don't have one yet:

1. Go to the [Foundry Portal](https://ai.azure.com) and make sure the **New Foundry** toggle is on
2. Use the Project dropdown at the top to select an existing project or create a new one
3. In the **Build** tab, select **Models** from the left nav, then click **Deploy a base model** at the top right
4. Search for **gpt-4.1**, select it, and deploy

To configure the **Azure OpenAI (`aoai`) backend**, retrieve your endpoint and key:

1. In the Foundry portal, navigate to **Models > your GPT-4.1 deployment > Details**
2. The **Target URI** field shows the full path — your endpoint is the hostname portion only, e.g. `https://<n>.cognitiveservices.azure.com`
3. Copy the **Key** from the same page

Add to your `.env` file:

```
AZURE_SUBSCRIPTION_ID=<subscription-to-troubleshoot>
AZURE_OPENAI_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
AZURE_OPENAI_API_VERSION=2024-05-01-preview
```

To also use the **Microsoft Foundry (`foundry`) backend**, retrieve your project endpoint:

1. Copy the project endpoint from the Foundry project overview page — it looks like `https://<n>.services.ai.azure.com/api/projects/<project-name>`
2. Optionally, create an **Application Insights** resource and copy its connection string for tracing

Add to your `.env` file:

```
BACKEND=foundry
FOUNDRY_PROJECT_ENDPOINT=https://<your-foundry>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL_DEPLOYMENT=gpt-4.1
APPLICATIONINSIGHTS_CONNECTION_STRING=<optional>
```

---

### Step 4 — Run the agent

Activate your virtual environment if not already active:

```bash
source .venv/bin/activate
```

Run with your default `.env` (uses `aoai` backend unless `BACKEND=foundry` is set):

```bash
python3 agent.py
```

Switch to the Foundry backend for a development session:

```bash
BACKEND=foundry python3 agent.py
```

Run against a different tenant:

```bash
# Log into the target tenant first
az login --tenant <target-tenant-id>

# Run with an env file for that tenant
ENV_FILE=.env.other python3 agent.py
```

The startup output always shows which environment, subscription, and backend are active:

```
Environment : .env.other
Subscription: <subscription-id>
Backend     : Azure OpenAI (gpt-4.1 @ https://...)

Azure Troubleshooting Assistant ready.
Describe your problem and I'll investigate. Type 'exit' to quit.
```

---

## Multi-Tenant Usage

The agent tools authenticate to Azure ARM using `DefaultAzureCredential`, which respects whichever tenant your Azure CLI is currently logged into. To troubleshoot a subscription in a different Entra ID tenant:

```bash
az login --tenant <target-tenant-id>
ENV_FILE=.env.other python3 agent.py
```

Maintain one `.env` file per tenant context. A typical setup:

```
.env              # home tenant — connect with aoai or foundry
.env.other        # other tenant — aoai only
```

The `ENV_FILE` shell variable tells the script which `.env` file to load. It is read from the shell environment before `load_dotenv()` is called — there is no chicken-and-egg problem because it comes from the shell, not from a `.env` file.

**Important:** The Foundry backend cannot be used cross-tenant. The Foundry Agents API requires a token from the same tenant as the Foundry resource. Attempting cross-tenant use produces a `Tenant provided in token does not match resource tenant` error. Always use `BACKEND=aoai` for cross-tenant work.

---

## How the Conversation Loop Works

### Foundry backend

The Foundry SDK manages a server-side agent object and conversation thread. The Python script polls for run status and submits tool outputs when the agent requests them. Conversation history is maintained server-side across turns within the same thread automatically — your Python code never touches the history directly.

When you type `exit`, the script deletes the agent object from Foundry. If the script crashes before this cleanup runs, delete the orphaned agent manually in the Foundry portal under **Agents**, or via the Azure CLI.

### Azure OpenAI backend

This backend uses a stateless API. Conversation history is maintained as a Python `messages` list that grows through the session. The inner loop works as follows:

1. Append user message to history
2. Call the model with the full history and tool definitions
3. If the model returns tool calls, execute them and append results to history
4. Loop back to step 2 — the model processes the tool results and either calls more tools or produces a final response
5. When the model returns a response with no tool calls, print it and wait for the next user input

History is lost when the script exits. Each new session starts fresh with only the system prompt.

---

## Tracing and Observability

The Foundry backend includes OpenTelemetry instrumentation that sends traces to Application Insights. Each tool call is recorded as a span with the tool name, arguments, result summary, and success/failure status. Full result logging is disabled by default to avoid writing sensitive resource data to telemetry — it can be enabled temporarily by uncommenting a single line in `execute_tool()` for deep debugging.

Tracing is disabled automatically if `APPLICATIONINSIGHTS_CONNECTION_STRING` is not set — the script falls back gracefully with no code changes required.

The Azure OpenAI backend does not include tracing. This is an acceptable tradeoff for cross-tenant field use where Application Insights may not be accessible or relevant.

---

## System Prompt Design

The system prompt encodes the agent's investigation strategies as numbered scenarios with explicit step-by-step procedures. Key design decisions made during development:

**Redundant enforcement for critical steps.** The most important instruction — that `get_resource_properties` must be called using the exact resource IDs from the `scope_target_resource_ids` field returned by `get_deployment_template` — is enforced in two places: as a procedural step within the thorough investigation sequence, and as a pre-response gate that requires the agent to verify compliance before summarising findings. Single instructions for this step were repeatedly bypassed during testing; redundancy was necessary for reliability.

**Tool descriptions stay generic.** Investigation workflow instructions belong in the system prompt, not in tool descriptions. Putting workflow logic in tool descriptions makes tools tightly coupled to one scenario and can cause unexpected behaviour when the same tool is called in a different context.

**Summary lines are surfaced verbatim.** The tool returns a structured `summary` field, and the system prompt instructs the agent to open deployment listing responses with that exact string. This prevents the agent from paraphrasing counts and status in ways that lose precision.

**Stopping conditions for caller identification.** Rather than leaving the investigation open-ended, the system prompt defines explicit stopping conditions for tracing a deployment's origin: a named identity (user, service principal, or managed identity GUID), a Microsoft.PolicyInsights caller (which triggers the DINE investigation path), or an inability to determine the caller. This prevents the agent from over-investigating or under-investigating.

**Correlation ID scope rule.** Activity log searches using a correlation ID must run at subscription scope — filtering by resource group as well produces incomplete results. This is enforced in both the tool description and the system prompt.

---

## Ollama Local Model (Experimental — Not Recommended)

During development, a third backend was prototyped using Ollama with `qwen2.5:14b` running locally on an M4 MacBook Pro with 24GB unified memory. Ollama exposes an OpenAI-compatible API at `http://localhost:11434/v1`, so the conversation loop required only minor changes from the Azure OpenAI version. This was appealing as a fully offline, zero-cost option with no Azure dependency for the LLM.

The backend was not included in the final `agent.py` because the open source model fell significantly short of GPT-4o (my initial prototype model) for the reasoning this agent requires.

### Why Open Source Models Fell Short

`qwen2.5:14b` was chosen because it is one of the stronger open source models for tool calling at a size that fits comfortably in 24GB of unified memory on Apple Silicon. It handled single tool calls correctly but consistently failed at multi-step tool chaining — the core capability this agent depends on. Specifically:

- When asked to list deployments across all resource groups, it would call `list_resource_groups` to get the list, but then fail to connect those results to sequential `get_deployment_operations` calls for each group. It would either call `get_deployment_operations` without a resource group (causing a tool error), or re-list the resource groups repeatedly without making progress.
- It could not reliably execute the three-tool single-turn investigation pattern (template + resource properties + activity logs) that the system prompt prescribes for deployment failure analysis.
- Instruction-following for precise formatting requirements (e.g. "open your response with the exact summary line returned by the tool") was inconsistent.

These are not prompt engineering problems that can be solved with more specific instructions — they reflect a fundamental gap in agentic reasoning capability between 14B parameter open source models and GPT-4o at this task complexity. Larger open source models (32B+) would likely perform better, but were not tested.

The key insight is that this agent's value comes from **multi-step reasoning under uncertainty** — deciding what to look at next based on what the previous tool returned, synthesizing data from multiple sources into a coherent explanation, and following complex investigation logic. That is exactly where the capability gap between model tiers is most visible.

A useful architectural principle that emerged from this testing: **tools should be verbs, not workflows**. When a model struggles with multi-step chaining, the temptation is to encode the iteration in code (e.g. a `get_all_deployments` tool that loops over resource groups internally). This works, but it removes adaptability — the agent can only follow paths you explicitly anticipated. The value of a capable model like GPT-4o (and now GPT-4.1) is that it can reason through novel scenarios without every path being pre-scripted.

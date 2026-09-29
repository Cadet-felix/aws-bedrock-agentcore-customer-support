"""
Customer Support AI Agent — Starter Code
==========================================
Your task is to complete this file by implementing all sections marked
with # TODO comments.

Reference the step-by-step solution files and INSTRUCTIONS.md for guidance.
Do NOT copy the solution directly — work through each section yourself.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser
from playwright.async_api import Page as _PlaywrightPage
import sys

# 1. Fix Python 3.14 + nest_asyncio event loop teardown error
if sys.version_info >= (3, 14):
    _orig_shutdown = asyncio.base_events.BaseEventLoop.shutdown_default_executor

    async def _safe_shutdown_default_executor(self, timeout=None):
        try:
            await _orig_shutdown(self, timeout)
        except RuntimeError:
            self._executor_shutdown_called = True
            if self._default_executor is not None:
                self._default_executor.shutdown(wait=False)
                self._default_executor = None

    asyncio.base_events.BaseEventLoop.shutdown_default_executor = _safe_shutdown_default_executor

# 2. Make AgentCoreBrowser navigate return on 'domcontentloaded' so heavy sites like amazon.com don't time out
_orig_page_goto = _PlaywrightPage.goto

async def _fast_page_goto(self, url, *args, **kwargs):
    if kwargs.get("wait_until") is None:
        kwargs["wait_until"] = "domcontentloaded"
    return await _orig_page_goto(self, url, *args, **kwargs)

_PlaywrightPage.goto = _fast_page_goto

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

# ── TODO 1 — App Initialisation ───────────────────────────────────────────────
# Create a BedrockAgentCoreApp instance.
# This registers the ASGI server for AgentCore deployment.
# There must be exactly one instance per deployment.
#
# Hint: app = BedrockAgentCoreApp()

# TODO: Create the BedrockAgentCoreApp instance
app = BedrockAgentCoreApp()  # Replace this line


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"


# ── TODO 2 — Configuration ────────────────────────────────────────────────────
# Replace the placeholder strings with your actual AWS resource values.
# You collected these in Part 1 of the INSTRUCTIONS.
#
# GATEWAY_URL format: https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
# KB_ID       format: 10-character alphanumeric string from the KB console
# REGION:     your AWS region, e.g. "us-east-1"
# MEMORY_ID   format: shown in the AgentCore Memory console

GATEWAY_URL = "https://customersupportgateway-q0fpdckxqv.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"   # TODO: Replace with your Gateway URL
KB_ID       = "DNQ0LMTLCF"          # TODO: Replace with your Knowledge Base ID
REGION      = "us-east-1"        # TODO: Replace with your AWS region
MEMORY_ID   = "CustomerSupportMemory-DB1PUR74Zh"        # TODO: Replace with your Memory ID


# ── TODO 3 — Model and Clients ────────────────────────────────────────────────
# Create:
#   1. A BedrockModel using model_id "global.amazon.nova-2-lite-v1:0"
#   2. A MemoryClient with region_name=REGION
#   3. A boto3 client for the "bedrock-agent-runtime" service in REGION
#
# Hint: model = BedrockModel(model_id=model_id)

model_id = "global.amazon.nova-2-lite-v1:0"

# TODO: Create the BedrockModel instance
model = BedrockModel(model_id=model_id)  # Replace this line

# TODO: Create the MemoryClient instance
memory_client = MemoryClient(region_name=REGION)  # Replace this line

# TODO: Create the boto3 bedrock-agent-runtime client
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)  # Replace this line


# ── TODO 4 — Namespace Helper ─────────────────────────────────────────────────
# Implement get_namespaces() to return a dict mapping strategy type to
# namespace template string.
#
# Steps:
#   1. Call mem_client.get_memory_strategies(memory_id) to get strategy list
#   2. Return a dict: { strategy["type"]: strategy["namespaces"][0] for each strategy }
#
# Example output:
#   { "SEMANTIC": "cs_agent/{actorId}/facts",
#     "USER_PREFERENCE": "cs_agent/{actorId}/preferences" }

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    # TODO: Implement this function
    strategies = mem_client.get_memory_strategies(memory_id)
    return {
        s["type"]: (s.get("namespaceTemplates") or s.get("namespaces"))[0]
        for s in strategies
    }


# ── TODO 5 — Memory Hook ──────────────────────────────────────────────────────
# Implement MemoryHook, a HookProvider subclass that adds long-term memory.
#
# The class needs:
#   __init__(self, actor_id, session_id, memory_client, memory_id)
#     — store all four as instance attributes
#     — call get_namespaces() and store the result as self.namespaces
#
#   retrieve_customer_context(self, event: MessageAddedEvent)
#     — only runs for plain-text user messages (not tool results)
#     — for each strategy namespace, call memory_client.retrieve_memories(
#          memory_id, namespace (formatted with actorId), query, top_k=5)
#     — collect non-empty memory texts tagged with their strategy type
#     — if any memories found, prepend them to the user message as:
#          "Customer Context:\n<memories>\n\n<original_message>"
#
#   save_support_interaction(self, event: AfterInvocationEvent)
#     — walk the message list backwards to find the last plain-text user
#       query and the last assistant response
#     — call memory_client.create_event(memory_id, actor_id, session_id,
#          messages=[(customer_query, "USER"), (agent_response, "ASSISTANT")])
#
#   register_hooks(self, registry: HookRegistry)
#     — register retrieve_customer_context on MessageAddedEvent
#     — register save_support_interaction on AfterInvocationEvent

class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        # TODO: Store actor_id, session_id, memory_id, memory_client as attributes
        # TODO: Call get_namespaces() and store the result as self.namespaces
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(self.memory_client, self.memory_id)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        # TODO: Implement memory retrieval
        # Steps:
        #   1. Get the last message from event.agent.messages
        #   2. Check it is a user message and not a tool result
        #   3. Extract the user query text
        #   4. For each namespace in self.namespaces, call retrieve_memories()
        #   5. Collect non-empty memory texts with strategy type tags
        #   6. If any found, prepend them to the user message
        messages = event.agent.messages
        if not messages:
            return

        last_msg = messages[-1]
        if (
            last_msg.get("role") != "user"
            or not last_msg.get("content")
            or "toolResult" in last_msg["content"][0]
        ):
            return

        user_query = last_msg["content"][0].get("text", "")
        if not user_query:
            return

        retrieved_context = []
        for strategy_type, ns_template in self.namespaces.items():
            namespace = ns_template.format(actorId=self.actor_id)
            try:
                memories = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=namespace,
                    query=user_query,
                    top_k=5,
                )
                for mem in memories:
                    content = mem.get("content", {})
                    text = (
                        content.get("text", "").strip()
                        if isinstance(content, dict)
                        else str(mem.get("text", "")).strip()
                    )
                    if text:
                        retrieved_context.append(f"[{strategy_type}] {text}")
            except Exception as e:
                logger.warning(f"Memory retrieval failed for {namespace}: {e}")

        if retrieved_context:
            memories_block = "\n".join(retrieved_context)
            last_msg["content"][0]["text"] = (
                f"Customer Context:\n{memories_block}\n\n{user_query}"
            )
    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        # TODO: Implement memory saving
        # Steps:
        #   1. Get messages from event.agent.messages
        #   2. Walk backwards to find the last user query (plain text)
        #      and the last assistant response
        #   3. Call memory_client.create_event() with both messages
        messages = event.agent.messages
        if not messages:
            return

        customer_query = None
        agent_response = None

        for msg in reversed(messages):
            role = msg.get("role")
            content_list = msg.get("content", [])
            if not content_list:
                continue

            first_block = content_list[0]
            if role == "assistant" and agent_response is None and "text" in first_block:
                agent_response = first_block["text"]
            elif (
                role == "user"
                and customer_query is None
                and "text" in first_block
                and "toolResult" not in first_block
            ):
                raw_text = first_block["text"]
                if raw_text.startswith("Customer Context:\n") and "\n\n" in raw_text:
                    customer_query = raw_text.split("\n\n", 1)[1]
                else:
                    customer_query = raw_text

            if customer_query and agent_response:
                break

        if customer_query and agent_response:
            try:
                self.memory_client.create_event(
                    memory_id=self.memory_id,
                    actor_id=self.actor_id,
                    session_id=self.session_id,
                    messages=[
                        (customer_query, "USER"),
                        (agent_response, "ASSISTANT"),
                    ],
                )
            except Exception as e:
                logger.warning(f"Failed to save interaction to memory: {e}")

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        # TODO: Register retrieve_customer_context on MessageAddedEvent
        # TODO: Register save_support_interaction on AfterInvocationEvent
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)

# ── TODO 6 — Knowledge Base Tool ─────────────────────────────────────────────
# Implement search_knowledge_base(query) using the @tool decorator.
#
# Steps:
#   1. Guard: if KB_ID is empty return "Knowledge base not configured."
#   2. Call _bedrock_runtime.retrieve(
#          knowledgeBaseId=KB_ID,
#          retrievalQuery={"text": query}
#      )
#   3. Extract resp["retrievalResults"]; return a message if empty
#   4. Join the text chunks with "\n---\n" and return the result
#
# The docstring is the tool description — the model uses it to decide when
# to call this tool, so keep it clear and accurate.

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    # TODO: Implement the Knowledge Base search
    if not KB_ID or KB_ID.startswith("<"):
        return "Knowledge base not configured."

    resp = _bedrock_runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
    )
    results = resp.get("retrievalResults", [])
    if not results:
        return "No relevant information found in the knowledge base."

    chunks = [
        r.get("content", {}).get("text", "")
        for r in results
        if r.get("content", {}).get("text")
    ]
    return "\n---\n".join(chunks) if chunks else "No relevant information found in the knowledge base."


# ── TODO 7 — Loyalty Discount Tool (Code Interpreter) ────────────────────────
# Implement calculate_loyalty_discount() using the @tool decorator.
#
# The tool must:
#   1. Build a self-contained Python code string that:
#        • Defines earn_rates: {"standard": 1, "device": 2, "fresh": 5}
#        • Defines tier_rates: {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
#        • Calculates points_redeemed (floor to nearest 500, cap at 50% of order)
#        • Calculates tier_discount (applied to subtotal after points)
#        • Calculates final_total, total_savings, points_earned, remaining_points
#        • Prints a JSON result dict
#   2. Execute the code with code_session(REGION).invoke("executeCode", {...})
#      using language="python" and clearContext=True
#   3. Return the first result event as a JSON string
#   4. Include a fallback that computes only the tier discount if the
#      Code Interpreter is unavailable

@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    # TODO: Build the code string (use an f-string to inject the arguments)
    code = f"""
import json

loyalty_points = {loyalty_points}
tier = {tier!r}
order_total = {order_total}
product_category = {product_category!r}

earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

max_points_cap = int(order_total * 0.50 * 100)
usable_points = min(loyalty_points, max_points_cap)
points_redeemed = (usable_points // 500) * 500 if usable_points >= 500 else 0
points_discount = round(points_redeemed / 100.0, 2)

subtotal = round(order_total - points_discount, 2)
tier_rate = tier_rates.get(tier.capitalize(), 0.00)
tier_discount = round(subtotal * tier_rate, 2)
final_total = round(subtotal - tier_discount, 2)
total_savings = round(points_discount + tier_discount, 2)

earn_rate = earn_rates.get(product_category.lower(), 1)
points_earned = int(final_total * earn_rate)
remaining_points = loyalty_points - points_redeemed + points_earned

result = {{
    "order_total": order_total,
    "tier": tier,
    "tier_discount_pct": f"{{int(tier_rate * 100)}}%",
    "tier_discount": tier_discount,
    "points_redeemed": points_redeemed,
    "points_discount": points_discount,
    "total_savings": total_savings,
    "final_total": final_total,
    "points_earned": points_earned,
    "remaining_points": remaining_points,
}}
print(json.dumps(result))
"""  # Replace with your code string

    try:
        # TODO: Execute the code using code_session and return the result
        with code_session(REGION) as client:
            response = client.invoke(
                "executeCode",
                {
                    "code": code,
                    "language": "python",
                    "clearContext": True,
                },
            )
        for event in response["stream"]:
            res = event.get("result", event)
            if isinstance(res, dict):
                if res.get("isError"):
                    raise RuntimeError(f"Code Interpreter error: {res}")
                if "content" in res and res["content"]:
                    content = res["content"]
                    text_out = (
                        "".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in content
                        ).strip()
                        if isinstance(content, list)
                        else str(content).strip()
                    )
                    return json.dumps(json.loads(text_out))
            elif isinstance(res, str):
                return json.dumps(json.loads(res.strip()))
            return json.dumps(res)

    except Exception as e:
        # TODO: Implement fallback calculation using tier discount only
        logger.warning(f"Code Interpreter unavailable, using fallback: {e}")
        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_rate = tier_rates.get(tier.capitalize(), 0.00)
        tier_discount = round(order_total * tier_rate, 2)
        final_total = round(order_total - tier_discount, 2)
        return json.dumps({
            "order_total": order_total,
            "tier": tier,
            "tier_discount_pct": f"{int(tier_rate * 100)}%",
            "tier_discount": tier_discount,
            "points_redeemed": 0,
            "points_discount": 0.0,
            "total_savings": tier_discount,
            "final_total": final_total,
            "remaining_points": loyalty_points,
            "note": "Calculated via tier-only fallback (Code Interpreter unavailable)",
        })

# ── TODO 8 — Agent Entrypoint ─────────────────────────────────────────────────
# Implement the invoke() function decorated with @app.entrypoint.
#
# Steps:
#   1. Extract user_input, actor_id, and session_id from the payload
#      (generate a UUID if session_id is missing)
#   2. Instantiate MemoryHook for this actor/session
#   3. Instantiate AgentCoreBrowser(region=REGION)
#   4. Build the tools list: [search_knowledge_base, calculate_loyalty_discount,
#                              agent_core_browser.browser]
#   5. Connect to the Gateway via MCPClient, load gateway_tools, extend tools list
#   6. Create and invoke the Agent with all tools, hooks, and system_prompt
#   7. Return the text from the first content block of the response
#   8. Handle exceptions gracefully
SYSTEM_PROMPT = """You are an intelligent Customer Support Assistant for an e-commerce store.
You help customers with:
1. Order tracking and customer profile lookups (via Gateway tools).
2. Refund processing, refund status checks, and return labels (via Gateway tools).
3. Product specifications, return policies, warranties, and loyalty program details (via search_knowledge_base).
4. Exact loyalty discount calculations (via calculate_loyalty_discount).
5. Live web page lookups when asked to visit a URL (via the browser tool).

 Always invoke the live Gateway tools for order tracking and refund requests, even if order details appear in Customer Context.

Always invoke the live Gateway tools for order tracking and refund requests, even if order details appear in Customer Context.
When reporting loyalty discounts from calculate_loyalty_discount, always state the exact numbers from the tool JSON (points_redeemed, points_discount, tier_discount, total_savings, final_total, points_earned, remaining_points) without recalculating them yourself.

When using the browser tool:
1. Initialize a session using `init_session` with a lowercase hyphenated `session_name` (e.g., "session-1").
2. Navigate to the requested URL using `navigate`.
3. To get the page title, use `evaluate` with `script="document.title"` (or `get_text` for page content), even if navigation reports a partial timeout.

Always use the appropriate tool to provide accurate, grounded answers, and respect any customer preferences noted in the Customer Context."""

@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; generated if absent
    """
    # TODO: Implement the agent invocation
    try:
        user_input = payload.get("prompt") or payload.get("message", "Hello!")
        actor_id = payload.get("customer_id", "CUST-123")
        session_id = payload.get("session_id") or str(uuid.uuid4())

        hooks = []
        if MEMORY_ID and not MEMORY_ID.startswith("<"):
            memory_hook = MemoryHook(
                actor_id=actor_id,
                session_id=session_id,
                memory_client=memory_client,
                memory_id=MEMORY_ID,
            )
            hooks.append(memory_hook)

        agent_core_browser = AgentCoreBrowser(region=REGION)
        tools = [
            search_knowledge_base,
            calculate_loyalty_discount,
            agent_core_browser.browser,
        ]

        if GATEWAY_URL and not GATEWAY_URL.startswith("<"):
            mcp_client = MCPClient(lambda: streamable_http_client(GATEWAY_URL))
            with mcp_client:
                gateway_tools = mcp_client.list_tools_sync()
                tools.extend(gateway_tools)
                agent = Agent(
                    model=model,
                    tools=tools,
                    hooks=hooks,
                    system_prompt=SYSTEM_PROMPT,
                )
                response = agent(user_input)
                for msg in agent.messages:
                    for block in msg.get("content", []):
                        if "toolUse" in block:
                            tu = block["toolUse"]
                            print(f"\n[MCP tools/call] Tool: {tu.get('name')} | Arguments: {json.dumps(tu.get('input', {}))}", flush=True)
                        elif "toolResult" in block:
                            tr = block["toolResult"]
                            print(f"[MCP tools/call Result] Status: {tr.get('status', 'success')} | Payload: {json.dumps(tr.get('content', []))}\n", flush=True)
        else:
            agent = Agent(
                model=model,
                tools=tools,
                hooks=hooks,
                system_prompt=SYSTEM_PROMPT,
            )
            response = agent(user_input)

        return response.message["content"][0]["text"]

    except Exception as e:
        logger.error(f"Error invoking agent: {e}", exc_info=True)
        return f"Sorry, I encountered an error while processing your request: {str(e)}"


# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()
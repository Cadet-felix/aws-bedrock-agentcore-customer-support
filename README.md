# Production-Grade Customer Support AI Agent with Amazon Bedrock AgentCore

[![AWS Bedrock AgentCore](https://img.shields.io/badge/AWS-Bedrock%20AgentCore-FF9900?logo=amazon-aws)](https://aws.amazon.com/bedrock/)
[![Strands Agents](https://img.shields.io/badge/Framework-Strands%20Agents-00A1C9)](https://strandsagents.com)
[![MCP Protocol](https://img.shields.io/badge/Protocol-MCP%20(Model%20Context%20Protocol)-4B32C3)](https://modelcontextprotocol.io)
[![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

An end-to-end, cloud-native AI Customer Support Agent built on **Amazon Bedrock AgentCore** and the **Strands Agents** framework using **Amazon Nova 2 Lite** (`global.amazon.nova-2-lite-v1:0`).

This agent unifies external microservice tools via the **Model Context Protocol (MCP)** through the AgentCore Gateway, **Retrieval-Augmented Generation (RAG)** with a Bedrock Knowledge Base, **cross-session long-term memory**, **sandboxed Python execution** via the AgentCore Code Interpreter, **live web automation** via Playwright/AgentCore Browser, and **Amazon CloudWatch** observability.

---

## System Architecture

```mermaid
flowchart TB
    User(["Customer / Client CLI"]) -->|"JSON Payload"| Runtime

    subgraph AgentCore ["Amazon Bedrock AgentCore"]
        Runtime["AgentCore Runtime"]
        MemoryHook["MemoryHook"]
        Agent["Strands Agent"]
        Gateway["AgentCore MCP Gateway"]
        Memory["AgentCore Memory"]
        CodeInt["AgentCore Code Interpreter"]
        Browser["AgentCore Browser"]
    end

    subgraph AWSBackend ["AWS Backend & Knowledge Resources"]
        APIGW["API Gateway REST Proxy"] --> OrderLambda["Lambda: order-tracker"]
        RefundLambda["Lambda: refund-processor"]
        KB["Bedrock Knowledge Base"]
        CW["Amazon CloudWatch"]
    end

    Runtime --> MemoryHook
    MemoryHook <--> Memory
    MemoryHook --> Agent

    Agent --> Gateway
    Gateway --> APIGW
    Gateway --> RefundLambda

    Agent --> KB
    Agent --> CodeInt
    Agent --> Browser
    Runtime -.-> CW

Key Capabilities & Engineering Highlights
Unified MCP Tool Routing via AgentCore Gateway

Connects to the AgentCore Gateway over Streamable HTTP (MCPClient) to dynamically discover (tools/list) and invoke (tools/call) backend tools across two distinct integration patterns:

API-Backed Target (order-tracker): Routes REST queries (get_order, get_customer, get_customer_orders) through Amazon API Gateway to an AWS Lambda backend.

Lambda-Backed Target (refund-processor): Directly invokes an AWS Lambda function (initiate_refund, check_refund_status, get_return_label) validated against a strict JSON schema.

Deterministic Loyalty Arithmetic with Resilient Fallback (calculate_loyalty_discount)

Offloads multi-step financial calculations to the AgentCore Code Interpreter sandbox (clearContext=True).

Enforces business rules deterministically: caps redeemable points at 50% of the order total first, floors to 500-point increments, applies sequential tier discounts (Silver: 0%, Gold: 10%, Platinum: 15%), and calculates category earn rates (standard: 1x, device: 2x, fresh: 5x).

Unwraps event["result"]["content"] to return a clean top-level JSON payload (points_redeemed, tier_discount_pct, final_total, remaining_points) and includes an automatic tier-only fallback if the sandbox is unreachable.

Non-Intrusive Cross-Session Memory (MemoryHook)

Implements a custom Strands HookProvider bound to MessageAddedEvent and AfterInvocationEvent:

Pre-Invocation Retrieval: Queries both SEMANTIC facts and USER_PREFERENCE namespaces and prepends relevant context to the user prompt.

Post-Invocation Persistence: Strips injected context prefixes and stores clean (USER, ASSISTANT) turns via memory_client.create_event().

Retrieval-Augmented Generation (search_knowledge_base)

Queries an Amazon Bedrock Knowledge Base backed by S3 (product_catalog.txt), Amazon Titan Embeddings v2, and OpenSearch Serverless to answer product specification, return policy, warranty, and loyalty tier questions.

Live Web Navigation & Runtime Compatibility (AgentCoreBrowser)

Uses AgentCoreBrowser to initialize headless browser sessions, navigate to live URLs (such as https://www.amazon.com), and extract DOM properties (document.title).

Includes lightweight runtime patches for Python 3.14 asyncio default executor teardown and Playwright wait_until="domcontentloaded" navigation so heavy e-commerce pages resolve without timing out on background tracking scripts.

Production Observability & Alerting

Streams structured runtime logs and OpenTelemetry/X-Ray traces to Amazon CloudWatch Logs, paired with a custom metric filter (AgentErrorCount on ERROR entries) and a CloudWatch Alarm (CustomerSupport-HighErrorRate) that triggers if errors exceed 5 within a 5-minute period.

Repository Structure
├── main.py                          # Complete AgentCore application, tools, hooks, and runtime patches
├── lambda/
│   ├── order_tracker.py             # API Gateway-backed Lambda for order & customer lookups
│   ├── refund_processor.py          # Direct Lambda target for refund processing & return labels
│   └── lambda_schema                # MCP JSON schema for refund-processor Gateway registration
├── product_catalog.txt              # Source document synced to the Bedrock Knowledge Base
├── gateway_and_loyalty_traces.log   # Full verification log (MCP tools/list, tools/call & loyalty checks)
├── REFLECTION.md                    # Architectural reflection on design decisions & production scaling
├── pyproject.toml                   # Project dependencies managed with uv
└── uv.lock                          # Deterministic dependency lockfile
Sample MCP tools/call & Execution Traces
Full verification logs are available in gateway_and_loyalty_traces.log.

[MCP tools/call] Tool: order-tracker___get_order | Arguments: {"order_id": "ORD-001"}
[MCP tools/call Result] Status: success | Payload: [{"text": "{\"order_id\":\"ORD-001\",\"customer_id\":\"CUST-123\",\"status\":\"SHIPPED\",\"items\":[{\"name\":\"Wireless Headphones Pro\",\"qty\":1,\"price\":89.99}],\"total\":89.99,\"tracking_number\":\"TRK987654321\",\"carrier\":\"UPS\",\"estimated_delivery\":\"2026-10-01\"}"}]

Final Answer:
Your order ORD-001 for the Wireless Headphones Pro has been SHIPPED via UPS with tracking number TRK987654321. The estimated delivery date is October 1, 2026. The order total was $89.99.

[MCP tools/call] Tool: order-tracker___get_order | Arguments: {"order_id": "ORD-001"}
[MCP tools/call Result] Status: success | Payload: [{"text": "{\"order_id\":\"ORD-001\",\"customer_id\":\"CUST-123\",\"status\":\"SHIPPED\",\"items\":[{\"name\":\"Wireless Headphones Pro\",\"qty\":1,\"price\":89.99}],\"total\":89.99,\"tracking_number\":\"TRK987654321\",\"carrier\":\"UPS\",\"estimated_delivery\":\"2026-10-01\"}"}]

Final Answer:
Your order ORD-001 for the Wireless Headphones Pro has been SHIPPED via UPS with tracking number TRK987654321. The estimated delivery date is October 1, 2026. The order total was $89.99.

2. Lambda-Backed Gateway Target (refund-processor___initiate_refund)[MCP tools/call] Tool: refund-processor___initiate_refund | Arguments: {"reason": "defective screen", "order_id": "ORD-002", "amount": 139.99}
[MCP tools/call Result] Status: success | Payload: [{"text": "{\"statusCode\":200,\"body\":\"{\\\"refund_id\\\": \\\"REF-JPCH2WSF\\\", \\\"order_id\\\": \\\"ORD-002\\\", \\\"status\\\": \\\"APPROVED\\\", \\\"amount\\\": 139.99, \\\"message\\\": \\\"Refund approved. Credit appears in 3-5 business days.\\\", \\\"created_at\\\": \\\"2026-09-29T02:35:03.393861\\\"}\"}"}]

{
  "order_total": 12.0,
  "tier": "Gold",
  "tier_discount_pct": "10%",
  "tier_discount": 0.7,
  "points_redeemed": 500,
  "points_discount": 5.0,
  "total_savings": 5.7,
  "final_total": 6.3,
  "points_earned": 6,
  "remaining_points": 3756
}

$150.00 Gold Order with 4,250 Points:
{
  "order_total": 150.0,
  "tier": "Gold",
  "tier_discount_pct": "10%",
  "tier_discount": 11.0,
  "points_redeemed": 4000,
  "points_discount": 40.0,
  "total_savings": 51.0,
  "final_total": 99.0,
  "points_earned": 99,
  "remaining_points": 349
}

Setup & Deployment Instructions
Prerequisites
Python: 3.14+

Package Manager: uv

AWS CLI v2 configured with credentials in us-east-1

Bedrock Model Access: Amazon Nova Lite (global.amazon.nova-2-lite-v1:0) and Amazon Titan Embeddings v2

1. Install Dependencies
git clone [https://github.com/Cadet-felix/aws-bedrock-agentcore-customer-support.git](https://github.com/Cadet-felix/aws-bedrock-agentcore-customer-support.git)
cd aws-bedrock-agentcore-customer-support
uv sync

2. Configure AWS Resource Identifiers
Update the resource constants in main.py (under TODO 2) with your AWS environment values:
GATEWAY_URL = "https://<your-gateway-id>[.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp](https://.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp)"
KB_ID       = "<your-kb-id>"
REGION      = "us-east-1"
MEMORY_ID   = "<your-memory-id>"


3. Deploy to Amazon Bedrock AgentCore Runtime
.venv/bin/agentcore configure
.venv/bin/agentcore deploy4. Run Functional End-to-End Tests

# Test 1: Order Tracking (API Gateway Target)
.venv/bin/agentcore invoke '{"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123", "session_id": "t1"}'

# Test 2: Refund Processing (Lambda Target)
.venv/bin/agentcore invoke '{"prompt": "I want to return my Kindle Paperwhite (ORD-002) due to a defective screen. Please initiate a refund for $139.99.", "customer_id": "CUST-123", "session_id": "t2"}'

# Test 3: Knowledge Base (RAG)
.venv/bin/agentcore invoke '{"prompt": "What are the benefits of the Platinum loyalty tier?", "customer_id": "CUST-123", "session_id": "t3"}'

# Test 4: Cross-Session Long-Term Memory
.venv/bin/agentcore invoke '{"prompt": "Hi, I am Jane. I prefer concise responses.", "customer_id": "CUST-123", "session_id": "s-A"}'
.venv/bin/agentcore invoke '{"prompt": "Do you remember my name and communication preference?", "customer_id": "CUST-123", "session_id": "s-B"}'

# Test 5: Loyalty Discount Calculation (Code Interpreter)
.venv/bin/agentcore invoke '{"prompt": "I am a Gold member with 4250 points. Calculate my discount on a $150 standard order.", "customer_id": "CUST-123", "session_id": "t5"}'

# Test 6: Live Web Browser Tool
.venv/bin/agentcore invoke '{"prompt": "Go to [https://www.amazon.com](https://www.amazon.com) and tell me the page title.", "customer_id": "CUST-123", "session_id": "t6"}'



Author
Felix Okorie

AWS AI & ML Scholar | Future AWS Agent Engineer Nanodegree

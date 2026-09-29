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
    User(["Customer / Client CLI"]) -->|"JSON Payload\n(prompt, customer_id, session_id)"| Runtime

    subgraph AgentCore["Amazon Bedrock AgentCore"]
        Runtime["AgentCore Runtime\n(@app.entrypoint)"]
        MemoryHook["MemoryHook\n(MessageAddedEvent / AfterInvocationEvent)"]
        Agent["Strands Agent\n(Amazon Nova 2 Lite)"]
        Gateway["AgentCore MCP Gateway\n(Streamable HTTP)"]
        Memory[("AgentCore Memory\n• SEMANTIC: cs_agent/{actorId}/facts\n• USER_PREFERENCE: cs_agent/{actorId}/preferences")]
        CodeInt["AgentCore Code Interpreter\n(Sandboxed Python Execution)"]
        Browser["AgentCore Browser\n(Playwright Session)"]
    end

    subgraph AWSBackend["AWS Backend & Knowledge Resources"]
        APIGW["API Gateway REST Proxy\n(/orders, /customers)"] --> OrderLambda["Lambda: order-tracker"]
        RefundLambda["Lambda: refund-processor\n(Direct Invocation)"]
        KB[("Bedrock Knowledge Base\nTitan Embeddings v2 + OpenSearch Serverless")]
        CW["Amazon CloudWatch\nLogs, X-Ray Traces & Error Alarms"]
    end

    Runtime --> MemoryHook
    MemoryHook <-->|"Retrieve & Persist Context"| Memory
    MemoryHook --> Agent

    Agent -->|"MCP tools/list & tools/call"| Gateway
    Gateway -->|"API Target (TDGZNUZJEP)"| APIGW
    Gateway -->|"Lambda Target (WJ8LALJ9XQ)"| RefundLambda

    Agent -->|"@tool search_knowledge_base"| KB
    Agent -->|"@tool calculate_loyalty_discount"| CodeInt
    Agent -->|"agent_core_browser.browser"| Browser
    Runtime -.->|"Telemetry & ERROR Metric Filter"| CW
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
[MCP tools/call] Tool: order-tracker___get_order | Arguments: {"order_id": "ORD-001"}
[MCP tools/call Result] Status: success | Payload: [{"text": "{\"order_id\":\"ORD-001\",\"customer_id\":\"CUST-123\",\"status\":\"SHIPPED\",\"items\":[{\"name\":\"Wireless Headphones Pro\",\"qty\":1,\"price\":89.99}],\"total\":89.99,\"tracking_number\":\"TRK987654321\",\"carrier\":\"UPS\",\"estimated_delivery\":\"2026-10-01\"}"}]

Final Answer:
Your order ORD-001 for the Wireless Headphones Pro has been SHIPPED via UPS with tracking number TRK987654321. The estimated delivery date is October 1, 2026. The order total was $89.99.[MCP tools/call] Tool: refund-processor___initiate_refund | Arguments: {"reason": "defective screen", "order_id": "ORD-002", "amount": 139.99}
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
.venv/bin/agentcore deploy

4. Run Functional End-to-End Tests

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

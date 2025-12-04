# Example Test Graphs

This directory contains example behavioral test graphs demonstrating various features of the platform.

## Basic Graph

```yaml
# basic-test.yaml
id: basic-test
name: Basic Agent Test

nodes:
  - id: greeter
    type: mock
    config:
      response: "Hello, how can I help?"

  - id: responder
    type: mock
    inputs: [greeter]

edges:
  - from: greeter
    to: responder

assertions:
  - id: greeting-present
    type: contains
    target: greeter
    field: response
    expected: "Hello"
```

## Multi-Agent Negotiation

```yaml
# negotiation-test.yaml
id: negotiation-test
name: Price Negotiation Test

nodes:
  - id: buyer-agent
    type: negotiator
    config:
      provider: openai
      model: gpt-4o-mini
      system_prompt: "You are a buyer. Negotiate the best price."
      max_price: 100

  - id: seller-agent
    type: negotiator
    config:
      provider: anthropic
      model: claude-3-haiku-20240307
      system_prompt: "You are a seller. Maximize profit."
      min_price: 50
    inputs: [buyer-agent]

  - id: deal-validator
    type: validator
    inputs: [buyer-agent, seller-agent]

edges:
  - from: buyer-agent
    to: seller-agent
  - from: seller-agent
    to: deal-validator
  - from: buyer-agent
    to: deal-validator

contracts:
  - id: buyer-output
    source: buyer-agent
    required_fields: [offer, reasoning]
    types:
      offer: number
    constraints:
      offer:
        min: 0
        max: 100

  - id: seller-output
    source: seller-agent
    required_fields: [counter_offer, accepted]
    types:
      counter_offer: number
      accepted: boolean

assertions:
  - id: deal-reached
    type: equals
    target: deal-validator
    field: deal_made
    expected: true

  - id: price-in-range
    type: range
    target: deal-validator
    field: final_price
    expected:
      min: 50
      max: 100

  - id: negotiation-converges
    type: convergence
    target: deal-validator
    field: price_history
    expected:
      rounds: 5
      threshold: 5
```

## RAG Pipeline Test

```yaml
# rag-test.yaml
id: rag-pipeline
name: RAG Pipeline Quality Test

nodes:
  - id: retriever
    type: retriever
    config:
      provider: mock
      top_k: 5
      
  - id: reranker
    type: reranker
    config:
      model: cross-encoder
    inputs: [retriever]
    
  - id: generator
    type: generator
    config:
      provider: openai
      model: gpt-4o
      temperature: 0.1
    inputs: [reranker]

edges:
  - from: retriever
    to: reranker
  - from: reranker
    to: generator

contracts:
  - id: retriever-contract
    source: retriever
    required_fields: [documents, scores]
    types:
      documents: array
      scores: array
    constraints:
      documents:
        min_length: 1
        max_length: 10

  - id: reranker-contract
    source: reranker
    required_fields: [reranked_docs, relevance_scores]
    
assertions:
  - id: docs-retrieved
    type: greater_than
    target: retriever
    field: doc_count
    expected: 0

  - id: reranking-improves
    type: greater_than
    target: reranker
    field: top_relevance
    expected: 0.7

  - id: answer-grounded
    type: semantic_similarity
    target: generator
    field: answer
    expected: "answer based on retrieved context"
    config:
      threshold: 0.6

  - id: latency-acceptable
    type: latency_under
    target: generator
    expected: 3000

  - id: cost-reasonable
    type: cost_under
    target: generator
    expected: 0.05
```

## Tool-Calling Agent

```yaml
# tool-agent-test.yaml
id: tool-agent
name: Tool-Calling Agent Test

nodes:
  - id: planner
    type: planner
    config:
      provider: openai
      model: gpt-4o
      tools:
        - name: search
          description: Search the web
        - name: calculate
          description: Perform calculations
        - name: lookup
          description: Look up information

  - id: executor
    type: executor
    inputs: [planner]
    config:
      max_iterations: 5
      
  - id: synthesizer
    type: synthesizer
    inputs: [executor]

edges:
  - from: planner
    to: executor
  - from: executor
    to: synthesizer

contracts:
  - id: planner-output
    source: planner
    required_fields: [plan, tool_calls]
    schema:
      type: object
      properties:
        plan:
          type: string
        tool_calls:
          type: array
          items:
            type: object
            properties:
              tool: { type: string }
              args: { type: object }
            required: [tool, args]

assertions:
  - id: plan-valid
    type: schema_valid
    target: planner
    field: output
    expected:
      type: object
      required: [plan, tool_calls]

  - id: tools-executed
    type: greater_than
    target: executor
    field: tools_executed
    expected: 0

  - id: no-hallucination
    type: not_contains
    target: synthesizer
    field: answer
    expected: "I don't know"
```

## Chaos Testing

```yaml
# chaos-test.yaml
id: chaos-resilience
name: Agent Resilience Under Chaos

nodes:
  - id: primary-agent
    type: responder
    config:
      provider: openai
      model: gpt-4o-mini

  - id: fallback-agent
    type: responder
    config:
      provider: anthropic
      model: claude-3-haiku-20240307
    inputs: [primary-agent]

  - id: aggregator
    type: aggregator
    inputs: [primary-agent, fallback-agent]

edges:
  - from: primary-agent
    to: fallback-agent
  - from: primary-agent
    to: aggregator
  - from: fallback-agent
    to: aggregator

# Enable chaos mode in execution config
execution_config:
  mode: chaos
  chaos_config:
    drop_rate: 0.2
    corrupt_rate: 0.1
    latency_injection:
      enabled: true
      max_delay_ms: 2000

assertions:
  - id: system-recovers
    type: equals
    target: aggregator
    field: has_valid_response
    expected: true

  - id: fallback-triggered
    type: greater_than
    target: fallback-agent
    field: activation_count
    expected: 0
```

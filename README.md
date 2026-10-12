# PII gate demo (strands-decider)

A chat app where every message is first scored by a local
[strands-decider](https://huggingface.co/StrandsAgents/strands-decider-2B-hobson-v19) model.
If the PII probability is at or above the threshold, the message is blocked and never reaches
the Bedrock LLM. Otherwise it is sent to a Strands agent (Claude Haiku 4.5 on Bedrock).

```
message ──► Strands Agent
              │ DeciderGate hook (BeforeInvocationEvent)
              │   POST /v1/systemone ──► strands-decider (noul: P(has PII))
              ▼
       score ≥ threshold? ── yes ──► event.cancel → blocked reply (Bedrock not called)
              │ no
              ▼
          Bedrock LLM ──► reply
```

The gate is a Strands hook (`DeciderGate` in `agent/decider_gate.py`) on
`BeforeInvocationEvent`, so it runs inside the agent before every model call. When the
score reaches the threshold it sets `event.cancel`: the user gets the block message,
Bedrock is never called, and the blocked message is not added to the agent's history.
If the decider is unreachable the hook fails closed. To add the gate to another Strands
agent, pass `hooks=[DeciderGate(DeciderClient())]` to `Agent(...)`.

The demo sends the UI's threshold and decider question to the hook through
`invocation_state["decider"]`, and the hook writes the score, breakdown and timings back
into the same dict for the frontend.

## Routing with `choice` questions

The same decider request also asks two `choice` questions (`agent/router.py`):

- **team**: billing / support / sales / general. Picks the specialist system prompt.
- **complexity**: simple / complex. Simple requests go to Haiku 4.5, complex ones to
  Sonnet 5.5.

A team pick whose confidence is below the **route confidence floor** (default 0.3,
adjustable in the UI) falls back to the general agent. There is one agent, and only its
system prompt and model change per turn, so the conversation history is shared across
specialists. The endpoint passes the PII verdict from the batched call to the hook as
`invocation_state["decider"]["precomputed"]`, so the decider is asked once per message;
used on its own, the hook calls the decider itself.

## The PII questions

Each request asks the decider 7 yes/no (`noul`) questions over the same message in one call:
the main `has_pii` question, which decides the block, plus one per PII type (name, email,
phone, address, government ID, payment card) to explain the verdict. The decider shares one
forward pass over the message across all of them.

## Run

1. Start the decider (from the `../decider` project, where `strands-decider` is installed):

   ```sh
   strands-decider serve StrandsAgents/strands-decider-2B-hobson-v19 --port 9000
   ```

2. Put AWS credentials in `.env` (or use your normal AWS credential chain):

   ```
   aws_access_key_id=...
   aws_secret_access_key=...
   ```

3. Start the app and open http://127.0.0.1:8000

   ```sh
   uv run main.py
   ```

   To demo without Bedrock, run `MOCK_LLM=1 uv run main.py`.

## Configuration (env vars)

| Var | Default |
|---|---|
| `DECIDER_URL` | `http://localhost:9000` |
| `AWS_REGION` | `ap-south-1` |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` (before the first route) |
| `SIMPLE_MODEL_ID` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `COMPLEX_MODEL_ID` | `global.anthropic.claude-sonnet-5-5` |
| `MOCK_LLM` | off |

## What the UI shows

- **Per message:** the PII score as a gauge with the threshold marked, the verdict, a per-type
  breakdown (opens automatically when a message is blocked), and decider / LLM latency.
- **Score history** bar chart. Drag the threshold slider to see which past messages a
  stricter or looser gate would have blocked.
- **Editable decider question.** Change what counts as sensitive without touching code.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/chat` | `{message, threshold, instructions?, route_floor?}` → score, categories, route, blocked, reply, timings |
| POST | `/api/reset` | clears the agent's conversation history |
| GET | `/api/defaults` | default question and threshold, mock mode flag |
| GET | `/api/health` | decider status (proxied from its `/health`) |

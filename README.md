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
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `MOCK_LLM` | off |

## What the UI shows

- **Per message:** the PII score as a gauge with the threshold marked, the verdict, a per-type
  breakdown (opens automatically when a message is blocked), and decider / LLM latency.
- **Live PII score** above the input while you type. It calls `/api/score`, which never
  touches the LLM.
- **Score history** bar chart. Drag the threshold slider to see which past messages a
  stricter or looser gate would have blocked.
- **Editable decider question.** Change what counts as sensitive without touching code.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/chat` | `{message, threshold, instructions?}` → score, categories, blocked, reply, timings |
| POST | `/api/score` | `{message, instructions?}` → score and categories only |
| POST | `/api/reset` | clears the agent's conversation history |
| GET | `/api/defaults` | default question and threshold, mock mode flag |
| GET | `/api/health` | decider status (proxied from its `/health`) |

# Open Studio Chat

Persistent local ChatGPT-style sessions backed by the shared LLM bridge.

## API

- `GET /api/chat/health`
- `GET /api/chat/models`
- `GET|PUT /api/chat/preferences` — persisted favorite model for new sessions
- `GET /api/chat/pending-jobs` — Chat history waiting for Job Hub sync
- `GET|POST /api/chat/sessions`
- `GET|PATCH|DELETE /api/chat/sessions/{id}`
- `GET /api/chat/sessions/{id}/messages`
- `POST /api/chat/sessions/{id}/messages`
- `DELETE /api/chat/sessions/{id}/messages/{message_id}`

Messages are stored in `data/state/chat.db`. Completed exchanges are also queued
as Chat history jobs in Job Hub (disable with `CHAT_RECORD_JOBS=0`). The service
calls the LLM bridge at `LLM_URL` (`http://llm:8000` by default); it does not
download a separate model.
When the bridge or Ollama model is unavailable, endpoints return a clear 503.

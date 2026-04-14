# Vapi API Notes

Source: https://docs.vapi.ai  
Confirmed: Apr 2026

---

## Auth

All requests use:
```
Authorization: Bearer <VAPI_API_KEY>
Content-Type: application/json
```

Base URL: `https://api.vapi.ai`

---

## POST /assistant — Create assistant

**Minimum required body:**
```json
{
  "name": "string",
  "model": {
    "provider": "openai",
    "model": "gpt-4o",
    "systemPrompt": "string"
  }
}
```

**Optional fields used in this project:**
- `firstMessage` — assistant greeting
- `analysisPlan` — structured post-call extraction
- `voice` — TTS config (not used in chat loop; kept fixed)
- `transcriber` — STT config (not used in chat loop)

**Response:** Full assistant object; capture `id` as `assistant_id`.

**Update:** `PATCH /assistant/{id}` with same body shape; only send fields to change.

---

## POST /chat — Create chat turn

**Turn model: sequential POST per turn using `previousChatId`**

Each POST creates one user-turn + one assistant-turn. The response contains the full `output` from the assistant for that turn.

**Request:**
```json
{
  "assistantId": "string",
  "input": "user message string",
  "previousChatId": "string (omit for first turn)"
}
```

**Optional override per turn:**
```json
{
  "assistantOverrides": {
    "variableValues": {}
  }
}
```

**Response:**
```json
{
  "id": "chat_abc123",            // use as previousChatId for next turn
  "assistantId": "...",
  "messages": [                   // full history for this session
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "output": [                     // assistant reply for THIS turn only
    {"role": "assistant", "content": "..."}
  ],
  "createdAt": "...",
  "updatedAt": "..."
}
```

**Key fields for harness:**
- `response.id` → pass as `previousChatId` on next turn
- `response.output[0].content` → assistant reply text for this turn
- `response.messages` → full conversation history at end

**Limitations noted in docs:**
- Server webhook events (status updates, end-of-call reports) are NOT supported on chat
- No audio/voice processing in chat mode

---

## POST /call — Create call (voice; VOICE_ENABLED=false for this project)

**Request:**
```json
{
  "assistantId": "string",
  "phoneNumberId": "string",
  "customer": {
    "number": "+1XXXXXXXXXX"
  }
}
```

**Response:** call object with `id`.

---

## GET /call/{id} — Get call details

**Response includes (when call completes):**
- `artifact.transcript` — full transcript string
- `artifact.messages` — structured turn list
- `artifact.recordingUrl` — audio URL

**Terminal call states:** `ended`, `failed` (poll until one of these).

---

## analysisPlan

Attach to assistant config to get structured extraction per call/chat (availability in chat TBD — validate in spike).

```json
{
  "analysisPlan": {
    "structuredDataSchema": {
      "type": "object",
      "properties": {
        "appointment_booked": {"type": "boolean"},
        "patient_name": {"type": "string"},
        "appointment_date": {"type": "string"},
        "procedure": {"type": "string"},
        "contact_info": {"type": "string"}
      }
    }
  }
}
```

---

## OpenRouter

Base URL: `https://openrouter.ai/api/v1`  
Compatible with OpenAI client SDK (`openai` Python package pointing at OpenRouter base URL).

**Auth:** `Authorization: Bearer <OPENROUTER_API_KEY>` (same as OpenAI pattern)

**JSON output:** Use `response_format={"type": "json_object"}` or prompt engineering with explicit JSON schema in system message.

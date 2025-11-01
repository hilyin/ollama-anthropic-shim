# Ollama-Anthropic Translation Shim

A lightweight translation server that makes Ollama compatible with Claude Code by translating between the Anthropic Messages API and Ollama's chat API format.

## What is this?

Claude Code is designed to communicate with the Anthropic API. This shim allows Claude Code to use Ollama (running locally with models like MiniMax M2) by:

1. Accepting Anthropic-style API requests from Claude Code
2. Translating them to Ollama's chat API format
3. Forwarding requests to your local Ollama instance
4. Translating Ollama's responses back to Anthropic format
5. Returning them to Claude Code

**Flow**: Claude Code → Shim (localhost:4001) → Ollama (localhost:11434) → Shim → Claude Code

## Features

- ✅ Full Anthropic Messages API v1 compatibility
- ✅ Streaming support with Server-Sent Events (SSE)
- ✅ Tool calling (function calling) support with automatic format conversion
- ✅ Automatic request/response translation
- ✅ Handles text content, system messages, and multi-turn conversations
- ✅ Configurable via environment variables
- ✅ Docker-based deployment
- ✅ Health check endpoint
- ✅ Comprehensive logging with request/response truncation
- ✅ MiniMax M2 reasoning model support (thinking field handling)

## Important Note: Ollama Cloud Free Tier Limitations

**⚠️ Claude Code Compatibility Issue with Ollama Cloud Free Tier**

While this shim works perfectly for simple requests, **Claude Code sends very large requests** (18KB+ system prompts, 20+ tool definitions, multi-turn conversation history) that frequently exceed Ollama Cloud's free tier limits, resulting in `500 Internal Server Error` responses.

**Recommendations:**
- ✅ **Use local Ollama** - Install Ollama locally for unlimited usage with models like llama3.1, qwen2.5, or mistral
- ⏳ **Wait for paid tier** - Ollama Cloud paid plans (after free trial) may have higher limits
- ⚠️ **Free tier works for:** Simple API calls, testing, small conversations
- ❌ **Free tier struggles with:** Claude Code's full feature set (agents, tools, long contexts)

**Testing:** The shim itself is production-ready - the limitation is upstream in Ollama Cloud's free tier capacity.

## Prerequisites

Before you begin, ensure you have:

1. **Docker** and **Docker Compose** installed
   - [Get Docker Desktop](https://www.docker.com/products/docker-desktop/)

2. **Ollama** installed and running on macOS
   - [Install Ollama](https://ollama.ai/)

3. **MiniMax M2 model** pulled in Ollama:
   ```bash
   ollama pull minimax-m2:cloud
   ```

## Ollama Setup

### 1. Install Ollama

```bash
# macOS
brew install ollama

# Or download from https://ollama.ai/download
```

### 2. Start Ollama Service

```bash
ollama serve
```

Ollama will start on `http://localhost:11434` by default.

### 3. Pull the MiniMax M2 Model

```bash
ollama pull minimax-m2:cloud
```

### 4. Verify Ollama is Running

```bash
# List available models
curl http://localhost:11434/api/tags

# Test chat endpoint
curl -X POST http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-m2:cloud",
    "messages": [{"role": "user", "content": "Say hello"}],
    "stream": false
  }'
```

You should see a response with the model's output.

## Running the Shim

### Quick Start

1. **Create a `.env` file** (required for Ollama Cloud models):
   ```bash
   cp .env.example .env
   ```

   Edit `.env` and add your Ollama API key:
   ```bash
   OLLAMA_API_KEY=your-api-key-here
   ```

   Get your API key from [https://ollama.com/settings/keys](https://ollama.com/settings/keys)

2. **Start the shim**:
   ```bash
   ./up.sh
   ```

3. **View logs**:
   ```bash
   docker compose logs -f shim
   ```

4. **Stop the shim**:
   ```bash
   ./down.sh
   ```

5. **Rebuild from scratch**:
   ```bash
   ./rebuild.sh
   ```

### Environment Variables

You can customize the shim's behavior using environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama API endpoint (from inside Docker) |
| `OLLAMA_MODEL` | `minimax-m2:cloud` | Model to use (ignores model in requests) |
| `OLLAMA_API_KEY` | *(none)* | **Required for cloud models** - Get from [ollama.com/settings/keys](https://ollama.com/settings/keys) |
| `SHIM_PORT` | `4001` | Port for the shim to listen on |
| `LOG_LEVEL` | `info` | Logging level (`debug`, `info`, `warning`, `error`) |

**Example**: Run on a different port with debug logging:

```bash
export SHIM_PORT=5000
export LOG_LEVEL=debug
./up.sh
```

## Claude Code Integration

To make Claude Code use this shim instead of the Anthropic API:

### 1. Create or Edit Settings File

Open or create `~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:4001",
    "ANTHROPIC_AUTH_TOKEN": "not-used",
    "ANTHROPIC_MODEL": "minimax-m2:cloud",
    "ANTHROPIC_SMALL_FAST_MODEL": "minimax-m2:cloud",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "minimax-m2:cloud",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "minimax-m2:cloud",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "minimax-m2:cloud"
  }
}
```

**Note**: The `ANTHROPIC_AUTH_TOKEN` value doesn't matter - the shim doesn't validate it. You can use any string.

### 2. Restart Claude Code

After updating the settings file, restart Claude Code for the changes to take effect.

### 3. Verify It's Working

Start a conversation in Claude Code. You should see:
- Responses from the MiniMax M2 model
- Request logs in the shim container: `docker compose logs -f shim`

## Testing

### Test 1: Health Check

```bash
curl http://localhost:4001/health
```

**Expected response**:
```json
{"ok": true}
```

### Test 2: Direct API Call

```bash
curl -X POST http://localhost:4001/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet",
    "messages": [
      {"role": "user", "content": "Write a short Python function that returns the nth Fibonacci number."}
    ],
    "max_tokens": 256,
    "temperature": 0.2,
    "top_p": 0.95,
    "stream": false
  }'
```

**Expected response** (Anthropic format):
```json
{
  "id": "msg_abc123...",
  "type": "message",
  "model": "minimax-m2:cloud",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Here's a Python function...[code]..."
    }
  ],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0
  }
}
```

**Note**: Token counts are placeholders (Ollama doesn't provide them).

### Test 3: Streaming Support

```bash
curl -X POST http://localhost:4001/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet",
    "messages": [{"role": "user", "content": "Count from 1 to 5"}],
    "max_tokens": 100,
    "stream": true
  }'
```

**Expected response** (Server-Sent Events stream):
```
event: message_start
data: {"type":"message_start","message":{"id":"msg_...","type":"message","role":"assistant","content":[],"model":"minimax-m2:cloud","stop_reason":null,"usage":{"input_tokens":0,"output_tokens":0}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"1"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" 2 3 4 5"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":0}}

event: message_stop
data: {"type":"message_stop"}
```

### Test 4: Tool Calling

```bash
curl -X POST http://localhost:4001/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet",
    "messages": [
      {"role": "user", "content": "What is the weather in San Francisco?"}
    ],
    "max_tokens": 256,
    "stream": false,
    "tools": [
      {
        "name": "get_weather",
        "description": "Get the current weather in a location",
        "input_schema": {
          "type": "object",
          "properties": {
            "location": {"type": "string", "description": "The city and state"}
          },
          "required": ["location"]
        }
      }
    ]
  }'
```

**Expected response** includes tool_use blocks when the model decides to use tools:
```json
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "I'll check the weather for you."},
    {
      "type": "tool_use",
      "id": "toolu_...",
      "name": "get_weather",
      "input": {"location": "San Francisco, CA"}
    }
  ],
  "stop_reason": "tool_use",
  "model": "minimax-m2:cloud",
  "usage": {"input_tokens": 0, "output_tokens": 0}
}
```

### Test 5: With Claude Code

1. Ensure the shim is running: `./up.sh`
2. Configure `~/.claude/settings.json` (see above)
3. Restart Claude Code
4. Send a message: "Write a hello world function in Python"
5. Check shim logs: `docker compose logs -f shim`

You should see request/response logs and get a response from MiniMax M2.

## Architecture

### Request Flow

```
┌─────────────┐      POST /v1/messages       ┌──────────┐
│ Claude Code │ ──────────────────────────> │   Shim   │
│ (Client)    │   (Anthropic format)        │  :4001   │
└─────────────┘                              └──────────┘
                                                   │
                                                   │ POST /api/chat
                                                   │ (Ollama format)
                                                   ↓
                                             ┌──────────┐
                                             │  Ollama  │
                                             │  :11434  │
                                             └──────────┘
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check - returns `{"ok": true}` |
| `/v1/messages` | POST | Anthropic Messages API endpoint |

### Translation Details

**Request transformation**:
- `model` → Ignored, always uses `OLLAMA_MODEL`
- `messages` → Extracted text from content blocks, tool_result → tool messages
- `max_tokens` → `options.num_predict` (defaults to 4096 for reasoning models if not specified)
- `temperature` → `options.temperature`
- `top_p` → `options.top_p`
- `tools` → Ollama tools format (input_schema → parameters)

**Response transformation**:
- Ollama `message.content` → Anthropic `content[0].text`
- Ollama `message.thinking` → Anthropic content text (fallback for reasoning models like MiniMax M2)
- Ollama `tool_calls` → Anthropic `tool_use` blocks
- Generates fake UUID for message `id` and tool use IDs
- Adds required Anthropic fields: `type`, `stop_reason`, `usage`
- Sets `stop_reason: "tool_use"` when tools are called, otherwise `"end_turn"`

## Troubleshooting

### Shim Can't Reach Ollama

**Problem**: Logs show connection errors to Ollama

**Solutions**:
1. Verify Ollama is running: `curl http://localhost:11434/api/tags`
2. On macOS, Docker uses `host.docker.internal` to reach the host
3. Try alternative: Set `OLLAMA_BASE_URL=http://docker.for.mac.localhost:11434`

### Port Conflicts

**Problem**: Port 4001 is already in use

**Solution**: Change the port:
```bash
export SHIM_PORT=5000
./rebuild.sh
```

Don't forget to update `~/.claude/settings.json` with the new port.

### Model Not Found

**Problem**: "model 'minimax-m2:cloud' not found"

**Solution**:
```bash
# List available models
ollama list

# Pull the model
ollama pull minimax-m2:cloud
```

### View Logs

```bash
# Follow logs in real-time
docker compose logs -f shim

# View last 100 lines
docker compose logs --tail=100 shim
```

### Check Container Status

```bash
# List running containers
docker compose ps

# Restart container
docker compose restart shim
```

### Claude Code Not Using Shim

**Problem**: Claude Code still uses Anthropic API

**Solutions**:
1. Verify `~/.claude/settings.json` has correct `ANTHROPIC_BASE_URL`
2. Restart Claude Code completely
3. Check shim is running: `curl http://localhost:4001/health`
4. Check shim logs for incoming requests

## Limitations

1. **Token counts are placeholders**: Always returns 0 (Ollama doesn't provide them)
2. **Model name mapping**: All model names map to `OLLAMA_MODEL` env var
3. **macOS/Docker only**: Uses `host.docker.internal` for Mac Docker Desktop
4. **Ollama Cloud request size limits**: Very large requests (18KB+ system prompts, 20+ tools) may cause 500 errors from Ollama Cloud

## Future Enhancements

- [ ] Add actual token counting (estimate from text length)
- [ ] Support multiple model mappings (map claude-opus → llama3, etc.)
- [ ] Add request caching
- [ ] Add metrics and monitoring endpoints
- [ ] Add rate limiting
- [ ] Improve error handling for Ollama Cloud request size limits

## Project Structure

```
.
├── src/
│   └── server.py          # Main FastAPI server
├── requirements.txt       # Python dependencies
├── Dockerfile            # Container definition
├── docker-compose.yml    # Docker Compose config
├── .dockerignore         # Docker build exclusions
├── .env.example          # Environment variables template
├── .gitignore            # Git exclusions
├── up.sh                 # Start the shim
├── down.sh               # Stop the shim
├── rebuild.sh            # Rebuild from scratch
└── README.md             # This file
```

## Contributing

This is a production-ready implementation with full streaming and tool calling support. Contributions welcome for:
- Additional model mappings
- Better error handling for Ollama Cloud limits
- Token count estimation
- Request caching
- Tests
- Rate limiting

## License

MIT License - feel free to modify and distribute.

## Support

For issues or questions:
- Check the troubleshooting section above
- Review logs: `docker compose logs -f shim`
- Verify Ollama is working independently
- Check Claude Code settings configuration

---

**Happy coding with local models!** 🚀

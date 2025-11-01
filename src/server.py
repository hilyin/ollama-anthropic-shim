"""
Ollama-to-Anthropic Translation Shim

This server translates Anthropic Messages API requests to Ollama chat API format,
allowing Claude Code to communicate with Ollama as if it were the Anthropic API.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Union

import httpx
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Environment configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "minimax-m2:cloud")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
SHIM_PORT = int(os.getenv("SHIM_PORT", "4001"))

logger.info(f"Starting Ollama-Anthropic shim server")
logger.info(f"OLLAMA_BASE_URL: {OLLAMA_BASE_URL}")
logger.info(f"OLLAMA_MODEL: {OLLAMA_MODEL}")
logger.info(f"OLLAMA_API_KEY: {'***set***' if OLLAMA_API_KEY else 'not set'}")
logger.info(f"SHIM_PORT: {SHIM_PORT}")

# Constants
class StopReason:
    """Anthropic API stop reasons."""
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"


class ContentBlockType:
    """Anthropic content block types."""
    TEXT = "text"
    TOOL_USE = "tool_use"


class SSEEventType:
    """Server-Sent Events event types."""
    MESSAGE_START = "message_start"
    CONTENT_BLOCK_START = "content_block_start"
    CONTENT_BLOCK_DELTA = "content_block_delta"
    CONTENT_BLOCK_STOP = "content_block_stop"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_STOP = "message_stop"
    ERROR = "error"


# Initialize FastAPI app
app = FastAPI(title="Ollama-Anthropic Shim", version="1.0.0")


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate text to max_length characters."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "...[truncated]"


def extract_text_from_content(content: Union[str, List[Dict[str, Any]]]) -> str:
    """
    Extract text from Anthropic message content.

    Content can be:
    - A string: "Hello, world"
    - An array of blocks: [{"type": "text", "text": "Hello"}]

    We extract only text blocks and ignore tool_use, tool_result, etc.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        return "\n".join(text_parts)

    return ""


def transform_tools_to_ollama(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform Anthropic tools to Ollama format.

    Anthropic format:
    [{
      "name": "get_weather",
      "description": "Get the current weather",
      "input_schema": {
        "type": "object",
        "properties": {...},
        "required": [...]
      }
    }]

    Ollama format:
    [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get the current weather",
        "parameters": {
          "type": "object",
          "properties": {...},
          "required": [...]
        }
      }
    }]
    """
    ollama_tools = []

    for tool in tools:
        ollama_tool = {
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {})
            }
        }
        ollama_tools.append(ollama_tool)

    return ollama_tools


def transform_messages_to_ollama(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform Anthropic messages to Ollama format.

    Anthropic format:
    [{"role": "user", "content": "..." or [{"type": "text", "text": "..."}]}]

    Ollama format:
    [{"role": "user", "content": "..."}]

    Also handles:
    - tool_result blocks (Anthropic) -> tool messages (Ollama)
    - tool_use blocks (Anthropic) -> tool_calls (Ollama)
    """
    ollama_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Handle string content
        if isinstance(content, str):
            if content:
                ollama_messages.append({
                    "role": role,
                    "content": content
                })
            continue

        # Handle array of content blocks
        if isinstance(content, list):
            text_parts = []
            tool_calls = []
            tool_results = []

            for block in content:
                block_type = block.get("type")

                if block_type == "text":
                    text_parts.append(block.get("text", ""))

                elif block_type == "tool_use":
                    # Convert Anthropic tool_use to Ollama tool_calls format
                    tool_calls.append({
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": block.get("input", {})
                        }
                    })

                elif block_type == "tool_result":
                    # Convert Anthropic tool_result to Ollama tool message format
                    tool_content = block.get("content", "")
                    if isinstance(tool_content, list):
                        # Extract text from content blocks
                        tool_content = extract_text_from_content(tool_content)

                    tool_results.append({
                        "role": "tool",
                        "content": str(tool_content)
                    })

            # Build message based on what we found
            if tool_calls and role == "assistant":
                # Assistant message with tool calls
                message = {
                    "role": "assistant",
                    "tool_calls": tool_calls
                }
                if text_parts:
                    message["content"] = "\n".join(text_parts)
                ollama_messages.append(message)

            elif text_parts:
                # Regular text message
                ollama_messages.append({
                    "role": role,
                    "content": "\n".join(text_parts)
                })

            # Add tool results as separate messages
            ollama_messages.extend(tool_results)

    return ollama_messages


def send_sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """
    Generate a Server-Sent Events (SSE) formatted message.

    Args:
        event_type: The event type (e.g., "message_start", "content_block_delta")
        data: The event data to be JSON-encoded

    Returns:
        Formatted SSE message string
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def build_anthropic_response(
    ollama_response: Dict[str, Any],
    model: str
) -> Dict[str, Any]:
    """
    Build Anthropic-style response from Ollama response.

    Ollama response format:
    {
      "message": {"role": "assistant", "content": "...", "tool_calls": [...]},
      "done": true,
      ...
    }

    Anthropic response format:
    {
      "id": "msg_...",
      "type": "message",
      "role": "assistant",
      "content": [{"type": "text", "text": "..."}, {"type": "tool_use", ...}],
      "model": "...",
      "stop_reason": "end_turn" or "tool_use",
      "stop_sequence": null,
      "usage": {"input_tokens": 0, "output_tokens": 0}
    }
    """
    message = ollama_response.get("message", {})
    content_text = message.get("content", "")

    # Some models (like MiniMax M2) put reasoning in "thinking" field
    # If content is empty, try the thinking field
    if not content_text and "thinking" in message:
        content_text = message.get("thinking", "")

    # Generate a fake message ID
    message_id = f"msg_{uuid.uuid4().hex[:24]}"

    # Build content array
    content_blocks = []

    # Add text content if present
    if content_text:
        content_blocks.append({
            "type": "text",
            "text": content_text
        })

    # Convert tool_calls to Anthropic tool_use blocks
    tool_calls = message.get("tool_calls", [])
    for tool_call in tool_calls:
        # Ollama format: {"function": {"name": "...", "arguments": {}}}
        function = tool_call.get("function", {})
        if function:
            tool_use_id = f"toolu_{uuid.uuid4().hex[:24]}"

            content_blocks.append({
                "type": "tool_use",
                "id": tool_use_id,
                "name": function.get("name", ""),
                "input": function.get("arguments", {})
            })

    # Determine stop_reason
    stop_reason = StopReason.TOOL_USE if tool_calls else StopReason.END_TURN

    return {
        "id": message_id,
        "type": "message",
        "model": model,
        "role": "assistant",
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 0,  # Placeholder - Ollama doesn't provide this
            "output_tokens": 0  # Placeholder - Ollama doesn't provide this
        }
    }


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Log all requests and responses with timing."""
    start_time = time.time()

    # Log request
    logger.info(f"{request.method} {request.url.path}")

    # For /v1/messages, log truncated request body
    if request.url.path == "/v1/messages":
        try:
            body = await request.body()
            # Need to recreate request with body since we consumed it
            async def receive():
                return {"type": "http.request", "body": body}

            request = Request(request.scope, receive)

            # Try to parse and log truncated version
            try:
                import json
                body_json = json.loads(body.decode())
                if "messages" in body_json:
                    for msg in body_json["messages"]:
                        if "content" in msg:
                            content = msg["content"]
                            content_str = str(content) if not isinstance(content, str) else content
                            msg["content"] = truncate_text(content_str, 200)
                logger.info(f"Request body: {json.dumps(body_json)}")
            except:
                logger.info(f"Request body: {truncate_text(body.decode(), 200)}")
        except:
            pass

    # Process request
    response = await call_next(request)

    # Calculate latency
    latency_ms = (time.time() - start_time) * 1000

    # Log response
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({latency_ms:.2f}ms)")

    return response


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"ok": True}


async def stream_ollama_response(ollama_request: Dict[str, Any], headers: Dict[str, str]):
    """Stream Ollama response and convert to Anthropic SSE format."""
    import json

    message_id = f"msg_{uuid.uuid4().hex[:24]}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/chat",
            json=ollama_request,
            headers=headers
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                yield send_sse_event(SSEEventType.ERROR, {
                    'type': 'error',
                    'error': {'type': 'upstream_error', 'message': error_text.decode()}
                })
                return

            # Send message_start event
            yield send_sse_event(SSEEventType.MESSAGE_START, {
                'type': 'message_start',
                'message': {
                    'id': message_id,
                    'type': 'message',
                    'role': 'assistant',
                    'content': [],
                    'model': OLLAMA_MODEL,
                    'stop_reason': None,
                    'usage': {'input_tokens': 0, 'output_tokens': 0}
                }
            })

            full_content = ""
            full_thinking = ""
            accumulated_tool_calls = []
            text_block_started = False
            current_block_index = 0

            async for line in response.aiter_lines():
                if not line.strip():
                    continue

                try:
                    chunk = json.loads(line)
                    logger.debug(f"Ollama chunk: {json.dumps(chunk)}")
                    message = chunk.get("message", {})

                    # Get content delta
                    content_delta = message.get("content", "")
                    thinking_delta = message.get("thinking", "")

                    # Accumulate tool_calls (they may arrive before done=true)
                    if "tool_calls" in message:
                        accumulated_tool_calls = message.get("tool_calls", [])

                    # Start text block on first content
                    if (content_delta or thinking_delta) and not text_block_started:
                        yield send_sse_event(SSEEventType.CONTENT_BLOCK_START, {
                            'type': 'content_block_start',
                            'index': current_block_index,
                            'content_block': {'type': ContentBlockType.TEXT, 'text': ''}
                        })
                        text_block_started = True

                    if content_delta:
                        full_content += content_delta
                        # Send content_block_delta
                        yield send_sse_event(SSEEventType.CONTENT_BLOCK_DELTA, {
                            'type': 'content_block_delta',
                            'index': current_block_index,
                            'delta': {'type': 'text_delta', 'text': content_delta}
                        })

                    if thinking_delta:
                        full_thinking += thinking_delta

                    # Check if done
                    if chunk.get("done", False):
                        # If content is empty, use thinking
                        if not full_content and full_thinking:
                            if not text_block_started:
                                yield send_sse_event(SSEEventType.CONTENT_BLOCK_START, {
                                    'type': 'content_block_start',
                                    'index': current_block_index,
                                    'content_block': {'type': ContentBlockType.TEXT, 'text': ''}
                                })
                                text_block_started = True

                            yield send_sse_event(SSEEventType.CONTENT_BLOCK_DELTA, {
                                'type': 'content_block_delta',
                                'index': current_block_index,
                                'delta': {'type': 'text_delta', 'text': full_thinking}
                            })

                        # Close text block if started
                        if text_block_started:
                            yield send_sse_event(SSEEventType.CONTENT_BLOCK_STOP, {
                                'type': 'content_block_stop',
                                'index': current_block_index
                            })
                            current_block_index += 1

                        # Handle tool_calls (use accumulated ones)
                        stop_reason = StopReason.TOOL_USE if accumulated_tool_calls else StopReason.END_TURN

                        for tool_call in accumulated_tool_calls:
                            # Ollama format: {"function": {"name": "...", "arguments": {}}}
                            function = tool_call.get("function", {})
                            if function:
                                tool_use_id = f"toolu_{uuid.uuid4().hex[:24]}"
                                tool_name = function.get('name', '')
                                tool_args = function.get('arguments', {})

                                logger.debug(f"Processing tool_call: name={tool_name}, args_type={type(tool_args)}")

                                # Send content_block_start for tool_use
                                yield send_sse_event(SSEEventType.CONTENT_BLOCK_START, {
                                    'type': 'content_block_start',
                                    'index': current_block_index,
                                    'content_block': {
                                        'type': ContentBlockType.TOOL_USE,
                                        'id': tool_use_id,
                                        'name': tool_name,
                                        'input': {}
                                    }
                                })

                                # Send content_block_delta with tool input
                                # Arguments should be serialized to JSON string
                                args_json = json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args)
                                yield send_sse_event(SSEEventType.CONTENT_BLOCK_DELTA, {
                                    'type': 'content_block_delta',
                                    'index': current_block_index,
                                    'delta': {
                                        'type': 'input_json_delta',
                                        'partial_json': args_json
                                    }
                                })

                                # Send content_block_stop for tool_use
                                yield send_sse_event(SSEEventType.CONTENT_BLOCK_STOP, {
                                    'type': 'content_block_stop',
                                    'index': current_block_index
                                })

                                current_block_index += 1

                        # Send message_delta
                        yield send_sse_event(SSEEventType.MESSAGE_DELTA, {
                            'type': 'message_delta',
                            'delta': {'stop_reason': stop_reason},
                            'usage': {'output_tokens': 0}
                        })

                        # Send message_stop
                        yield send_sse_event(SSEEventType.MESSAGE_STOP, {
                            'type': 'message_stop'
                        })
                        break

                except json.JSONDecodeError:
                    continue


@app.post("/v1/messages")
async def create_message(request: Request):
    """
    Anthropic Messages API endpoint.

    Accepts Anthropic-style requests and translates them to Ollama format.
    """
    try:
        # Parse request body
        body = await request.json()

        # Check if streaming is requested
        is_streaming = body.get("stream", False)

        # Extract parameters
        messages = body.get("messages", [])
        max_tokens = body.get("max_tokens", 4096)  # Higher default for reasoning models
        temperature = body.get("temperature", 0.2)
        top_p = body.get("top_p")
        tools = body.get("tools", [])

        # Transform messages to Ollama format
        ollama_messages = transform_messages_to_ollama(messages)

        # Build Ollama request
        ollama_request = {
            "model": OLLAMA_MODEL,
            "messages": ollama_messages,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
            "stream": is_streaming
        }

        # Add top_p if provided
        if top_p is not None:
            ollama_request["options"]["top_p"] = top_p

        # Add tools if provided
        if tools:
            ollama_tools = transform_tools_to_ollama(tools)
            ollama_request["tools"] = ollama_tools
            logger.info(f"Passing {len(ollama_tools)} tools to Ollama")
            logger.debug(f"First tool: {json.dumps(ollama_tools[0]) if ollama_tools else 'none'}")

        logger.info(f"Calling Ollama at {OLLAMA_BASE_URL}/api/chat with model {OLLAMA_MODEL} (stream={is_streaming})")

        # Build headers
        headers = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

        # Handle streaming
        if is_streaming:
            return StreamingResponse(
                stream_ollama_response(ollama_request, headers),
                media_type="text/event-stream"
            )

        # Call Ollama (non-streaming)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                ollama_response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json=ollama_request,
                    headers=headers
                )

                # Log truncated Ollama response
                response_text = ollama_response.text
                logger.info(f"Ollama response: {truncate_text(response_text, 200)}")

                # Handle non-200 responses from Ollama
                if ollama_response.status_code != 200:
                    error_message = ollama_response.text
                    return JSONResponse(
                        status_code=ollama_response.status_code,
                        content={
                            "error": {
                                "type": "upstream_error",
                                "message": error_message
                            }
                        }
                    )

                # Parse Ollama response
                ollama_data = ollama_response.json()

                # Transform to Anthropic format
                anthropic_response = build_anthropic_response(ollama_data, OLLAMA_MODEL)

                return JSONResponse(content=anthropic_response)

        except httpx.RequestError as e:
            logger.error(f"Error connecting to Ollama: {e}")
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": {
                        "type": "upstream_error",
                        "message": f"Failed to connect to Ollama: {str(e)}"
                    }
                }
            )

    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "type": "internal_error",
                    "message": "unhandled exception"
                }
            }
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SHIM_PORT)

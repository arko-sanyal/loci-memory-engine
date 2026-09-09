import httpx
import ollama

from rag import config


def generate(prompt: str) -> str:
    client = ollama.Client(
        host=config.OLLAMA_HOST, timeout=config.OLLAMA_CONNECT_TIMEOUT_SECONDS
    )
    try:
        response = client.generate(model=config.LLM_MODEL, prompt=prompt)
        return response["response"]
    except (httpx.ConnectError, httpx.ConnectTimeout, ConnectionError) as e:
        raise ConnectionError(
            f"Could not reach Ollama at {config.OLLAMA_HOST}. "
            "Start it with `ollama serve` and make sure "
            f"`{config.LLM_MODEL}` is pulled."
        ) from e

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional


class OllamaUnavailableError(RuntimeError):
    """Raised when Ollama is unavailable."""


@dataclass
class LLMReply:
    text: str
    model: str
    used_fallback: bool = False


class OllamaClient:
    """Small Ollama client with a deterministic local fallback."""

    def __init__(
        self,
        model: str = "deepseek-r1",
        host: str = "http://127.0.0.1:11434",
        timeout: int = 120,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            self._request("GET", "/api/tags")
            return True
        except OllamaUnavailableError:
            return False

    def list_models(self) -> List[str]:
        data = self._request("GET", "/api/tags")
        models = []
        for item in data.get("models", []):
            name = item.get("name")
            if isinstance(name, str) and name:
                models.append(name)
        return models

    def model_available(self, model_name: Optional[str] = None) -> bool:
        target = model_name or self.model
        try:
            return target in self.list_models()
        except OllamaUnavailableError:
            return False

    def generate(self, system_prompt: str, prompt: str) -> LLMReply:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
        data = self._request("POST", "/api/generate", payload)
        response_text = str(data.get("response", "")).strip()
        if not response_text:
            raise OllamaUnavailableError("Ollama returned an empty response.")
        return LLMReply(text=response_text, model=self.model, used_fallback=False)

    def answer_question(
        self,
        question: str,
        memory_context: str,
        file_context: str,
    ) -> LLMReply:
        system_prompt = (
            "You are DeepSleep, a local coding copilot. Answer concisely, stay practical, "
            "use the provided project memory, and suggest file-specific next steps when relevant."
        )
        prompt = (
            f"Project memory:\n{memory_context}\n\n"
            f"Relevant file context:\n{file_context or 'No extra file context.'}\n\n"
            f"User question: {question}\n\n"
            "Answer in a terminal-friendly style. If the user asks what they were doing, "
            "summarize the active session and recent files."
        )

        try:
            return self.generate(system_prompt, prompt)
        except OllamaUnavailableError:
            return self._fallback_answer(question, memory_context, file_context)

    def summarize_activity(
        self,
        changed_files: List[str],
        file_snippets: Dict[str, str],
        previous_summary: str,
    ) -> LLMReply:
        system_prompt = (
            "You are DeepSleep's dream loop. Write a compact session summary using only factual "
            "details from the changed files. Mention the most likely task and the next sensible step."
        )
        snippet_block = "\n\n".join(
            f"[{path}]\n{snippet}" for path, snippet in file_snippets.items()
        )
        prompt = (
            f"Previous session summary:\n{previous_summary}\n\n"
            f"Changed files:\n- " + "\n- ".join(changed_files) + "\n\n"
            f"Snippets:\n{snippet_block or 'No readable snippets.'}\n\n"
            "Return a concise paragraph under 120 words."
        )

        try:
            return self.generate(system_prompt, prompt)
        except OllamaUnavailableError:
            return self._fallback_summary(changed_files, file_snippets, previous_summary)

    def _fallback_answer(
        self,
        question: str,
        memory_context: str,
        file_context: str,
    ) -> LLMReply:
        lower = question.lower()
        if "what was i doing" in lower or "what was i working on" in lower:
            lines = [
                "Ollama is offline, so here is the local memory snapshot:",
                memory_context.strip(),
            ]
        else:
            lines = [
                "Ollama is offline, so I am answering from the saved local context.",
                "Question:",
                question.strip(),
                "",
                "Memory:",
                memory_context.strip(),
            ]
            if file_context:
                lines.extend(["", "Relevant files:", file_context.strip()])
        return LLMReply(text="\n".join(lines).strip(), model="heuristic-fallback", used_fallback=True)

    def _fallback_summary(
        self,
        changed_files: List[str],
        file_snippets: Dict[str, str],
        previous_summary: str,
    ) -> LLMReply:
        snippet_preview = []
        for path, snippet in list(file_snippets.items())[:3]:
            first_line = next((line.strip() for line in snippet.splitlines() if line.strip()), "")
            if first_line:
                snippet_preview.append(f"{path}: {first_line[:80]}")

        description = (
            "Idle dream summary: "
            + (f"continued from '{previous_summary}'. " if previous_summary and previous_summary != "No session summary yet." else "")
            + f"Recent activity touched {len(changed_files)} file(s): {', '.join(changed_files[:6]) or 'none'}."
        )
        if snippet_preview:
            description += " Key clues: " + " | ".join(snippet_preview)
        description += " Next step: reopen the newest file and continue from the last edited section."
        return LLMReply(text=description, model="heuristic-fallback", used_fallback=True)

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[dict] = None,
    ) -> dict:
        url = f"{self.host}{endpoint}"
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, method=method, headers=headers)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            raise OllamaUnavailableError(str(exc)) from exc

        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise OllamaUnavailableError("Ollama returned invalid JSON.") from exc

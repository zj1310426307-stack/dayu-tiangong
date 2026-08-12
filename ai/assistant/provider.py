"""定义可选外部大模型提供方，默认运行不依赖任何云端密钥。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """保存 OpenAI-compatible 对话端点所需的最小配置。"""

    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 20.0


class CompatibleChatProvider:
    """调用管理员显式配置的兼容端点，不参与工具权限判断。"""

    def __init__(self, config: ProviderConfig) -> None:
        """保存不可变连接配置，避免在请求间修改提供方。"""

        self._config = config

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """向兼容端点发送仅含已脱敏证据的提示并返回文本。"""

        body = json.dumps(
            {
                "model": self._config.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")
        request = Request(
            f"{self._config.base_url.rstrip('/')}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self._config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"]).strip()

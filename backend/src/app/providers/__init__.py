"""
Multi-provider adapter system for LLM execution.

Supports:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Google (Gemini)
- Azure OpenAI
- Local models (Ollama, vLLM)

Configurable at runtime via provider registry.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import os
import json
import time

from app.services.secrets import resolve_provider_api_key


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""
    name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: str = ""
    timeout: int = 30
    max_retries: int = 3
    rate_limit_rpm: int = 60
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class ExecutionResult:
    """Result from provider execution."""
    response: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float
    model: str
    provider: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """Base class for LLM providers."""
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self.name = config.name
    
    @abstractmethod
    def execute(
        self,
        agent_type: str,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an agent task through the provider."""
        pass
    
    @abstractmethod
    def get_models(self) -> List[str]:
        """Get available models for this provider."""
        pass
    
    def estimate_cost(self, tokens_in: int, tokens_out: int, model: str) -> float:
        """Estimate cost based on token usage."""
        # Override in subclasses with actual pricing
        return 0.0


class OpenAIProvider(BaseProvider):
    """OpenAI API provider (GPT-4, GPT-3.5, etc.)."""
    
    PRICING = {
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    }
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.api_key = resolve_provider_api_key("openai", "OPENAI_API_KEY", config.api_key)
        self.base_url = config.base_url or "https://api.openai.com/v1"
        self.default_model = config.default_model or "gpt-4o-mini"
    
    def execute(
        self,
        agent_type: str,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute through OpenAI API."""
        try:
            import openai
            
            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            
            model = agent_config.get("model", self.default_model)
            system_prompt = agent_config.get("system_prompt", f"You are a {agent_type} agent.")
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(input_data)}
            ]
            
            start = time.perf_counter()
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=agent_config.get("max_tokens", 1024)
            )
            latency_ms = (time.perf_counter() - start) * 1000
            
            tokens_in = response.usage.prompt_tokens
            tokens_out = response.usage.completion_tokens
            
            return {
                "response": response.choices[0].message.content,
                "confidence": 0.95,
                "_tokens_in": tokens_in,
                "_tokens_out": tokens_out,
                "_latency_ms": latency_ms,
                "_cost_usd": self.estimate_cost(tokens_in, tokens_out, model),
                "_model": model,
                "_provider": "openai"
            }
            
        except ImportError:
            return self._mock_response(agent_type, input_data)
        except Exception as e:
            return {
                "response": f"Error: {str(e)}",
                "error": str(e),
                "_tokens_in": 0,
                "_tokens_out": 0,
                "_model": agent_config.get("model", self.default_model),
                "_provider": "openai"
            }
    
    def _mock_response(self, agent_type: str, input_data: Dict) -> Dict[str, Any]:
        """Mock response when OpenAI package not available."""
        return {
            "response": f"[MOCK] {agent_type} response for: {json.dumps(input_data)[:100]}",
            "confidence": 0.9,
            "_tokens_in": len(str(input_data)) // 4,
            "_tokens_out": 50,
            "_mock": True,
            "_provider": "openai"
        }
    
    def get_models(self) -> List[str]:
        return list(self.PRICING.keys())
    
    def estimate_cost(self, tokens_in: int, tokens_out: int, model: str) -> float:
        pricing = self.PRICING.get(model, {"input": 0.001, "output": 0.002})
        return (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1000


class AnthropicProvider(BaseProvider):
    """Anthropic API provider (Claude models)."""
    
    PRICING = {
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    }
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.api_key = resolve_provider_api_key("anthropic", "ANTHROPIC_API_KEY", config.api_key)
        self.default_model = config.default_model or "claude-3-haiku-20240307"
    
    def execute(
        self,
        agent_type: str,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute through Anthropic API."""
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=self.api_key)
            
            model = agent_config.get("model", self.default_model)
            system_prompt = agent_config.get("system_prompt", f"You are a {agent_type} agent.")
            
            start = time.perf_counter()
            response = client.messages.create(
                model=model,
                max_tokens=agent_config.get("max_tokens", 1024),
                system=system_prompt,
                messages=[
                    {"role": "user", "content": json.dumps(input_data)}
                ]
            )
            latency_ms = (time.perf_counter() - start) * 1000
            
            tokens_in = response.usage.input_tokens
            tokens_out = response.usage.output_tokens
            
            return {
                "response": response.content[0].text,
                "confidence": 0.95,
                "_tokens_in": tokens_in,
                "_tokens_out": tokens_out,
                "_latency_ms": latency_ms,
                "_cost_usd": self.estimate_cost(tokens_in, tokens_out, model),
                "_model": model,
                "_provider": "anthropic"
            }
            
        except ImportError:
            return self._mock_response(agent_type, input_data)
        except Exception as e:
            return {
                "response": f"Error: {str(e)}",
                "error": str(e),
                "_tokens_in": 0,
                "_tokens_out": 0,
                "_model": agent_config.get("model", self.default_model),
                "_provider": "anthropic"
            }
    
    def _mock_response(self, agent_type: str, input_data: Dict) -> Dict[str, Any]:
        return {
            "response": f"[MOCK] Claude {agent_type} response",
            "confidence": 0.9,
            "_tokens_in": len(str(input_data)) // 4,
            "_tokens_out": 50,
            "_mock": True,
            "_provider": "anthropic"
        }
    
    def get_models(self) -> List[str]:
        return list(self.PRICING.keys())
    
    def estimate_cost(self, tokens_in: int, tokens_out: int, model: str) -> float:
        pricing = self.PRICING.get(model, {"input": 0.001, "output": 0.005})
        return (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1000


class AzureOpenAIProvider(BaseProvider):
    """Azure OpenAI Service provider."""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.api_key = resolve_provider_api_key("azure_openai", "AZURE_OPENAI_API_KEY", config.api_key)
        self.base_url = config.base_url or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_version = config.extra.get("api_version", "2024-02-15-preview")
        self.deployment = config.extra.get("deployment", "gpt-4")
    
    def execute(
        self,
        agent_type: str,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute through Azure OpenAI."""
        try:
            from openai import AzureOpenAI
            
            client = AzureOpenAI(
                api_key=self.api_key,
                api_version=self.api_version,
                azure_endpoint=self.base_url
            )
            
            deployment = agent_config.get("deployment", self.deployment)
            system_prompt = agent_config.get("system_prompt", f"You are a {agent_type} agent.")
            
            start = time.perf_counter()
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(input_data)}
                ],
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=agent_config.get("max_tokens", 1024)
            )
            latency_ms = (time.perf_counter() - start) * 1000
            
            return {
                "response": response.choices[0].message.content,
                "confidence": 0.95,
                "_tokens_in": response.usage.prompt_tokens,
                "_tokens_out": response.usage.completion_tokens,
                "_latency_ms": latency_ms,
                "_deployment": deployment,
                "_provider": "azure_openai"
            }
            
        except ImportError:
            return {"response": "[MOCK] Azure OpenAI response", "_mock": True}
        except Exception as e:
            return {"response": f"Error: {str(e)}", "error": str(e)}
    
    def get_models(self) -> List[str]:
        return [self.deployment]


class OllamaProvider(BaseProvider):
    """Ollama local model provider."""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.base_url = config.base_url or "http://localhost:11434"
        self.default_model = config.default_model or "llama2"
    
    def execute(
        self,
        agent_type: str,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute through Ollama."""
        try:
            import requests
            
            model = agent_config.get("model", self.default_model)
            system_prompt = agent_config.get("system_prompt", f"You are a {agent_type} agent.")
            
            start = time.perf_counter()
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": f"{system_prompt}\n\nInput: {json.dumps(input_data)}",
                    "stream": False
                },
                timeout=self.config.timeout
            )
            latency_ms = (time.perf_counter() - start) * 1000
            
            data = response.json()
            
            return {
                "response": data.get("response", ""),
                "confidence": 0.9,
                "_tokens_in": data.get("prompt_eval_count", 0),
                "_tokens_out": data.get("eval_count", 0),
                "_latency_ms": latency_ms,
                "_model": model,
                "_provider": "ollama"
            }
            
        except Exception as e:
            return {
                "response": f"[MOCK] Ollama response for {agent_type}",
                "confidence": 0.8,
                "_mock": True,
                "_error": str(e),
                "_provider": "ollama"
            }
    
    def get_models(self) -> List[str]:
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags")
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except:
            return ["llama2", "mistral", "codellama"]


class GoogleGeminiProvider(BaseProvider):
    """Google Gemini API provider."""
    
    PRICING = {
        "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
        "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
        "gemini-1.0-pro": {"input": 0.0005, "output": 0.0015},
    }
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.api_key = resolve_provider_api_key("google", "GOOGLE_API_KEY", config.api_key)
        self.default_model = config.default_model or "gemini-1.5-flash"
    
    def execute(
        self,
        agent_type: str,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute through Google Gemini."""
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=self.api_key)
            
            model_name = agent_config.get("model", self.default_model)
            model = genai.GenerativeModel(model_name)
            
            system_prompt = agent_config.get("system_prompt", f"You are a {agent_type} agent.")
            prompt = f"{system_prompt}\n\nInput: {json.dumps(input_data)}"
            
            start = time.perf_counter()
            response = model.generate_content(prompt)
            latency_ms = (time.perf_counter() - start) * 1000
            
            return {
                "response": response.text,
                "confidence": 0.95,
                "_latency_ms": latency_ms,
                "_model": model_name,
                "_provider": "google"
            }
            
        except ImportError:
            return {"response": "[MOCK] Gemini response", "_mock": True, "_provider": "google"}
        except Exception as e:
            return {"response": f"Error: {str(e)}", "error": str(e), "_provider": "google"}
    
    def get_models(self) -> List[str]:
        return list(self.PRICING.keys())


class MockProvider(BaseProvider):
    """Mock provider for testing without API calls."""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.responses = config.extra.get("responses", {})
        self.latency_ms = config.extra.get("latency_ms", 100)
    
    def execute(
        self,
        agent_type: str,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return mock response."""
        time.sleep(self.latency_ms / 1000)  # Simulate latency
        
        response = self.responses.get(
            agent_type, 
            f"Mock response from {agent_type} agent"
        )
        
        return {
            "response": response,
            "confidence": 0.99,
            "_tokens_in": len(str(input_data)) // 4,
            "_tokens_out": len(response) // 4,
            "_latency_ms": self.latency_ms,
            "_mock": True,
            "_provider": "mock"
        }
    
    def get_models(self) -> List[str]:
        return ["mock-model"]


class ProviderRegistry:
    """
    Registry for managing LLM providers.
    
    Allows runtime configuration and switching between providers.
    """
    
    PROVIDER_CLASSES = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "azure_openai": AzureOpenAIProvider,
        "azure": AzureOpenAIProvider,
        "ollama": OllamaProvider,
        "google": GoogleGeminiProvider,
        "gemini": GoogleGeminiProvider,
        "mock": MockProvider,
    }
    
    def __init__(self, *, strategy: Optional[str] = None):
        self.providers: Dict[str, BaseProvider] = {}
        self.default_provider: Optional[str] = None
        self.strategy = (strategy or os.getenv("PROVIDER_STRATEGY") or "auto").lower()
    
    def register(self, name: str, config: ProviderConfig) -> BaseProvider:
        """Register a provider with configuration."""
        provider_type = config.name
        if self.strategy == "mock" and provider_type != "mock":
            provider_class = MockProvider
            config = ProviderConfig(name="mock", extra=config.extra)
        else:
            provider_class = self.PROVIDER_CLASSES.get(provider_type)
        if not provider_class:
            raise ValueError(f"Unknown provider type: {provider_type}")
        
        provider = provider_class(config)
        self.providers[name] = provider
        
        if self.default_provider is None:
            self.default_provider = name
        
        return provider
    
    def get_provider(self, name: Optional[str] = None) -> BaseProvider:
        """Get a registered provider by name."""
        if name is None:
            name = self.default_provider
        
        if name not in self.providers:
            # Auto-register mock provider as fallback
            if self.strategy == "mock" or name == "mock" or not self.providers:
                registered = self.register(name or "mock", ProviderConfig(name="mock"))
                if self.default_provider is None:
                    self.default_provider = name or "mock"
                return registered
            raise ValueError(f"Provider not registered: {name}")
        
        return self.providers[name]
    
    def list_providers(self) -> List[str]:
        """List registered provider names."""
        return list(self.providers.keys())
    
    def list_available_providers(self) -> List[str]:
        """List available provider types."""
        return list(self.PROVIDER_CLASSES.keys())

    def enable_mock_mode(self) -> None:
        """Switch registry to mock-only mode (useful for offline tests)."""

        self.strategy = "mock"
        for name in list(self.providers.keys()):
            self.providers[name] = MockProvider(ProviderConfig(name="mock"))
        if "mock" not in self.providers:
            self.register("mock", ProviderConfig(name="mock"))


# Global provider registry instance
provider_registry = ProviderRegistry()


def configure_providers(config: Dict[str, Any]) -> ProviderRegistry:
    """
    Configure providers from a configuration dictionary.
    
    Example config:
    {
        "providers": {
            "openai": {
                "type": "openai",
                "api_key": "sk-...",
                "default_model": "gpt-4o-mini"
            },
            "claude": {
                "type": "anthropic",
                "api_key": "sk-ant-..."
            }
        },
        "default": "openai"
    }
    """
    registry = ProviderRegistry(strategy=config.get("strategy"))
    
    for name, provider_config in config.get("providers", {}).items():
        provider_type = provider_config.pop("type", name)
        registry.register(
            name,
            ProviderConfig(
                name=provider_type,
                api_key=provider_config.get("api_key"),
                base_url=provider_config.get("base_url"),
                default_model=provider_config.get("default_model", ""),
                timeout=provider_config.get("timeout", 30),
                max_retries=provider_config.get("max_retries", 3),
                extra=provider_config
            )
        )
    
    if config.get("default"):
        registry.default_provider = config["default"]
    
    return registry

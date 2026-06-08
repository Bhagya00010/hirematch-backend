import os
import logging
from typing import Optional
from abc import ABC, abstractmethod
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseAIProvider(ABC):
    """
    Abstract Base Class for LLM and Embedding provider strategies.
    """
    @abstractmethod
    def get_llm(self, temperature: float = 0.0) -> BaseChatModel:
        """Get the LangChain Chat Model."""
        pass

    @abstractmethod
    def get_embeddings(self) -> Embeddings:
        """Get the LangChain Embeddings model."""
        pass


class OllamaProvider(BaseAIProvider):
    """
    Ollama Provider using langchain-ollama.
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.api_key = settings.OLLAMA_API_KEY
        self.model_name = settings.OLLAMA_MODEL if settings.OLLAMA_MODEL else settings.OLLAMA_LLM_MODEL

    def get_llm(self, temperature: float = 0.0) -> BaseChatModel:
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "Could not import ChatOllama from langchain_ollama. "
                "Please install langchain-ollama: pip install langchain-ollama"
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        return ChatOllama(
            model=self.model_name,
            base_url=self.base_url,
            temperature=temperature,
            client_kwargs={"headers": headers} if headers else {}
        )

    def get_embeddings(self) -> Embeddings:
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            raise ImportError(
                "Could not import OllamaEmbeddings from langchain-ollama. "
                "Please install langchain-ollama: pip install langchain-ollama"
            )

        if self.base_url:
            os.environ["OLLAMA_BASE_URL"] = self.base_url

        embedding_model = settings.AI_EMBEDDING_MODEL if settings.AI_EMBEDDING_MODEL else (
            settings.OLLAMA_EMBEDDING_MODEL if settings.OLLAMA_EMBEDDING_MODEL else self.model_name
        )

        return OllamaEmbeddings(
            model=embedding_model
        )


class GeminiProvider(BaseAIProvider):
    """
    Google Gemini Provider using langchain-google-genai with local Hugging Face embeddings.
    """

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.llm_model = settings.GEMINI_LLM_MODEL
        self.huggingface_model = settings.HUGGINGFACE_EMBEDDING_MODEL

    def get_llm(self, temperature: float = 0.0) -> BaseChatModel:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError(
                "Could not import ChatGoogleGenerativeAI from langchain-google-genai. "
                "Please install langchain-google-genai: pip install langchain-google-genai"
            )

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY must be set when using Gemini LLM.")

        return ChatGoogleGenerativeAI(
            model=self.llm_model,
            google_api_key=self.api_key,
            temperature=temperature,
        )

    def get_embeddings(self) -> Embeddings:
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings
        except ImportError:
            raise ImportError(
                "Could not import HuggingFaceEmbeddings. "
                "Make sure sentence-transformers is installed: pip install sentence-transformers"
            )

        return HuggingFaceEmbeddings(
            model_name=self.huggingface_model
        )


class OpenAIProvider(BaseAIProvider):
    """
    OpenAI Provider using langchain-openai.
    """

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.llm_model = settings.OPENAI_LLM_MODEL
        self.embedding_model = settings.OPENAI_EMBEDDING_MODEL

    def get_llm(self, temperature: float = 0.0) -> BaseChatModel:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "Could not import ChatOpenAI from langchain-openai. "
                "Please install langchain-openai: pip install langchain-openai"
            )

        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY must be set when using OpenAI LLM.")

        return ChatOpenAI(
            model=self.llm_model,
            api_key=self.api_key,
            temperature=temperature,
        )

    def get_embeddings(self) -> Embeddings:
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            raise ImportError(
                "Could not import OpenAIEmbeddings from langchain-openai. "
                "Please install langchain-openai: pip install langchain-openai"
            )

        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY must be set when using OpenAI embeddings.")

        return OpenAIEmbeddings(
            model=self.embedding_model,
            api_key=self.api_key,
        )


def get_llm_provider(provider_name: Optional[str] = None) -> BaseAIProvider:
    """
    Factory helper to resolve LLM provider strategy.
    """
    if not provider_name:
        provider_name = settings.LLM_PROVIDER

    if not provider_name:
        if settings.OLLAMA_MODEL or settings.OLLAMA_LLM_MODEL:
            provider_name = "ollama"
        elif settings.GEMINI_API_KEY:
            provider_name = "gemini"
        elif settings.OPENAI_API_KEY:
            provider_name = "openai"
        else:
            raise ValueError(
                "No LLM provider configured. Please set OLLAMA_MODEL, GEMINI_API_KEY, or OPENAI_API_KEY in your env."
            )

    provider_name = provider_name.lower().strip()
    logger.info(f"Resolved LLM Provider: {provider_name}")

    if provider_name == "ollama":
        return OllamaProvider()
    elif provider_name == "gemini":
        return GeminiProvider()
    elif provider_name == "openai":
        return OpenAIProvider()
    else:
        raise ValueError(f"Unsupported AI provider: {provider_name}")


def get_embedding_provider(provider_name: Optional[str] = None) -> BaseAIProvider:
    """
    Factory helper to resolve Embedding provider strategy.
    """
    if not provider_name:
        provider_name = settings.EMBEDDING_PROVIDER

    if not provider_name:
        if settings.OLLAMA_EMBEDDING_MODEL or settings.AI_EMBEDDING_MODEL:
            provider_name = "ollama"
        elif settings.GEMINI_API_KEY:
            provider_name = "gemini"
        elif settings.OPENAI_API_KEY:
            provider_name = "openai"
        else:
            provider_name = "ollama"  # fallback default

    provider_name = provider_name.lower().strip()
    logger.info(f"Resolved Embedding Provider: {provider_name}")

    if provider_name == "ollama":
        return OllamaProvider()
    elif provider_name == "gemini":
        return GeminiProvider()
    elif provider_name == "openai":
        return OpenAIProvider()
    else:
        raise ValueError(f"Unsupported Embedding provider: {provider_name}")


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """
    Global convenience helper to get the LLM using the active provider strategy.
    """
    return get_llm_provider().get_llm(temperature=temperature)


def get_embeddings() -> Embeddings:
    """
    Global convenience helper to get Embeddings using the active provider strategy.
    """
    return get_embedding_provider().get_embeddings()

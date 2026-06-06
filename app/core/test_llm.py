from app.core.llm import get_llm, get_embeddings
from app.core.config import settings

def test_ai_flow():
    try:
        llm = get_llm()
        embeddings = get_embeddings()
    except Exception as e:
        print(f"Error resolving LLM/Embeddings: {e}")
        return

    provider_name = settings.LLM_PROVIDER
    if not provider_name:
        if settings.OLLAMA_MODEL or settings.OLLAMA_LLM_MODEL:
            provider_name = "ollama"
        elif settings.GEMINI_API_KEY:
            provider_name = "gemini"
        elif settings.OPENAI_API_KEY:
            provider_name = "openai"

    llm_model = settings.OLLAMA_MODEL if settings.OLLAMA_MODEL else settings.OLLAMA_LLM_MODEL
    if provider_name == "gemini":
        llm_model = settings.GEMINI_LLM_MODEL
    elif provider_name == "openai":
        llm_model = settings.OPENAI_LLM_MODEL

    embedding_model = settings.AI_EMBEDDING_MODEL if settings.AI_EMBEDDING_MODEL else settings.OLLAMA_EMBEDDING_MODEL
    if provider_name == "gemini":
        embedding_model = settings.HUGGINGFACE_EMBEDDING_MODEL
    elif provider_name == "openai":
        embedding_model = settings.OPENAI_EMBEDDING_MODEL

    print(f"Model Name: {llm_model}")
    print(f"Embedding Model Name: {embedding_model}")

    question = "What is the capital of France?"
    print(f"Question: {question}")
    
    print("\nSending question to LLM...")
    try:
        response = llm.invoke(question)
        if hasattr(response, 'content'):
            answer = response.content
        else:
            answer = str(response)
        print(f"Answer: {answer}")
    except Exception as e:
        print(f"LLM Invocation failed: {e}")
        return

    print("\nGenerating embedding of the answer...")
    try:
        vector = embeddings.embed_query(answer)
        print(f"Embedding vector (first 5 dimensions): {vector[:5]}...")
        print(f"Embedding vector total length: {len(vector)}")
    except Exception as e:
        print(f"Embedding Generation failed: {e}")

if __name__ == "__main__":
    test_ai_flow()

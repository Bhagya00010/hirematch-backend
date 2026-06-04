from fastapi import FastAPI

app = FastAPI(
    title="HireMatch AI",
    version="1.0.0"
)


@app.get("/")
def health():
    return {
        "status": "running",
        "service": "HireMatch AI"
    }

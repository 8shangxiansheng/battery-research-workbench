from fastapi import FastAPI

app = FastAPI(
    title="Battery Research Workbench API",
    version="0.1.1",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "architecture": "v1.1-multi-battery-multi-experiment",
        "phase": "M0-foundation",
    }

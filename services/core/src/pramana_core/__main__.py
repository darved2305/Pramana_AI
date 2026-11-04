"""Run the core service: ``python -m pramana_core`` (port from CORE_PORT, default 8000)."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "pramana_core.main:create_app",
        factory=True,
        host=os.environ.get("CORE_HOST", "127.0.0.1"),
        port=int(os.environ.get("CORE_PORT", "8000")),
        ws_max_size=1 << 20,
    )

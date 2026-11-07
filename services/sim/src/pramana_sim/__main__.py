"""Run the simulator: ``python -m pramana_sim`` (port from SIM_PORT, default 8100)."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "pramana_sim.app:create_app",
        factory=True,
        host=os.environ.get("SIM_HOST", "127.0.0.1"),
        port=int(os.environ.get("SIM_PORT", "8100")),
        # Longer than any client's pooled-connection idle time (Node keeps them ~5 s), so the
        # server never closes a connection a proxy or test client is about to reuse.
        timeout_keep_alive=65,
    )

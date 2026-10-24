"""Run with:  python -m kairo_gateway   (from the repository root)"""

import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

uvicorn.run(
    "kairo_gateway.server:app",
    host=os.getenv("KAIRO_GATEWAY_HOST", "0.0.0.0"),
    port=int(os.getenv("KAIRO_GATEWAY_PORT", "8090")),
    log_level="info",
)

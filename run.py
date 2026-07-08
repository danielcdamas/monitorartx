"""Ponto de entrada: python run.py [porta]"""
import os
import sys

import uvicorn

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    # sem o timeout, streams SSE abertos seguram o shutdown para sempre
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, timeout_graceful_shutdown=5)

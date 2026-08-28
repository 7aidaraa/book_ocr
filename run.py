"""Start the server.

Local:   python run.py            -> http://127.0.0.1:8000
Hosted:  HOST=0.0.0.0 PORT=7860   (set by the container; e.g. HF Spaces)
"""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )

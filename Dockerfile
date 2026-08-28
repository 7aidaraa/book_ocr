# Hosted deployment (e.g. Hugging Face Spaces, Docker SDK).
# Local use does not need Docker — see README.

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user . /home/user/app

RUN pip install --no-cache-dir --user -r requirements.txt

# Download OCR models at build time so the first conversion doesn't wait
# on a ~1GB download. Tolerated if the hoster is briefly unreachable.
RUN python -c "\
from paddleocr import PPStructureV3; \
PPStructureV3(lang='ar', use_doc_orientation_classify=True, use_doc_unwarping=False, \
use_table_recognition=True, use_formula_recognition=False)" || true

ENV HOST=0.0.0.0 PORT=7860
EXPOSE 7860
CMD ["python", "run.py"]

.PHONY: help install install-ai run dev test demo seed docker clean storage

PY ?= python3

help:
	@echo "BhashaFlix AI"
	@echo "  make install      install core deps (CPU only, works on free tiers)"
	@echo "  make install-ai   install optional models (whisper, NLLB, XTTS, demucs)"
	@echo "  make run          start the server on 0.0.0.0:8000"
	@echo "  make test         run the full real test suite"
	@echo "  make demo         dub a generated sample clip end to end"
	@echo "  make seed         fill a running server with two finished demo projects"
	@echo "  make docker       build the container image"
	@echo "  make clean        remove generated storage (irreversible)"

install:
	$(PY) -m pip install -r requirements.txt

install-ai:
	$(PY) -m pip install -r requirements-ai.txt

run:
	$(PY) -m uvicorn backend.app:app --host 0.0.0.0 --port $${PORT:-8000}

dev:
	BFLIX_RELOAD=1 $(PY) -m uvicorn backend.app:app --host 0.0.0.0 --port $${PORT:-8000} --reload

test:
	$(PY) -m pytest -q

demo:
	$(PY) scripts/demo_e2e.py

seed:
	$(PY) scripts/seed_demo_library.py

docker:
	docker build -t bhashaflix-ai .

clean:
	rm -rf storage/jobs storage/tmp storage/*.sqlite3*
	@mkdir -p storage && touch storage/.gitkeep

# Open Studio — one command to build and run the complete local AI studio.
# Run `make help` for the full target list.

SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose
COMPOSE_GPU := docker compose -f docker-compose.yml -f docker-compose.gpu.yml
COMPOSE_VULKAN := docker compose -f docker-compose.yml -f docker-compose.vulkan.yml
PY := python3
WHISPER_MODEL ?= large-v3
OLLAMA_MODEL ?= llama3.2:3b
CHAT_AGENT_MODEL ?= qwen3:4b
OPENSTUDIO_PORT ?= 8090

.PHONY: help init build rebuild up up-cpu up-gpu up-vulkan up-all down fix-perms stop restart ps logs wait health status config shell \
        models models-all models-llm models-music models-whisper models-text models-piper models-images models-qvac \
        gpu-info test test-backend test-frontend screenshots demo backup reset clean pull update api-url \
        verify compose-config

help: ## Show this help
	@echo ""
	@echo "  Open Studio — local AI music, video, voice, documents and media"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "  First run:   make up          (builds missing images and starts core)"
	@echo "  Restart:     make up          (reuses images and persistent ./data)"
	@echo "  Rebuild:     make rebuild     (after changing source code)"
	@echo "  Then open:   http://localhost:$(OPENSTUDIO_PORT)"
	@echo "  Set the password in the browser on first use."
	@echo "  Models:      make models      (downloads LLM + music + text + whisper + piper)"
	@echo ""

init: ## Create ./data, seed initial_data, .env and a random INTERNAL_TOKEN
	@mkdir -p data 2>/dev/null || true
	@if [ -d initial_data ] && [ ! -f data/.initialized ]; then \
		if [ -z "$$(find data -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then \
			echo "Seeding initial state from initial_data/"; \
			cp -a initial_data/. data/ 2>/dev/null || echo "Warning: could not seed initial_data (check data ownership)"; \
		fi; \
	fi
	@for directory in files state cache models artifacts exports home; do mkdir -p "data/$$directory" 2>/dev/null || true; done
	@touch data/.initialized 2>/dev/null || true
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		TOKEN=$$(openssl rand -hex 32 2>/dev/null || $(PY) -c "import secrets; print(secrets.token_hex(32))"); \
		$(PY) -c "import pathlib,sys; p=pathlib.Path('.env'); s=p.read_text(); s=s.replace('INTERNAL_TOKEN=change-me-openstudio-internal','INTERNAL_TOKEN='+sys.argv[1]); p.write_text(s)" "$$TOKEN"; \
		echo "Created .env with a random INTERNAL_TOKEN."; \
	fi
	@$(PY) -c "import pathlib,sys,re; p=pathlib.Path('.env'); s=p.read_text(); key='OPENSTUDIO_DATA_DIR'; val=sys.argv[1]; s=re.sub(r'^'+key+r'=.*$$', key+'='+val, s, flags=re.M) if re.search(r'^'+key+r'=', s, re.M) else s+('\n' if not s.endswith('\n') else '')+key+'='+val+'\n'; key='OPENSTUDIO_REPO_DIR'; val=sys.argv[2]; s=re.sub(r'^'+key+r'=.*$$', key+'='+val, s, flags=re.M) if re.search(r'^'+key+r'=', s, re.M) else s+('\n' if not s.endswith('\n') else '')+key+'='+val+'\n'; p.write_text(s)" "$(CURDIR)/data" "$(CURDIR)"
	@# The music engine uses ACESTEP_UID/GID (default root). Host-owned model
	@# volumes can override them explicitly in .env; make init does not force
	@# the host UID because core services create ./data as root.
	@TOKEN=$$(grep '^INTERNAL_TOKEN=' .env | cut -d= -f2-); printf '%s' "$$TOKEN" > data/state/internal.token 2>/dev/null || true
	@chmod 600 data/state/internal.token 2>/dev/null || true
	@echo "Data directory: $(CURDIR)/data"

build: init ## Build the always-on core images (optional services are built on demand)
	$(COMPOSE) build files jobhub admin gateway frontend chat

up: init ## Start/restart the core; reuse existing images and persistent data
	COMPOSE_OVERRIDES= $(COMPOSE) --profile services up -d files jobhub admin gateway frontend chat
	@echo ""
	@echo "Open Studio core is starting."
	@echo "  Web app:      http://localhost:$(OPENSTUDIO_PORT)"
	@echo "  API gateway:  http://127.0.0.1:$${GATEWAY_PORT:-8091}/api/health"
	@echo "  First visit:  create your password, then enable services in Settings → Services."
	@echo "  Health:       make health"
	@echo "  Logs:         make logs"
	@echo ""

up-cpu: up ## Alias for CPU mode

up-gpu: init ## Start the core app with NVIDIA CUDA used for on-demand services
	TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128 \
	VOICE_DEVICE=cuda WHISPER_DEVICE=cuda SRT_INSTALL_CUDA=1 QVAC_DEVICE=gpu \
	COMPOSE_OVERRIDES="-f docker-compose.gpu.yml" \
		$(COMPOSE) --profile services up -d files jobhub admin gateway frontend chat
	@echo "NVIDIA mode active. Enable services in Settings → Services; builds use the GPU override."

up-vulkan: init ## Start the core app with AMD/Intel Vulkan for on-demand services
	ACESTEP_VULKAN=1 QVAC_DEVICE=gpu \
	COMPOSE_OVERRIDES="-f docker-compose.vulkan.yml" \
		$(COMPOSE) --profile services up -d files jobhub admin gateway frontend chat
	@echo "Vulkan mode active. Enable services in Settings → Services; builds use the Vulkan override."

up-all: init ## Start every service (no lazy loading)
	$(COMPOSE) --profile services up -d

rebuild: init ## Rebuild and recreate the core after a source update
	COMPOSE_OVERRIDES= $(COMPOSE) --profile services up -d --build --force-recreate files jobhub admin gateway frontend chat

down: ## Stop all containers (data is kept)
	$(COMPOSE) --profile services down --remove-orphans

stop: ## Stop without removing containers
	$(COMPOSE) --profile services stop

restart: ## Restart the stack
	$(COMPOSE) --profile services restart

ps: ## Show container status
	$(COMPOSE) --profile services ps

logs: ## Follow logs (SERVICE=name to filter)
	@if [ -n "$(SERVICE)" ]; then $(COMPOSE) logs -f --tail=200 $(SERVICE); else $(COMPOSE) logs -f --tail=100; fi

wait: ## Wait until the gateway and frontend are healthy
	@bash scripts/wait-for-health.sh

health: ## Probe the public app and the gateway
	@echo "Frontend: $$(curl -fsS -o /dev/null -w '%{http_code}' http://localhost:$(OPENSTUDIO_PORT)/ || echo offline)"
	@echo "Gateway:  $$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:$${GATEWAY_PORT:-8091}/api/health || echo offline)"
	@curl -fsS http://127.0.0.1:$${GATEWAY_PORT:-8091}/api/health 2>/dev/null | $(PY) -m json.tool 2>/dev/null || true

status: ps ## Show containers + queues + health
	$(COMPOSE) ps
	@echo ""
	@curl -fsS http://127.0.0.1:$${GATEWAY_PORT:-8091}/api/health 2>/dev/null | $(PY) -m json.tool 2>/dev/null || echo "Gateway not reachable yet."

config: ## Render the resolved compose configuration
	$(COMPOSE) config

compose-config: config ## Alias

api-url: ## Print the public API URL and a curl example
	@echo "http://127.0.0.1:$${GATEWAY_PORT:-8091}/api"
	@echo "curl -H 'Authorization: Bearer <api-key>' http://127.0.0.1:$${GATEWAY_PORT:-8091}/api/status"

shell: ## Open a shell: make shell SERVICE=gateway
	@test -n "$(SERVICE)" || (echo "Usage: make shell SERVICE=gateway"; exit 1)
	$(COMPOSE) exec $(SERVICE) sh

# ── Models ────────────────────────────────────────────────────────────────
models: models-llm models-music models-whisper models-text models-piper ## Download every model used by the stack
	@echo "All model downloads finished (QVAC/SD checkpoints download on first use)."

models-all: models ## Alias

models-llm: ## Pull the Ollama models used for chat, lyrics and tool commands
	$(COMPOSE) up -d ollama
	@sleep 3
	$(COMPOSE) exec ollama ollama pull $${OLLAMA_MODEL:-$(OLLAMA_MODEL)} || $(COMPOSE) exec ollama ollama pull $(OLLAMA_MODEL)
	$(COMPOSE) exec ollama ollama pull $${CHAT_AGENT_MODEL:-$(CHAT_AGENT_MODEL)} || $(COMPOSE) exec ollama ollama pull $(CHAT_AGENT_MODEL)

models-music: ## Download the default ACE-Step GGUF set (~4-8 GB)
	$(COMPOSE) --profile services run --rm --user root --entrypoint /opt/acestep/download-models.sh music-engine

models-whisper: ## Pre-download the Whisper model
	$(COMPOSE) --profile services run --rm --entrypoint python srt -c "from faster_whisper import WhisperModel; WhisperModel('$(WHISPER_MODEL)', download_root='/data/models/whisper')"

models-text: ## Download OPUS-MT + T5 translation/summary models
	$(COMPOSE) --profile services run --rm --entrypoint download-models translation --models all
	$(COMPOSE) --profile services run --rm --entrypoint download-models summary --models all

models-piper: ## Download the built-in Piper voices (US/UK/FR/DE/ES/PT)
	$(COMPOSE) --profile services run --rm --entrypoint voice-download-models voice

models-images: ## Warm the diffusers cache (optional; first generation downloads)
	@echo "Images download on first use from Hugging Face, or set IMAGEGEN_DEFAULT_PROVIDER=procedural."

models-qvac: ## Show how to install QVAC model packs
	@echo "Install QVAC model packs from Settings → Models. The API is POST /api/qvac/models/install with {\"family\":\"...\"}."

# ── Hardware ──────────────────────────────────────────────────────────────
gpu-info: ## Show NVIDIA, Vulkan and /dev/dri status
	@echo "== NVIDIA =="; nvidia-smi 2>/dev/null || echo "nvidia-smi not found"
	@echo "== DRM / Vulkan devices =="; ls -l /dev/dri 2>/dev/null || echo "/dev/dri not present"
	@echo "== vulkaninfo =="; (command -v vulkaninfo >/dev/null && vulkaninfo --summary 2>/dev/null | head -30) || echo "vulkaninfo not installed on host (fine; the container has its own)"

# ── Quality ───────────────────────────────────────────────────────────────
test: test-backend test-frontend ## Run backend checks and the frontend build

test-backend: ## Compile every Python service and run the shared tests
	@bash scripts/test-backend.sh

test-frontend: ## Type-check and build the Vue app
	cd frontend && npm ci --silent 2>/dev/null || npm install --silent
	cd frontend && npm run typecheck
	cd frontend && npm run build

screenshots: ## Build the demo UI and capture docs/screenshots/*.png
	@bash scripts/take_screenshots.sh

demo: ## Serve the demo build at http://localhost:8090 (no backends)
	cd frontend && npm run build:demo && npm run preview

verify: ## Quick end-to-end smoke test against a running stack
	@bash scripts/smoke-test.sh

# ── Operations ────────────────────────────────────────────────────────────
backup: ## Backup data/ to data/backups/openstudio-<timestamp>.tar.gz
	@mkdir -p data/backups
	@STAMP=$$(date +%Y%m%d-%H%M%S); tar -czf data/backups/openstudio-$$STAMP.tar.gz data/files data/state .env; echo "Wrote data/backups/openstudio-$$STAMP.tar.gz"

pull: ## Pull all third-party base images
	$(COMPOSE) pull

update: rebuild ## Rebuild after a git pull (alias)

fix-perms: ## Fix ownership of ./data to the current host user
	@sudo chown -R "$$(id -u):$$(id -g)" "$(CURDIR)/data" 2>/dev/null || chown -R "$$(id -u):$$(id -g)" "$(CURDIR)/data" 2>/dev/null || echo "Could not change ownership; run: sudo chown -R $$(id -u):$$(id -g) data"
	@echo "Ownership refreshed."

reset: ## DESTRUCTIVE: remove containers and ./data (asks for confirmation)
	@read -p "Delete ALL Open Studio data (files, state, models, database)? [y/N] " ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		$(COMPOSE) --profile services down -v --remove-orphans; \
		rm -rf data/files data/state data/cache data/models data/artifacts data/exports; \
		echo "Data removed. .env kept."; \
	else echo "Aborted."; fi

clean: ## Remove stopped containers, dangling images and build cache
	$(COMPOSE) down --remove-orphans
	docker image prune -f
	docker builder prune -f

# The spoken count is dynamic text, so it cannot come from a pre-rendered mp3:
# PLAY_SOUND announces the phase instantly (cloc.mp3, checked in) and
# sounds/say.sh synthesizes "<count> lines of code" with the same voice and
# queues it behind the phase voice. The say.sh call is backgrounded so the
# count is never delayed by synthesis or playback.
cloc:
	@echo "Running cloc to count lines of code..."
	@$(call PLAY_SOUND,cloc)
	@# Exclude runtime bins and third_party from the count; print to terminal (no file)
	@if command -v cloc >/dev/null 2>&1; then \
		report=$$(mktemp); \
		trap 'rm -f "$$report"' EXIT; \
		cloc --exclude-dir=$(OUT_DIR),third_party,docs,node_modules,dist --exclude-ext=tex . | tee "$$report"; \
		loc=$$(awk '/^SUM:/ {print $$NF}' "$$report"); \
		if [ -n "$$loc" ]; then \
			nohup sh "$(SOUND_DIR)/say.sh" "$$loc lines of code" </dev/null >/dev/null 2>&1 & \
		fi; \
	else \
		echo "cloc not found on PATH. Install it (e.g. sudo apt install cloc) to get a detailed LOC report."; \
	fi
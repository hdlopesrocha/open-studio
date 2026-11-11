# ACE-Step 1.5 music engine

Dockerized GGUF/C++ engine used by `services/music`. It is built from the
repository root so the Dockerfile can copy these scripts:

```yaml
music-engine:
  build:
    context: .
    dockerfile: engines/acestep-cpp/Dockerfile
  image: openstudio-music-engine
  restart: unless-stopped
  ports:
    - "8085:8085"
  environment:
    ACESTEP_CPP_MODELS_DIR: /data/models/acestep
    ACESTEP_CPP_DEVICE: CPU            # or Vulkan0 / CUDA0
    ACESTEP_CPP_DOWNLOAD_MODELS: "true"
    ACESTEP_CPP_QUANT: Q8_0
    ACESTEP_CPP_LM_SIZE: 0.6B
  volumes:
    - ./data/models:/data/models
  healthcheck:
    test: ["CMD-SHELL", "curl -sf http://127.0.0.1:8085/health >/dev/null || exit 1"]
    interval: 30s
    timeout: 10s
    start_period: 30m
    retries: 5
```

The container runs as uid/gid `10001`. Make sure the bind-mounted model
directory is writable by that user on first start, or pre-populate
`data/models/acestep` and set `ACESTEP_CPP_DOWNLOAD_MODELS=false`. The default
Q8_0 set downloads about 7.7 GB (DiT, 5Hz LM, text encoder and VAE).

The music service expects the engine at `http://music-engine:8085` by default
(`ACESTEP_ENGINE_URL`). Open `http://localhost:8085/` for the engine's own
diagnostic UI.

The engine starts with `--max-batch 1` for low-memory machines. If you want to
use `lm_batch_size > 1` from the studio, set `ACESTEP_CPP_MAX_BATCH=4` (or the
largest batch you can afford) in the service environment.

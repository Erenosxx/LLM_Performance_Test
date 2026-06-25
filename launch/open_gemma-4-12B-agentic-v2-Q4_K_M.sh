#!/usr/bin/env bash
# gemma-4-12B-agentic-v2-Q4_K_M.gguf  (çift GPU)  -> http://127.0.0.1:8080
set -e
export CUDA_VISIBLE_DEVICES=0,1
"/home/han/Desktop/llama.cpp/build/bin/llama-server" \
  -m "/media/han/nvmer0/LLM/models/gemma-4-12B-agentic-v2-Q4_K_M.gguf" \
  -c 32768 -ngl 99 -sm layer \
  --host 127.0.0.1 --port 8080 \
  -a gemma-4-12B-agentic-v2-Q4_K_M --jinja

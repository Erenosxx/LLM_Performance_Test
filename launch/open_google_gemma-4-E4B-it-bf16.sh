#!/usr/bin/env bash
# google_gemma-4-E4B-it-bf16.gguf  (çift GPU)  -> http://127.0.0.1:8080
set -e
export CUDA_VISIBLE_DEVICES=0,1
"/home/han/Desktop/llama.cpp/build/bin/llama-server" \
  -m "/media/han/nvmer0/LLM/models/google_gemma-4-E4B-it-bf16.gguf" \
  -c 32768 -ngl 99 -fa on -sm layer \
  --host 127.0.0.1 --port 8080 \
  -a google_gemma-4-E4B-it-bf16 --jinja

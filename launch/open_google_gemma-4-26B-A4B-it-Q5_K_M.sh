#!/usr/bin/env bash
# google_gemma-4-26B-A4B-it-Q5_K_M.gguf  (çift GPU, 32k, -fa on)  -> http://127.0.0.1:8080
set -e
export CUDA_VISIBLE_DEVICES=0,1
"/home/han/Desktop/llama.cpp/build/bin/llama-server" \
  -m "/media/han/nvmer0/LLM/models/google_gemma-4-26B-A4B-it-Q5_K_M.gguf" \
  -c 32768 -ngl 99 -sm layer -fa on \
  --host 127.0.0.1 --port 8080 \
  -a google_gemma-4-26B-A4B-it-Q5_K_M --jinja

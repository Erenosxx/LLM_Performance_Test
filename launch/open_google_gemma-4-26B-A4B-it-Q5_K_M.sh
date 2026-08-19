#!/usr/bin/env bash
# google_gemma-4-26B-A4B-it-Q5_K_M.gguf  (tek GPU, 128k, -fa on)  -> http://127.0.0.1:8080
# profil: Gemma 4 (kart) · temp=1.0 top_p=0.95 top_k=64 rep=1.0
set -e
export CUDA_VISIBLE_DEVICES=0
"/home/han/Desktop/llama.cpp-new/build/bin/llama-server" \
  -m "/mnt/data/LLM/models/google_gemma-4-26B-A4B-it-Q5_K_M.gguf" \
  -c 131072 -ngl 99 -sm none -fa on \
  --host 127.0.0.1 --port 8080 \
  -a google_gemma-4-26B-A4B-it-Q5_K_M --jinja

#!/usr/bin/env bash
# Qwen3.8-27B-Q4_K_M.gguf  (tek GPU, 96k, -fa on)  -> http://127.0.0.1:8080
# profil: Qwen3.8 (kart: düşünme kipi) · temp=1.0 top_p=0.95 top_k=20 rep=1.0 effort=medium
set -e
export CUDA_VISIBLE_DEVICES=0
"/home/han/Desktop/llama.cpp-new/build/bin/llama-server" \
  -m "/mnt/data/LLM/models/Qwen3.8-27B-Q4_K_M.gguf" \
  -c 98304 -ngl 99 -sm none -fa on \
  --host 127.0.0.1 --port 8080 \
  -a Qwen3.8-27B-Q4_K_M --jinja

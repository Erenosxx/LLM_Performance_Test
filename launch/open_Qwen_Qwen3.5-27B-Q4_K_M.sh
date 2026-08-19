#!/usr/bin/env bash
# Qwen_Qwen3.5-27B-Q4_K_M.gguf  (tek GPU, 96k, -fa on)  -> http://127.0.0.1:8080
# profil: Qwen3.5-3.7 (kart) · temp=0.6 top_p=0.95 top_k=20 rep=1.0
set -e
export CUDA_VISIBLE_DEVICES=0
"/home/han/Desktop/llama.cpp-new/build/bin/llama-server" \
  -m "/mnt/data/LLM/models/Qwen_Qwen3.5-27B-Q4_K_M.gguf" \
  -c 98304 -ngl 99 -sm none -fa on \
  --host 127.0.0.1 --port 8080 \
  -a Qwen_Qwen3.5-27B-Q4_K_M --jinja

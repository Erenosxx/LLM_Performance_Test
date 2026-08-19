#!/usr/bin/env bash
# gemma-4-31B-it-qat-UD-Q4_K_XL.gguf  (tek GPU, 32k, -fa on)  -> http://127.0.0.1:8080
# profil: Gemma 4 (kart) · temp=1.0 top_p=0.95 top_k=64 rep=1.0
set -e
export CUDA_VISIBLE_DEVICES=0
"/home/han/Desktop/llama.cpp-new/build/bin/llama-server" \
  -m "/mnt/data/LLM/models/gemma-4-31B-it-qat-UD-Q4_K_XL.gguf" \
  -c 32768 -ngl 99 -sm none -fa on \
  --host 127.0.0.1 --port 8080 \
  -a gemma-4-31B-it-qat-UD-Q4_K_XL --jinja

# -*- coding: utf-8 -*-
"""
Test edilecek modellerin tek kaynak (single source of truth) yapılandırması.
launch/*.sh üreteci ve run_models.py orkestratörü bunu kullanır.

mmproj-*.gguf (projektör), *-adapter.gguf (LoRA) ve safetensors klasörleri
KASITLI olarak listede yoktur — bunlar tek başına çalıştırılabilir model değildir.
"""

MODELS_DIR = "/media/han/nvmer0/LLM/models"
LLAMA_SERVER = "/home/han/Desktop/llama.cpp/build/bin/llama-server"

PORT = 8080
HOST = "127.0.0.1"

DEFAULT_CTX = 65536       # 64k context -> max_tokens otomatik ~63488; token limitine çok daha az takılır
                          # (özellikle agentic çok-turlu görevlerde sohbet birikse de yer kalır)
DEFAULT_NGL = 99          # tüm katmanlar GPU'da (maksimum)
# NOT: Tüm modeller ÇİFT GPU'da açılır (eşit/adil koşul, OOM riski yok). Boyut-bazlı tek/çift
# stratejisi kaldırıldı (sınır modeller 64k'da OOM olup puan kaybediyordu).
SINGLE_GPU_MAX_GB = 17.0  # (artık kullanılmıyor; eski launcher'larla uyumluluk için bırakıldı)

# Küçükten büyüğe sıralı (hızlı geri bildirim için). İstemediğin satırı yorumla.
MODELS = [
    {"file": "gemma-3-4b-it-Q8_0.gguf"},
    {"file": "google_gemma-4-12B-it-qat-q4_0.gguf"},
    {"file": "gemma-4-12B-agentic-v2-Q4_K_M.gguf"},   # yuxinlu1 agentic/kod fine-tune (v2)
    {"file": "google_gemma-4-E4B-it-bf16.gguf"},
    {"file": "Qwen3.5-27B-Q4_K_M.gguf"},
    {"file": "google_gemma-3-27b-it-Q4_K_L.gguf"},
    {"file": "Qwen_Qwen3.6-27B-Q4_K_M.gguf"},
    {"file": "google_gemma-4-26B-A4B-it-Q5_K_M.gguf"},
    {"file": "google_gemma-4-31B-it-Q4_K_M.gguf"},
    {"file": "Qwen_Qwen3.6-27B-Q5_K_M.gguf"},
    {"file": "Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf"},
    {"file": "Qwen3.5-35B-A3B-Q4_K_M.gguf"},
    {"file": "google_gemma-4-31B-it-Q5_K_M.gguf"},
]

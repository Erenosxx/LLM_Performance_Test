# -*- coding: utf-8 -*-
"""
Test edilecek modellerin tek kaynak (single source of truth) yapılandırması.
launch/*.sh üreteci ve run_models.py orkestratörü bunu kullanır.

mmproj-*.gguf (projektör), *-adapter.gguf (LoRA) ve safetensors klasörleri
KASITLI olarak listede yoktur — bunlar tek başına çalıştırılabilir model değildir.
"""

MODELS_DIR = "/mnt/data/LLM/models"
LLAMA_SERVER = "/home/han/Desktop/llama.cpp-new/build/bin/llama-server"

PORT = 8080
HOST = "127.0.0.1"

DEFAULT_CTX = 32768       # 32k context -> max_tokens otomatik ~30720. TÜM .sh launcher'lar bu değerle
                          # (tek-tip, adil koşul). .sh artık gerçek açılışı belirler (run_models .sh'yi çalıştırır).
DEFAULT_NGL = 99          # tüm katmanlar GPU'da (maksimum)
# NOT (17 Ağu 2026): Makinede artık TEK RTX 4090 var (eski çift-GPU kurulumu yok).
# Launcher'lar tek GPU'ya geçirildi: CUDA_VISIBLE_DEVICES=0, -sm none.
# 32k context tek kartta ÖLÇÜLDÜ ve sığıyor — en dar model (gemma-4-31B-qat)
# yüklemede 23423 MiB, 1961 token üretimden sonra 23435 MiB (24564 MiB'ın altında).
# llama.cpp tamponları peşinen ayırdığı için üretim sırasında büyüme ~12 MiB.
# Daha rahat pay isterse: 24576 → 22775 MiB. Bir OOM görülürse ilk düşürülecek budur.
SINGLE_GPU_MAX_GB = 17.0  # (artık kullanılmıyor; eski launcher'larla uyumluluk için bırakıldı)

# WP6 değerlendirmesinin (results/20260812_170628) en iyi 3 modeli + yeni Qwen 3.8.
# Sıra: küçükten büyüğe (hızlı geri bildirim). İstemediğin satırı yorumla —
# ama asıl seçim launch/ içindeki .sh dosyalarıdır (bkz. README).
# `ctx` değerleri ÖLÇÜLDÜ (18 Ağu 2026, ctx_olcum.py — her aday context için
# sunucu gerçekten açılıp üretim yaptırıldı). Tavanlar dört kat fark ediyor:
# 26B-A4B'nin KV'si küçük (sliding_window 1024), 31B dense ise 32k'da doluyor.
MODELS = [
    {"file": "gemma-4-31B-it-qat-UD-Q4_K_XL.gguf",    # WP6 strict +116, common'da birinci
     "ctx": 32768},                                   # ölçüldü: 49152'de OOM (23431 MiB)
    {"file": "Qwen3.8-27B-Q4_K_M.gguf",               # yeni (5 Ağu 2026), bu koşuda ilk kez
     "ctx": 98304},                                   # ölçüldü: 131072'de OOM (23627 MiB)
    {"file": "Qwen_Qwen3.5-27B-Q4_K_M.gguf",          # WP6'nın en iyi Qwen'i (+100)
     "ctx": 98304},                                   # ölçüldü: 131072'de OOM (23621 MiB)
    {"file": "google_gemma-4-26B-A4B-it-Q5_K_M.gguf", # WP6 birincisi (+126)
     "ctx": 131072},                                  # ölçüldü: 131072 sığdı, 1,9 GB pay kaldı
]

# Diskte DURAN ama bu koşuya alınmayanlar (istersen satır ekleyip aç):
#   google_gemma-3-27b-it-Q4_K_L, Qwen3.6-27B-UD-Q4_K_XL,
#   gemma-4-26B-A4B-it-qat-UD-Q4_K_XL
#   google_gemma-4-31B-it-Q5_K_M → 22,6 GB, tek 4090'a SIĞMIYOR (WP6'da ölçüldü)
#
# Eski havuzun geri kalanı bu diskte YOK (RAID0 ile gitti; yeniden indirilmedi):
#   gemma-3-4b-it-Q8_0, google_gemma-4-12B-it-qat-q4_0, gemma-4-12B-agentic-v2-Q4_K_M,
#   google_gemma-4-E4B-it-bf16, Qwen_Qwen3.6-27B-Q4_K_M, Qwen_Qwen3.6-27B-Q5_K_M,
#   google_gemma-4-31B-it-Q4_K_M, Qwen_Qwen3.6-35B-A3B-Q4_K_M, Qwen3.5-35B-A3B-Q4_K_M

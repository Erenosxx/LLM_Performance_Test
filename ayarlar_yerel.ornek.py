# -*- coding: utf-8 -*-
"""Makineye özel yollar — KOPYALA ve düzenle:

    cp ayarlar_yerel.ornek.py ayarlar_yerel.py

`ayarlar_yerel.py` .gitignore'dadır; buradaki değerler depoya girmez.
Ortam değişkeni verilirse (LLM_MODELS_DIR / LLAMA_SERVER) o öncelikli olur.

Bu iki yolu doğru göstermek, projeyi çalıştırmak için yeterlidir.
"""

# .gguf model dosyalarının bulunduğu klasör
LLM_MODELS_DIR = "~/llm-models"

# llama.cpp'nin derlenmiş llama-server ikilisi
LLAMA_SERVER = "~/llama.cpp/build/bin/llama-server"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_models.py'nin İNGİLİZCE versiyonu — tüm sorular İngilizce sorulur (grader'lar aynı/dilden bağımsız).
Aynı modelleri İngilizce test eder; Türkçe sonuçlarla kıyaslayıp dil etkisini görmek için.

Kullanım:
    python run_models_En.py                 # launch/ içindeki modelleri İngilizce test et
    python run_models_En.py --only <dosya.gguf>
    python run_models_En.py --combined-selftest

Çıktı: Model_raporlari_EN/calisma_<tarih>/ (Türkçe çıktıdan AYRI klasör).
"""

import os

import llm_perf_test

# ÖNEMLİ: run_models'tan ÖNCE dili İngilizce'ye çevir ki QUESTIONS/CATEGORIES İngilizce bağlansın.
llm_perf_test.use_language("en")

import run_models  # noqa: E402  (use_language'dan SONRA import edilmeli)

# İngilizce çıktıyı ayrı klasöre yaz (Türkçe sonuçların üstüne yazma)
run_models.OUTPUT_BASE = os.path.join(run_models.BASE_DIR, "Model_raporlari_EN")


if __name__ == "__main__":
    print("== İNGİLİZCE TEST MODU (sorular İngilizce) ==")
    run_models.main()

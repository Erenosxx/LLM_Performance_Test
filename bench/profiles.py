# -*- coding: utf-8 -*-
"""Model profilleri: her model KENDİ kartındaki ayarla koşar.

NEDEN: Haziran-ağustos koşularında tüm modeller `temperature=0` (greedy) ile
test edildi. Bu, tekrarlanabilirlik için bilinçli bir tercihti ama üreticilerin
önerdiği rejimin dışındaydı — kart skorları o ayarlarla ölçülüyor ve akıl
yürüten modellerde greedy çözümleme döngüye girebiliyor (17 Ağu 2026: Qwen3.8
bir kodlama sorusunda 12,5 dakika düşünüp token tavanına çarptı, 0 aldı).

Buradaki değerler MODELİN KENDİ `generation_config.json` dosyasından alındı
(18 Ağu 2026'da HuggingFace'ten doğrulandı), tahmin değildir.

YÖNTEMSEL NOT: profil kullanıldığında modeller artık aynı koşullarda
koşmuyor. Sonuç "aynı koşulda hangisi iyi" değil, "her biri en iyi hâliyle ne
yapabiliyor" sorusunu cevaplar. Rapor her modelin parametresini yazar.
"""

import re

# Bilinmeyen model: eski davranış (deterministik) korunur.
VARSAYILAN_PROFIL = {
    "ad": "varsayılan (deterministik)",
    "temperature": 0.0,
    "top_p": 1.0,
    "top_k": 0,
    "repeat_penalty": 1.1,
    "reasoning_effort": None,
    "ctx": 32768,
    "kv_tipi": None,          # None = f16; "q8_0" uzun bağlam kademeleri için
}

# Sıra önemli: ilk eşleşen kural kazanır (qwen3.8 kuralı qwen3.x'ten önce gelmeli).
PROFIL_KURALLARI = [
    (r"qwen3\.8", {
        "ad": "Qwen3.8 (kart: düşünme kipi)",
        "temperature": 1.0, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.0,
        # xhigh VARSAYILAN ama ölçüldü: bir soruda 133 sn + 6000 token + cevap YOK.
        # medium'da aynı soru 14 sn / 590 token ve cevap üretiliyor.
        "reasoning_effort": "medium",
        "ctx": 32768,
    }),
    (r"qwen3\.[567]", {
        "ad": "Qwen3.5-3.7 (kart)",
        "temperature": 0.6, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.0,
        "reasoning_effort": None, "ctx": 32768,
    }),
    (r"gemma-4", {
        "ad": "Gemma 4 (kart)",
        "temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.0,
        "reasoning_effort": None, "ctx": 32768,
    }),
    (r"gemma-3", {
        "ad": "Gemma 3 (kart)",
        "temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.0,
        "reasoning_effort": None, "ctx": 32768,
    }),
]


def profil_bul(model_adi, deterministik=False):
    """Model adından profil çözer. `deterministik=True` ise eski (temp=0) rejim.

    Eşleşme model dosya adı üzerinden yapılır: "Qwen3.8-27B-Q4_K_M",
    "gemma-4-31B-it-qat-UD-Q4_K_XL" gibi.
    """
    if deterministik:
        return dict(VARSAYILAN_PROFIL, ad="deterministik (--deterministik)")
    ad = (model_adi or "").lower()
    for desen, profil in PROFIL_KURALLARI:
        if re.search(desen, ad):
            return dict(VARSAYILAN_PROFIL, **profil)
    return dict(VARSAYILAN_PROFIL)


def ornekleme_alanlari(profil, no_think=False):
    """İstek gövdesine eklenecek örnekleme alanları.

    llama.cpp OpenAI uçları top_p/top_k/repeat_penalty'yi doğrudan kabul eder;
    reasoning_effort ise jinja şablonuna `chat_template_kwargs` ile geçer
    (Qwen3.8 şablonunda tanımlı — 17 Ağu'da canlı doğrulandı).
    """
    p = profil or VARSAYILAN_PROFIL
    alanlar = {
        "temperature": p.get("temperature", 0.0),
        "top_p": p.get("top_p", 1.0),
        "repeat_penalty": p.get("repeat_penalty", 1.1),
    }
    if p.get("top_k"):
        alanlar["top_k"] = p["top_k"]
    ctk = {}
    if no_think:
        ctk["enable_thinking"] = False
    elif p.get("reasoning_effort"):
        ctk["reasoning_effort"] = p["reasoning_effort"]
    if ctk:
        alanlar["chat_template_kwargs"] = ctk
    return alanlar


def ozet(profil):
    """Rapor/log için tek satırlık gösterim."""
    p = profil or VARSAYILAN_PROFIL
    par = f"temp={p['temperature']} top_p={p['top_p']} top_k={p.get('top_k') or '-'} rep={p['repeat_penalty']}"
    if p.get("reasoning_effort"):
        par += f" effort={p['reasoning_effort']}"
    return f"{p.get('ad', '?')} · {par}"

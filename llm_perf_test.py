#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Performance Test  (tek model)
=================================

Bağlı olduğu OpenAI-uyumlu llama-server portundaki modeli otomatik tespit eder,
sabit görevleri sorar, süreleri (TTFT, toplam, tokens/sec) ve GPU/VRAM kullanımını
ölçer, kod/SQL/matematik cevaplarını OTOMATİK puanlar ve PDF rapor üretir.

Görevler (her model için SABİT):
  - 1 yaratıcılık sorusu  (otomatik puanlanmaz, insan değerlendirmesi)
  - 5 kod sorusu          (kolay -> zor, çalıştırılarak test edilir)
  - 5 SQL sorusu          (kolay -> zor, SQLite'ta çalıştırılır)
  - 5 matematik sorusu    (kolay -> zor, bilinen sonuçla karşılaştırılır)

NASIL PUANLANIR? (özet)
  KOD : modelin yazdığı fonksiyon ayrı bir Python sürecinde, sabit girdi/çıktı
        çiftlerine karşı çalıştırılır. Tüm girdilerde doğru çıktı verirse GEÇTİ.
  SQL : modelin sorgusu ile REFERANS sorgu aynı bellek-içi SQLite veritabanında
        çalıştırılır; satır sonuçları birebir aynıysa GEÇTİ (sütun adı önemsiz).
  MAT : cevaptaki sayılar/kesirler ayrıştırılır; bilinen doğru sonuç (tolerans
        dahilinde) bulunursa GEÇTİ.

Kullanım:
    python llm_perf_test.py --url http://localhost:8080
    python llm_perf_test.py --selftest
"""

import argparse
import datetime as _dt
import html
import json
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

try:
    import requests
except ImportError:
    sys.exit("HATA: 'requests' kurulu değil ->  pip install requests")

from agentic import AGENTIC_TASKS, agentic_loop


# ===========================================================================
#  SORULAR
# ===========================================================================

CATEGORIES = ["Yaratıcılık", "Kod", "SQL", "Matematik", "Hata Ayıklama", "Agentic"]

# --- Yaratıcılık (1) ---
CREATIVE_PROMPT = (
    "Sahibinin tüm anılarını saklayan ama her gece bir anıyı sessizce unutan "
    "eski bir duvar saati hakkında, en fazla 150 kelimelik özgün bir kısa öykü yaz. "
    "Öykü çarpıcı bir son cümleyle bitsin. Sadece öyküyü yaz, başlık veya açıklama ekleme."
)

# --- Kod (5): YARIŞMA SEVİYESİ (LeetCode medium-hard); tek fonksiyon + kenar durum testleri ---
_NO_EXP = (" SADECE istenen fonksiyonu içeren tek bir Python kod bloğu ver; "
           "açıklama, yorum satırı veya başka hiçbir metin EKLEME.")
CODE_QUESTIONS = [
    {"seviye": 1, "func": "roman_sayi",
     "prompt": "`roman_sayi(s)` fonksiyonunu yaz: geçerli bir Romen rakamı metnini (örn. 'MCMXCIV') "
               "tam sayıya çevirip döndürsün. Değerler: I=1, V=5, X=10, L=50, C=100, D=500, M=1000; "
               "çıkarma kuralları IV=4, IX=9, XL=40, XC=90, CD=400, CM=900 geçerlidir." + _NO_EXP,
     "tests": [[["III"], 3], [["IV"], 4], [["IX"], 9], [["LVIII"], 58], [["XL"], 40],
               [["MCMXCIV"], 1994], [["MMXXIV"], 2024], [["DCCCXC"], 890]]},
    {"seviye": 2, "func": "editleme_mesafesi",
     "prompt": "`editleme_mesafesi(a, b)` fonksiyonunu yaz: `a` metnini `b` metnine dönüştürmek için "
               "gereken en az tekil düzenleme (bir karakter ekleme, silme veya değiştirme) sayısını "
               "(Levenshtein uzaklığı) döndürsün." + _NO_EXP,
     "tests": [[["kitten", "sitting"], 3], [["", "abc"], 3], [["abc", "abc"], 0],
               [["horse", "ros"], 3], [["intention", "execution"], 5], [["", ""], 0], [["a", ""], 1]]},
    {"seviye": 3, "func": "kelime_bol",
     "prompt": "`kelime_bol(s, sozluk)` fonksiyonunu yaz: `s` metni, `sozluk` listesindeki kelimelerin "
               "(her biri sıfır veya daha fazla kez kullanılabilir) ardışık birleşimiyle TAM olarak "
               "oluşturulabiliyorsa True, aksi halde False döndürsün. Boş metin için True." + _NO_EXP,
     "tests": [[["leetcode", ["leet", "code"]], True], [["applepenapple", ["apple", "pen"]], True],
               [["catsandog", ["cats", "dog", "sand", "and", "cat"]], False], [["", ["a"]], True],
               [["aaaa", ["a", "aa"]], True], [["abcd", ["a", "abc", "b", "cd"]], True]]},
    {"seviye": 4, "func": "n_vezir",
     "prompt": "`n_vezir(n)` fonksiyonunu yaz: n×n satranç tahtasına, hiçbiri birbirini tehdit etmeyecek "
               "(aynı satır, sütun veya çaprazda iki vezir olmayacak) şekilde n vezirin kaç FARKLI "
               "şekilde yerleştirilebileceğini (N-Queens çözüm sayısını) döndürsün." + _NO_EXP,
     "tests": [[[1], 1], [[2], 0], [[3], 0], [[4], 2], [[5], 10], [[6], 4], [[8], 92]]},
    {"seviye": 5, "func": "en_uzun_artan_yol",
     "prompt": "`en_uzun_artan_yol(matris)` fonksiyonunu yaz: bir tam sayı matrisinde, her adımda "
               "yalnızca yukarı/aşağı/sol/sağ komşuya ve DAHA BÜYÜK bir değere geçerek oluşturulabilen "
               "en uzun kesin artan yolun hücre sayısını (uzunluğunu) döndürsün. Boş matris için 0." + _NO_EXP,
     "tests": [[[[[9, 9, 4], [6, 6, 8], [2, 1, 1]]], 4], [[[[3, 4, 5], [3, 2, 6], [2, 2, 1]]], 4],
               [[[[1]]], 1], [[[]], 0], [[[[1, 2, 3], [6, 5, 4], [7, 8, 9]]], 9]]},
    {"seviye": 6, "func": "regex_eslesme",
     "prompt": "`regex_eslesme(s, p)` fonksiyonunu yaz: `p` deseni `s` metninin TAMAMINI eşliyorsa "
               "True, aksi halde False döndürsün. Desende '.' herhangi tek bir karakteri, '*' ise "
               "kendinden ÖNCEKİ karakterin sıfır veya daha fazla tekrarını temsil eder." + _NO_EXP,
     "tests": [[["aa", "a"], False], [["aa", "a*"], True], [["ab", ".*"], True],
               [["aab", "c*a*b"], True], [["mississippi", "mis*is*p*."], False],
               [["", ""], True], [["", "a*"], True], [["abc", "abc"], True]]},
    {"seviye": 7, "func": "histogram_max_alan",
     "prompt": "`histogram_max_alan(yukseklikler)` fonksiyonunu yaz: genişlikleri 1 olan ve yükseklikleri "
               "verilen bitişik çubuklardan oluşan histogramda oluşturulabilecek EN BÜYÜK dikdörtgenin "
               "alanını döndürsün. Boş liste için 0." + _NO_EXP,
     "tests": [[[[2, 1, 5, 6, 2, 3]], 10], [[[2, 4]], 4], [[[]], 0], [[[1, 1, 1, 1]], 4],
               [[[5]], 5], [[[6, 2, 5, 4, 5, 1, 6]], 12]]},
    {"seviye": 8, "func": "kelime_merdiveni",
     "prompt": "`kelime_merdiveni(basla, bitir, sozluk)` fonksiyonunu yaz: `basla` kelimesinden `bitir` "
               "kelimesine, her adımda yalnızca TEK bir harf değiştirerek ve her ara kelime `sozluk` "
               "içinde bulunarak ulaşılabilen en kısa dönüşüm dizisindeki KELİME SAYISINI (baş ve son "
               "dahil) döndürsün. Ulaşılamıyorsa 0. Tüm kelimeler aynı uzunluktadır." + _NO_EXP,
     "tests": [[["hit", "cog", ["hot", "dot", "dog", "lot", "log", "cog"]], 5],
               [["hit", "cog", ["hot", "dot", "dog", "lot", "log"]], 0],
               [["a", "c", ["a", "b", "c"]], 2], [["hot", "dog", ["hot", "dog", "dot"]], 3],
               [["hit", "hit", ["hit"]], 1]]},
]

# --- SQL (5): YARIŞMA SEVİYESİ (self-join + pencere fonksiyonları); referans sorgu = ölçüt ---
SQL_SCHEMA_TEXT = (
    "Aşağıdaki iki SQLite tablosu mevcut:\n"
    "  calisanlar(id INTEGER, ad TEXT, departman TEXT, maas INTEGER, yonetici_id INTEGER)\n"
    "  satislar(id INTEGER, calisan_id INTEGER, tutar INTEGER, ay INTEGER)\n"
    "  -- yonetici_id, calisanlar.id'ye işaret eder (NULL olabilir). "
    "satislar.calisan_id -> calisanlar.id. ay: 1-12.\n\n"
)
SQL_SEED_CALISANLAR = [
    (1, "Ali", "Yazilim", 11000, None),
    (2, "Veli", "Yazilim", 9000, 1),
    (3, "Ayse", "Yazilim", 9500, 1),
    (4, "Fatma", "Satis", 8000, 1),
    (5, "Mehmet", "Satis", 8500, 4),
    (6, "Zeynep", "Satis", 7500, 4),
    (7, "Can", "Pazarlama", 6000, 1),
    (8, "Deniz", "Pazarlama", 6500, 7),
]
SQL_SEED_SATISLAR = [
    (1, 2, 1000, 1), (2, 3, 1500, 1),
    (3, 5, 2000, 2), (4, 6, 500, 2),
    (5, 2, 1000, 3), (6, 8, 800, 3),
]
SQL_QUESTIONS = [
    {"seviye": 1,
     "prompt": "Ortalama maaşı 7000'den BÜYÜK olan departmanları (departman, ort_maas) listele. "
               "Ortalama maaşa göre azalan sırala.",
     "ref": "SELECT departman, AVG(maas) FROM calisanlar GROUP BY departman "
            "HAVING AVG(maas) > 7000 ORDER BY AVG(maas) DESC"},
    {"seviye": 2,
     "prompt": "Maaşı, kendi yöneticisinin maaşından YÜKSEK olan çalışanların adlarını (ad) "
               "alfabetik (artan) sırala. (yonetici_id, aynı tablodaki bir çalışana işaret eder.)",
     "ref": "SELECT c.ad FROM calisanlar c JOIN calisanlar y ON c.yonetici_id = y.id "
            "WHERE c.maas > y.maas ORDER BY c.ad"},
    {"seviye": 3,
     "prompt": "Her departmandaki EN YÜKSEK maaşlı çalışanı (departman, ad) bul. Departman adına göre "
               "alfabetik sırala. (Her departmanda en yüksek maaş tektir.)",
     "ref": "SELECT departman, ad FROM (SELECT departman, ad, "
            "RANK() OVER (PARTITION BY departman ORDER BY maas DESC) rk FROM calisanlar) "
            "WHERE rk = 1 ORDER BY departman"},
    {"seviye": 4,
     "prompt": "Her departmanda maaşı en yüksek olan İLK 2 çalışanı (departman, ad, maas) listele. "
               "Departman adına göre alfabetik, departman içinde maaşa göre azalan sırala.",
     "ref": "SELECT departman, ad, maas FROM (SELECT departman, ad, maas, "
            "ROW_NUMBER() OVER (PARTITION BY departman ORDER BY maas DESC) rn FROM calisanlar) "
            "WHERE rn <= 2 ORDER BY departman, maas DESC"},
    {"seviye": 5,
     "prompt": "Her ay için, o aya kadarki (o ay dahil, önceki tüm aylar) KÜMÜLATİF toplam satış "
               "tutarını (ay, kumulatif_toplam) hesapla. Aya göre artan sırala.",
     "ref": "SELECT ay, SUM(aylik) OVER (ORDER BY ay) FROM "
            "(SELECT ay, SUM(tutar) AS aylik FROM satislar GROUP BY ay) ORDER BY ay"},
    {"seviye": 6,
     "prompt": "Yönetici zincirini kullanarak her çalışanın hiyerarşi seviyesini bul: en üst yönetici "
               "(yonetici_id NULL olan) seviye 1'dir; ona bağlı olanlar 2, onlara bağlı olanlar 3... "
               "Sonuç (ad, seviye); önce seviyeye göre artan, sonra ada göre artan sırala.",
     "ref": "WITH RECURSIVE h(id, ad, seviye) AS ("
            "SELECT id, ad, 1 FROM calisanlar WHERE yonetici_id IS NULL "
            "UNION ALL "
            "SELECT c.id, c.ad, h.seviye+1 FROM calisanlar c JOIN h ON c.yonetici_id = h.id) "
            "SELECT ad, seviye FROM h ORDER BY seviye, ad"},
    {"seviye": 7,
     "prompt": "Her ay için aylık toplam satışı VE bir önceki aya göre değişimi (fark) hesapla. "
               "Sonuç (ay, aylik_toplam, onceki_aya_gore_fark). Önceki ay yoksa önceki toplamı 0 kabul "
               "et. Aya göre artan sırala.",
     "ref": "SELECT ay, aylik, aylik - LAG(aylik, 1, 0) OVER (ORDER BY ay) FROM "
            "(SELECT ay, SUM(tutar) AS aylik FROM satislar GROUP BY ay) ORDER BY ay"},
    {"seviye": 8,
     "prompt": "Her departmanda maaşı 2. en yüksek olan çalışanı bul (ad, departman, maas). "
               "Departman adına göre alfabetik sırala. (Her departmanda 2. en yüksek maaş tektir.)",
     "ref": "SELECT ad, departman, maas FROM (SELECT ad, departman, maas, "
            "DENSE_RANK() OVER (PARTITION BY departman ORDER BY maas DESC) dr FROM calisanlar) "
            "WHERE dr = 2 ORDER BY departman"},
]

# --- Matematik (5): YARIŞMA SEVİYESİ (AIME tarzı), çok adımlı, tek tam-sayı cevaplı ---
MATH_SUFFIX = "\nTüm adımları göster ve cevabı EN SON satırda tam olarak `#### <sayı>` biçiminde ver."
MATH_QUESTIONS = [
    {"seviye": 1, "expected": 9.0,
     "prompt": "7 üssü 100 (yani 7^100) sayısının 13'e bölümünden kalan kaçtır?"},
    {"seviye": 2, "expected": 220.0,
     "prompt": "1 ile 1000 (her ikisi de dahil) arasında, 7'ye VEYA 11'e tam bölünen kaç tam sayı vardır?"},
    {"seviye": 3, "expected": 54.0,
     "prompt": "Rakamlarının toplamı tam olarak 10 olan kaç tane üç basamaklı pozitif tam sayı vardır?"},
    {"seviye": 4, "expected": 7.0,
     "prompt": "x² − y² = 2025 denklemini sağlayan kaç farklı POZİTİF tam sayı (x, y) çifti vardır?"},
    {"seviye": 5, "expected": 15.0,
     "prompt": "1/x + 1/y = 1/12 denklemini sağlayan kaç farklı POZİTİF tam sayı (x, y) çifti vardır? "
               "(x ve y'nin yer değiştirdiği durumlar farklı sayılır.)"},
    {"seviye": 6, "expected": 24.0,
     "prompt": "100! (100 faktöriyel) sayısının ondalık yazılışı kaç tane sıfır ile biter "
               "(sonundaki sıfır sayısı)?"},
    {"seviye": 7, "expected": 50.0,
     "prompt": "8 kişilik bir gruptan 3 kişilik bir komite seçilecek. Gruptaki belirli iki kişi "
               "(Ayşe ve Burak) aynı komitede BİRLİKTE bulunamaz. Kaç farklı komite oluşturulabilir?"},
    {"seviye": 8, "expected": 27.0,
     "prompt": "Üç farklı zar (her biri 1-6) atılıyor. Üzerlerinde görünen sayıların toplamının tam "
               "olarak 10 olduğu kaç farklı SIRALI sonuç (a, b, c) vardır?"},
]


# --- Referans çözümler (PDF'te "doğru cevap" olarak gösterilir) ---
CODE_SOLUTIONS = {
    "roman_sayi": (
        "def roman_sayi(s):\n"
        "    d = {'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}\n"
        "    toplam = 0\n"
        "    for i in range(len(s)):\n"
        "        if i + 1 < len(s) and d[s[i]] < d[s[i+1]]:\n"
        "            toplam -= d[s[i]]\n"
        "        else:\n"
        "            toplam += d[s[i]]\n"
        "    return toplam"),
    "editleme_mesafesi": (
        "def editleme_mesafesi(a, b):\n"
        "    m, n = len(a), len(b)\n"
        "    dp = [[0]*(n+1) for _ in range(m+1)]\n"
        "    for i in range(m+1): dp[i][0] = i\n"
        "    for j in range(n+1): dp[0][j] = j\n"
        "    for i in range(1, m+1):\n"
        "        for j in range(1, n+1):\n"
        "            if a[i-1] == b[j-1]:\n"
        "                dp[i][j] = dp[i-1][j-1]\n"
        "            else:\n"
        "                dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])\n"
        "    return dp[m][n]"),
    "kelime_bol": (
        "def kelime_bol(s, sozluk):\n"
        "    kelimeler = set(sozluk)\n"
        "    n = len(s)\n"
        "    dp = [False]*(n+1)\n"
        "    dp[0] = True\n"
        "    for i in range(1, n+1):\n"
        "        for j in range(i):\n"
        "            if dp[j] and s[j:i] in kelimeler:\n"
        "                dp[i] = True\n"
        "                break\n"
        "    return dp[n]"),
    "n_vezir": (
        "def n_vezir(n):\n"
        "    sayac = 0\n"
        "    cols, d1, d2 = set(), set(), set()\n"
        "    def yerlestir(satir):\n"
        "        nonlocal sayac\n"
        "        if satir == n:\n"
        "            sayac += 1\n"
        "            return\n"
        "        for s in range(n):\n"
        "            if s in cols or (satir - s) in d1 or (satir + s) in d2:\n"
        "                continue\n"
        "            cols.add(s); d1.add(satir - s); d2.add(satir + s)\n"
        "            yerlestir(satir + 1)\n"
        "            cols.discard(s); d1.discard(satir - s); d2.discard(satir + s)\n"
        "    yerlestir(0)\n"
        "    return sayac"),
    "en_uzun_artan_yol": (
        "def en_uzun_artan_yol(matris):\n"
        "    if not matris or not matris[0]:\n"
        "        return 0\n"
        "    m, n = len(matris), len(matris[0])\n"
        "    memo = [[0]*n for _ in range(m)]\n"
        "    def dfs(i, j):\n"
        "        if memo[i][j]:\n"
        "            return memo[i][j]\n"
        "        en = 1\n"
        "        for di, dj in ((1,0),(-1,0),(0,1),(0,-1)):\n"
        "            ni, nj = i+di, j+dj\n"
        "            if 0 <= ni < m and 0 <= nj < n and matris[ni][nj] > matris[i][j]:\n"
        "                en = max(en, 1 + dfs(ni, nj))\n"
        "        memo[i][j] = en\n"
        "        return en\n"
        "    return max(dfs(i, j) for i in range(m) for j in range(n))"),
    "regex_eslesme": (
        "def regex_eslesme(s, p):\n"
        "    m, n = len(s), len(p)\n"
        "    dp = [[False]*(n+1) for _ in range(m+1)]\n"
        "    dp[0][0] = True\n"
        "    for j in range(1, n+1):\n"
        "        if p[j-1] == '*':\n"
        "            dp[0][j] = dp[0][j-2]\n"
        "    for i in range(1, m+1):\n"
        "        for j in range(1, n+1):\n"
        "            if p[j-1] == '*':\n"
        "                dp[i][j] = dp[i][j-2] or (p[j-2] in (s[i-1], '.') and dp[i-1][j])\n"
        "            elif p[j-1] in (s[i-1], '.'):\n"
        "                dp[i][j] = dp[i-1][j-1]\n"
        "    return dp[m][n]"),
    "histogram_max_alan": (
        "def histogram_max_alan(yukseklikler):\n"
        "    h = list(yukseklikler) + [0]\n"
        "    stack = []\n"
        "    en = 0\n"
        "    for i in range(len(h)):\n"
        "        while stack and h[stack[-1]] > h[i]:\n"
        "            yuk = h[stack.pop()]\n"
        "            gen = i if not stack else i - stack[-1] - 1\n"
        "            en = max(en, yuk * gen)\n"
        "        stack.append(i)\n"
        "    return en"),
    "kelime_merdiveni": (
        "def kelime_merdiveni(basla, bitir, sozluk):\n"
        "    from collections import deque\n"
        "    kelimeler = set(sozluk)\n"
        "    if bitir not in kelimeler:\n"
        "        return 0\n"
        "    q = deque([(basla, 1)])\n"
        "    gorulen = {basla}\n"
        "    while q:\n"
        "        kelime, adim = q.popleft()\n"
        "        if kelime == bitir:\n"
        "            return adim\n"
        "        for i in range(len(kelime)):\n"
        "            for c in 'abcdefghijklmnopqrstuvwxyz':\n"
        "                yeni = kelime[:i] + c + kelime[i+1:]\n"
        "                if yeni in kelimeler and yeni not in gorulen:\n"
        "                    gorulen.add(yeni)\n"
        "                    q.append((yeni, adim + 1))\n"
        "    return 0"),
    # --- Hata Ayıklama referans (doğru) çözümleri ---
    "en_buyuk": (
        "def en_buyuk(nums):\n"
        "    enb = nums[0]\n"
        "    for x in nums:\n"
        "        if x > enb:\n"
        "            enb = x\n"
        "    return enb"),
    "carpim": (
        "def carpim(nums):\n"
        "    sonuc = 1\n"
        "    for x in nums:\n"
        "        sonuc *= x\n"
        "    return sonuc"),
    "tekrar_eden_var_mi": (
        "def tekrar_eden_var_mi(nums):\n"
        "    return len(set(nums)) != len(nums)"),
    "ortalama": (
        "def ortalama(nums):\n"
        "    if not nums:\n"
        "        return 0\n"
        "    return sum(nums) // len(nums)"),
    "fib": (
        "def fib(n):\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, a + b\n"
        "    return a"),
    "birlestir": (
        "def birlestir(a, b):\n"
        "    sonuc = []\n"
        "    i = j = 0\n"
        "    while i < len(a) and j < len(b):\n"
        "        if a[i] <= b[j]:\n"
        "            sonuc.append(a[i]); i += 1\n"
        "        else:\n"
        "            sonuc.append(b[j]); j += 1\n"
        "    sonuc.extend(a[i:])\n"
        "    sonuc.extend(b[j:])\n"
        "    return sonuc"),
    "max_alt_dizi_toplami": (
        "def max_alt_dizi_toplami(nums):\n"
        "    en = simdiki = nums[0]\n"
        "    for x in nums[1:]:\n"
        "        simdiki = max(x, simdiki + x)\n"
        "        en = max(en, simdiki)\n"
        "    return en"),
    "asal_mi": (
        "def asal_mi(n):\n"
        "    if n < 2:\n"
        "        return False\n"
        "    for i in range(2, int(n**0.5) + 1):\n"
        "        if n % i == 0:\n"
        "            return False\n"
        "    return True"),
    "tek_liste": (
        "def tek_liste(x):\n"
        "    return [x]"),
}
MATH_SOLUTIONS = {
    1: "Fermat: 7^12 ≡ 1 (mod 13). 100 = 12·8 + 4 → 7^100 ≡ 7^4 (mod 13). 7^4 = 2401 = 13·184 + 9 → kalan 9.",
    2: "İçerme-dışlama: ⌊1000/7⌋=142, ⌊1000/11⌋=90, ⌊1000/77⌋=12 → 142 + 90 − 12 = 220.",
    3: "a+b+c=10, 1≤a≤9, 0≤b,c≤9. a'=a−1 ile a'+b+c=9. Toplam C(11,2)=55, a'=9 olan 1 durum çıkar → 54.",
    4: "(x−y)(x+y)=2025=3⁴·5² (tek). Bölen sayısı 15; x−y<x+y için 45'ten küçük 7 bölen (1,3,5,9,15,25,27) → 7 çift.",
    5: "12(x+y)=xy → (x−12)(y−12)=144. 144'ün 15 pozitif böleni var; her biri bir (x,y) verir → 15.",
    6: "Sondaki sıfırlar = 5'in kuvvetleri: ⌊100/5⌋ + ⌊100/25⌋ = 20 + 4 = 24.",
    7: "Toplam C(8,3)=56. Ayşe+Burak birlikte: kalan 1 kişi C(6,1)=6. Geçerli = 56 − 6 = 50.",
    8: "3 zarla 10 toplamı: 3 pozitif parçaya ayırma C(9,2)=36, bir parça ≥7 olan 3·3=9 durum çıkar → 27.",
}


# --- Kod Okuma / Çıktı Tahmini (Kod kategorisine eklenir): kodu izle, çıktıyı söyle ---
OUTPUT_QUESTIONS = [
    {"seviye": 9, "expected": 55, "cozum": "1²+2²+3²+4²+5² = 1+4+9+16+25 = 55.",
     "code": "x = 0\nfor i in range(1, 6):\n    x += i * i\nprint(x)"},
    {"seviye": 10, "expected": 30, "cozum": "f(4)=24, f(3)=6 → 24 + 6 = 30.",
     "code": "def f(n):\n    if n == 0:\n        return 1\n    return n * f(n - 1)\nprint(f(4) + f(3))"},
    {"seviye": 11, "expected": 5, "cozum": "'abracadabra' içinde 'a' harfi 5 kez geçer.",
     "code": "d = {}\nfor c in 'abracadabra':\n    d[c] = d.get(c, 0) + 1\nprint(d['a'])"},
]

# --- Hata Ayıklama branşı: bozuk kod verilir, model düzeltir, düzeltilmiş kod test edilir ---
DEBUG_QUESTIONS = [
    {"seviye": 1, "func": "en_buyuk",
     "spec": "bir tam sayı listesindeki EN BÜYÜK elemanı döndürmeli",
     "buggy": "def en_buyuk(nums):\n    enb = nums[0]\n    for i in range(len(nums) - 1):\n"
              "        if nums[i] > enb:\n            enb = nums[i]\n    return enb",
     "tests": [[[[3, 1, 2]], 3], [[[1, 2, 5]], 5], [[[5]], 5], [[[1, 2, 3, 9]], 9], [[[4, 4, 4]], 4]]},
    {"seviye": 2, "func": "carpim",
     "spec": "listedeki tüm elemanların ÇARPIMINI döndürmeli (boş liste için 1)",
     "buggy": "def carpim(nums):\n    sonuc = 0\n    for x in nums:\n        sonuc *= x\n    return sonuc",
     "tests": [[[[1, 2, 3, 4]], 24], [[[5]], 5], [[[]], 1], [[[2, 2, 2]], 8], [[[3, 0, 9]], 0]]},
    {"seviye": 3, "func": "tekrar_eden_var_mi",
     "spec": "listede en az bir TEKRAR EDEN eleman varsa True, yoksa False döndürmeli",
     "buggy": "def tekrar_eden_var_mi(nums):\n    for i in range(len(nums)):\n"
              "        for j in range(len(nums)):\n            if nums[i] == nums[j]:\n"
              "                return True\n    return False",
     "tests": [[[[1, 2, 3]], False], [[[1, 2, 1]], True], [[[5]], False], [[[]], False],
               [[[4, 5, 6, 4]], True]]},
    {"seviye": 4, "func": "ortalama",
     "spec": "sayıların tam sayı ortalamasını (aşağı yuvarlanmış) döndürmeli; BOŞ liste için 0",
     "buggy": "def ortalama(nums):\n    return sum(nums) // len(nums)",
     "tests": [[[[2, 4, 6]], 4], [[[1, 2]], 1], [[[]], 0], [[[10]], 10], [[[1, 2, 3, 4]], 2]]},
    {"seviye": 5, "func": "fib",
     "spec": "n. Fibonacci sayısını döndürmeli (fib(0)=0, fib(1)=1, fib(2)=1, fib(3)=2, ...)",
     "buggy": "def fib(n):\n    if n <= 1:\n        return n\n    a, b = 0, 1\n"
              "    for _ in range(n + 1):\n        a, b = b, a + b\n    return a",
     "tests": [[[0], 0], [[1], 1], [[2], 1], [[7], 13], [[10], 55], [[12], 144]]},
    {"seviye": 6, "func": "birlestir",
     "spec": "iki ARTAN SIRALI listeyi tek bir artan sıralı listede birleştirmeli (merge)",
     "buggy": "def birlestir(a, b):\n    sonuc = []\n    i = j = 0\n"
              "    while i < len(a) and j < len(b):\n        if a[i] <= b[j]:\n"
              "            sonuc.append(a[i]); i += 1\n        else:\n"
              "            sonuc.append(b[j]); j += 1\n    return sonuc",
     "tests": [[[[1, 3, 5], [2, 4, 6]], [1, 2, 3, 4, 5, 6]], [[[1, 2], []], [1, 2]],
               [[[], [3]], [3]], [[[1], [1]], [1, 1]], [[[], []], []]]},
    {"seviye": 7, "func": "max_alt_dizi_toplami",
     "spec": "bir tam sayı listesinde BİTİŞİK (en az bir elemanlı) bir alt dizinin alabileceği en "
             "büyük toplamı döndürmeli (Kadane algoritması)",
     "buggy": "def max_alt_dizi_toplami(nums):\n    en = simdiki = 0\n    for x in nums:\n"
              "        simdiki = max(x, simdiki + x)\n        en = max(en, simdiki)\n    return en",
     "tests": [[[[-2, 1, -3, 4, -1, 2, 1, -5, 4]], 6], [[[1, 2, 3]], 6], [[[-1, -2, -3]], -1],
               [[[5]], 5], [[[-5]], -5]]},
    {"seviye": 8, "func": "asal_mi",
     "spec": "n bir ASAL sayı ise True, değilse False döndürmeli (0, 1 ve negatifler asal değildir)",
     "buggy": "def asal_mi(n):\n    for i in range(2, int(n**0.5) + 1):\n"
              "        if n % i == 0:\n            return False\n    return True",
     "tests": [[[2], True], [[3], True], [[4], False], [[17], True], [[9], False],
               [[1], False], [[0], False]]},
    {"seviye": 9, "func": "tek_liste",
     "spec": "verilen elemanı içeren TEK ELEMANLI yeni bir liste döndürmeli; her çağrı BAĞIMSIZ olmalı "
             "(önceki çağrılardan etkilenmemeli)",
     "buggy": "def tek_liste(x, sonuc=[]):\n    sonuc.append(x)\n    return sonuc",
     "tests": [[[1], [1]], [[2], [2]], [[5], [5]], [[9], [9]]]},
]


def build_questions():
    """Tüm soruları tek bir düz listede üretir (kategori, seviye, prompt, grader)."""
    q = []
    q.append({"key": "yaraticilik_1", "kategori": "Yaratıcılık", "seviye": 1,
              "baslik": "Yaratıcılık", "prompt": CREATIVE_PROMPT, "grader": None,
              "kriter": "Otomatik puanlanmaz. İnsan değerlendirmesi: özgünlük, dil akıcılığı, "
                        "kurgu, kısıt uyumu (≤150 kelime + çarpıcı son cümle)."})
    for c in CODE_QUESTIONS:
        q.append({"key": f"kod_{c['seviye']}", "kategori": "Kod", "seviye": c["seviye"],
                  "baslik": f"Kod S{c['seviye']} ({c['func']})", "prompt": c["prompt"],
                  "grader": ("code", {"func": c["func"], "tests": c["tests"],
                                      "cozum": CODE_SOLUTIONS.get(c["func"], "")}),
                  "kriter": f"{len(c['tests'])} girdi/çıktı çiftiyle çalıştırılır."})
    for s in SQL_QUESTIONS:
        q.append({"key": f"sql_{s['seviye']}", "kategori": "SQL", "seviye": s["seviye"],
                  "baslik": f"SQL S{s['seviye']}", "prompt": SQL_SCHEMA_TEXT + s["prompt"],
                  "grader": ("sql", {"ref": s["ref"]}),
                  "kriter": "Referans sorgu ile aynı sonucu verirse geçer."})
    for m in MATH_QUESTIONS:
        q.append({"key": f"mat_{m['seviye']}", "kategori": "Matematik", "seviye": m["seviye"],
                  "baslik": f"Matematik S{m['seviye']}", "prompt": m["prompt"] + MATH_SUFFIX,
                  "grader": ("math", {"expected": m["expected"],
                                      "cozum": MATH_SOLUTIONS.get(m["seviye"], "")}),
                  "kriter": f"Beklenen sonuç: {m['expected']:g}."})
    # Kod Okuma / çıktı tahmini (Kod kategorisinde, ama math grader ile sayı kıyası)
    for o in OUTPUT_QUESTIONS:
        q.append({"key": f"kodoku_{o['seviye']}", "kategori": "Kod", "seviye": o["seviye"],
                  "baslik": f"Kod-Okuma S{o['seviye']}",
                  "prompt": "Aşağıdaki Python kodu çalıştırıldığında ekrana ne YAZDIRIR? Adım adım izle "
                            "ve cevabı EN SON `#### <sayı>` biçiminde ver:\n```python\n" + o["code"] + "\n```",
                  "grader": ("math", {"expected": float(o["expected"]), "cozum": o["cozum"]}),
                  "kriter": f"Beklenen çıktı: {o['expected']}."})
    # Hata Ayıklama branşı (bozuk kod -> düzelt -> code grader ile çalıştır)
    for dq in DEBUG_QUESTIONS:
        q.append({"key": f"hata_{dq['seviye']}", "kategori": "Hata Ayıklama", "seviye": dq["seviye"],
                  "baslik": f"Hata Ayıklama S{dq['seviye']} ({dq['func']})",
                  "prompt": f"Aşağıdaki `{dq['func']}` fonksiyonu şunu yapmalı: {dq['spec']}. Ancak bir "
                            "HATA içeriyor. Hatayı bul ve DÜZELTİLMİŞ fonksiyonun TAMAMINI tek bir Python "
                            "kod bloğunda ver; açıklama veya yorum YAZMA.\n```python\n" + dq["buggy"] + "\n```",
                  "grader": ("code", {"func": dq["func"], "tests": dq["tests"],
                                      "cozum": CODE_SOLUTIONS.get(dq["func"], "")}),
                  "kriter": f"{len(dq['tests'])} test ile düzeltme doğrulanır."})
    # Agentic branşı (çok-turlu araç kullanımı; loop run_questions'ta sürülür)
    for t in AGENTIC_TASKS:
        gtype = t["grader_type"]  # "math" -> sayı, "metin" -> isim eşleşmesi
        spec = {"expected": t["expected"], "cozum": t["cozum"]}
        q.append({"key": t["key"], "kategori": "Agentic", "seviye": t["seviye"],
                  "baslik": t["baslik"], "prompt": t["user"], "agentic": t,
                  "grader": (gtype, spec),
                  "kriter": "Araçlarla veri toplayıp doğru çıkarımı yapan model geçer."})
    return q


QUESTIONS = build_questions()


# ===========================================================================
#  OTOMATİK PUANLAMA
# ===========================================================================

def _extract_block(text, lang_hints=()):
    fences = re.findall(r"```(?:[a-zA-Z0-9_+-]*)\n(.*?)```", text, re.DOTALL)
    if fences:
        for blk in fences:
            for h in lang_hints:
                if h.lower() in blk.lower():
                    return blk.strip()
        return fences[0].strip()
    return text.strip()


def grade_code(answer, func, tests):
    """-> (passed, detay, output_info). output_info modelin her girdideki gerçek çıktısını içerir."""
    code = _extract_block(answer, lang_hints=(f"def {func}", "def "))
    if f"def {func}" not in code:
        return False, f"`{func}` fonksiyonu bulunamadı.", None
    harness = code + "\n\nimport json as _json\n_T = _json.loads(r'''" + json.dumps(tests) + "''')\n"
    harness += textwrap.dedent(f"""
        _out = []
        for _args, _exp in _T:
            try:
                _g = {func}(*_args)
                _out.append({{"got": repr(_g), "ok": _g == _exp}})
            except Exception as _e:
                _out.append({{"got": "HATA: " + str(_e), "ok": False}})
        print("RESULTS")
        print(_json.dumps(_out, ensure_ascii=False))
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(harness)
        path = f.name
    try:
        proc = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return False, "Zaman aşımı (>15sn) — muhtemelen sonsuz döngü.", None
    finally:
        if os.path.exists(path):
            os.unlink(path)
    out = proc.stdout or ""
    if proc.returncode != 0 or "RESULTS" not in out:
        return False, "Çalıştırma hatası:\n" + (proc.stderr or "")[:600], None
    try:
        outs = json.loads(out.split("RESULTS", 1)[1].strip())
    except Exception:
        return False, "Çıktı ayrıştırılamadı.", None
    rows, okc = [], 0
    for (args, exp), o in zip(tests, outs):
        argstr = ", ".join(repr(a) for a in args)
        ok = bool(o.get("ok"))
        okc += 1 if ok else 0
        rows.append({"call": f"{func}({argstr})", "expected": repr(exp), "got": o.get("got", ""), "ok": ok})
    passed = okc == len(tests)
    return passed, f"{okc}/{len(tests)} test geçti.", {"type": "code", "rows": rows}


def seed_sql_db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE calisanlar(id INTEGER, ad TEXT, departman TEXT, maas INTEGER, yonetici_id INTEGER)")
    con.execute("CREATE TABLE satislar(id INTEGER, calisan_id INTEGER, tutar INTEGER, ay INTEGER)")
    con.executemany("INSERT INTO calisanlar VALUES (?,?,?,?,?)", SQL_SEED_CALISANLAR)
    con.executemany("INSERT INTO satislar VALUES (?,?,?,?)", SQL_SEED_SATISLAR)
    return con


def grade_sql(answer, ref):
    """-> (passed, detay, output_info). output_info beklenen ve modelin sorgu sonucunu içerir."""
    con = seed_sql_db()
    try:
        expected = [tuple(r) for r in con.execute(ref).fetchall()]
    except Exception as e:
        con.close()
        return False, f"Referans sorgu hatası: {e}", None
    sql = _extract_block(answer, lang_hints=("select", "with"))
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    sels = [s for s in statements if s.lower().startswith(("select", "with"))]
    query = sels[-1] if sels else (statements[-1] if statements else sql)
    info = {"type": "sql", "expected": expected, "got": None}
    if "select" not in query.lower():
        con.close()
        info["got"] = "(geçerli SELECT sorgusu bulunamadı)"
        return False, "Geçerli bir SELECT sorgusu bulunamadı.", info
    try:
        got = [tuple(r) for r in con.execute(query).fetchall()]
    except Exception as e:
        con.close()
        info["got"] = f"HATA: {e}"
        return False, f"SQL çalıştırma hatası: {e}", info
    con.close()
    info["got"] = got
    passed = got == expected
    return passed, f"Sonuç {'doğru' if passed else 'yanlış'} ({len(got)} satır).", info


def _to_float(tok):
    s = tok.rstrip(".,").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def grade_math(answer, expected, tol=0.5):
    # 1) Belirgin final işareti: `#### <sayı>` veya \boxed{<sayı>} -> kesin ölçüm
    marks = (re.findall(r"####\s*\$?(-?\d[\d.,]*)", answer)
             or re.findall(r"\\boxed\{\s*(-?\d[\d.,]*)\s*\}", answer))
    final = _to_float(marks[-1]) if marks else None
    # 2) yedek: tüm sayı/kesir adayları
    cands = []
    for a, b in re.findall(r"(\d+)\s*/\s*(\d+)", answer):
        try:
            cands.append(int(a) / int(b))
        except ZeroDivisionError:
            pass
    for n in re.findall(r"-?\d[\d.,]*", answer):
        v = _to_float(n)
        if v is not None:
            cands.append(v)
    info = {"type": "math", "expected": expected, "final": final, "found": cands[:15]}
    if final is not None:
        ok = abs(final - expected) < tol
        return ok, f"#### sonucu: {final:g} (beklenen {expected:g}) → {'doğru' if ok else 'yanlış'}", info
    # işaret yoksa daha hoşgörülü: herhangi bir sayı eşleşirse
    ok = any(abs(c - expected) < tol for c in cands)
    msg = (f"Doğru sonuç (≈{expected:g}) bulundu (#### işareti yoktu)." if ok
           else f"Beklenen {expected:g} bulunamadı. Görülen: {cands[:12]}")
    return ok, msg, info


def _norm_metin(s):
    return re.sub(r"[^a-z0-9çğıöşü]", "", str(s).lower())


def grade_text(answer, expected):
    """Metin cevabı: `#### <cevap>` işaretinden ya da son satırdan al, normalize edip kıyasla."""
    marks = re.findall(r"####\s*(.+)", answer)
    if marks:
        cand = marks[-1].strip()
    else:
        satirlar = [s for s in answer.strip().splitlines() if s.strip()]
        cand = satirlar[-1].strip() if satirlar else ""
    e = _norm_metin(expected)
    c = _norm_metin(cand)
    ok = bool(e) and (c == e or e in c)
    info = {"type": "metin", "expected": expected, "got": cand[:80]}
    return ok, f"Beklenen '{expected}', bulunan '{cand[:60]}' → {'doğru' if ok else 'yanlış'}", info


def grade_answer(question, text):
    """Bir sorunun cevabını değerlendirir -> (passed|None, detay, output_info)."""
    g = question["grader"]
    if not g:
        return None, "", None
    gtype, spec = g
    if text.startswith("[İSTEK HATASI"):
        return False, "Modelden cevap alınamadı.", None
    if not text.strip():
        return False, "Model boş/eksik cevap verdi (token limiti veya düşünme aşaması).", None
    try:
        if gtype == "code":
            return grade_code(text, spec["func"], spec["tests"])
        if gtype == "sql":
            return grade_sql(text, spec["ref"])
        if gtype == "math":
            return grade_math(text, spec["expected"])
        if gtype == "metin":
            return grade_text(text, spec["expected"])
    except Exception as e:
        return False, f"Değerlendirici hatası: {e}", None
    return None, "", None


def correct_answer_text(question):
    """Bir sorunun 'doğru cevabı / beklenen sonucu' (PDF'te gösterilir)."""
    g = question["grader"]
    if not g:
        return question.get("kriter", "")
    gtype, spec = g
    if gtype == "code":
        ex = []
        for args, exp in spec["tests"]:
            argstr = ", ".join(repr(a) for a in args)
            ex.append(f"{spec['func']}({argstr}) = {exp!r}")
        return ("Referans çözüm:\n" + spec.get("cozum", "") +
                "\n\nBeklenen çıktılar:\n" + "\n".join(ex))
    if gtype == "sql":
        try:
            con = seed_sql_db()
            rows = [tuple(r) for r in con.execute(spec["ref"]).fetchall()]
            con.close()
            rowtxt = "\n".join(str(r) for r in rows)
        except Exception as e:
            rowtxt = f"(hesaplanamadı: {e})"
        return "Referans sorgu:\n" + spec["ref"] + "\n\nBeklenen sonuç:\n" + rowtxt
    if gtype == "math":
        return f"Doğru sonuç: {spec['expected']:g}\nÇözüm: {spec.get('cozum', '')}"
    if gtype == "metin":
        return f"Doğru cevap: {spec['expected']}\nÇözüm: {spec.get('cozum', '')}"
    return ""


def avg_tokens_per_sec(results):
    """Toplam üretilen token / toplam üretim süresi (gerçek ortalama verim)."""
    toks = sum(r.get("completion_tokens", 0) for r in results)
    gen = sum(max(0.0, r.get("total", 0) - r.get("ttft", 0)) for r in results if r.get("total"))
    return toks / gen if gen > 0 else 0.0


def gpu_util_stats(gpu_summary):
    """gpu_summary -> (ortalama util %, maks util %). Veri yoksa (0,0)."""
    if not gpu_summary:
        return 0.0, 0.0
    avgs = [s["util_avg"] for s in gpu_summary.values()]
    maxs = [s["util_max"] for s in gpu_summary.values()]
    return (statistics.mean(avgs), max(maxs))


def category_summary(results):
    out = {}
    for cat in CATEGORIES:
        items = [r for r in results if r["kategori"] == cat]
        graded = [r for r in items if r["passed"] is not None]
        out[cat] = {
            "passed": sum(1 for r in graded if r["passed"]),
            "graded": len(graded),
            "items": len(items),
            "time": sum(r["total"] for r in items),
        }
    return out


# ===========================================================================
#  MODEL TESPİTİ
# ===========================================================================

def _dig(obj, *keys):
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and not isinstance(obj[k], (dict, list)):
                return obj[k]
        for v in obj.values():
            r = _dig(v, *keys)
            if r is not None:
                return r
    return None


def detect_model(base_url, timeout=10):
    info = {"name": None, "model_path": None, "params": {}}
    try:
        r = requests.get(base_url + "/props", timeout=timeout)
        if r.ok:
            props = r.json()
            info["model_path"] = _dig(props, "model_path", "model")
            for key in ("n_ctx", "n_predict", "temperature", "top_k", "top_p",
                        "min_p", "repeat_penalty", "seed", "n_slots", "total_slots"):
                v = _dig(props, key)
                if v is not None:
                    info["params"][key] = v
            bi = _dig(props, "build_info")
            if bi:
                info["params"]["build_info"] = bi
    except Exception as e:
        print(f"[uyarı] /props okunamadı: {e}")
    try:
        r = requests.get(base_url + "/v1/models", timeout=timeout)
        if r.ok:
            data = r.json().get("data", [])
            if data:
                mid = data[0].get("id")
                if mid:
                    info["params"].setdefault("served_model_id", mid)
                    if not info["model_path"]:
                        info["model_path"] = mid
    except Exception as e:
        print(f"[uyarı] /v1/models okunamadı: {e}")
    raw = info["model_path"] or info["params"].get("served_model_id") or "bilinmeyen_model"
    name = re.sub(r"\.gguf$", "", os.path.basename(str(raw)), flags=re.IGNORECASE)
    info["name"] = name or "bilinmeyen_model"
    info["served_id"] = info["params"].get("served_model_id") or info["name"]
    return info


# ===========================================================================
#  GPU İZLEME
# ===========================================================================

class GpuMonitor:
    def __init__(self, interval=0.5):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.samples = {}
        self.available = self._check()

    def _check(self):
        try:
            subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def _poll_once(self):
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip()
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            idx, name, mem, util = parts
            d = self.samples.setdefault(int(idx), {"mem": [], "util": [], "name": name})
            try:
                d["mem"].append(float(mem))
                d["util"].append(float(util))
            except ValueError:
                pass

    def _run(self):
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self):
        if self.available:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def summary(self):
        res = {}
        for idx, d in sorted(self.samples.items()):
            if not d["mem"]:
                continue
            res[idx] = {"name": d["name"], "mem_min": min(d["mem"]), "mem_max": max(d["mem"]),
                        "mem_avg": statistics.mean(d["mem"]), "util_min": min(d["util"]),
                        "util_max": max(d["util"]), "util_avg": statistics.mean(d["util"]),
                        "n": len(d["mem"])}
        return res


# ===========================================================================
#  LLM İSTEMCİSİ
# ===========================================================================

def ask_llm(base_url, model_id, prompt, temperature, max_tokens, timeout=600, no_think=False):
    url = base_url + "/v1/chat/completions"
    payload = {"model": model_id, "messages": [{"role": "user", "content": prompt}],
               "temperature": temperature, "max_tokens": max_tokens, "stream": True,
               "stream_options": {"include_usage": True}}
    if no_think:
        # Düşünmeyi (reasoning) destekleyen jinja şablonları için
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    t0 = time.perf_counter()
    ttft = None
    chunks = []            # nihai cevap (content)
    reason_chunks = []     # düşünme (reasoning_content)
    completion_tokens = None
    finish_reason = None
    with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        for raw_b in resp.iter_lines():
            if not raw_b:
                continue
            raw = raw_b.decode("utf-8", errors="replace") if isinstance(raw_b, bytes) else raw_b
            if raw.startswith("data: "):
                raw = raw[6:]
            if raw.strip() == "[DONE]":
                break
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if choices:
                delta = choices[0].get("delta", {})
                piece = delta.get("content")
                rpiece = delta.get("reasoning_content")
                if piece:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    chunks.append(piece)
                if rpiece:
                    if ttft is None:           # ilk token düşünme tokenı da olabilir
                        ttft = time.perf_counter() - t0
                    reason_chunks.append(rpiece)
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]
            usage = obj.get("usage")
            if usage and usage.get("completion_tokens"):
                completion_tokens = usage["completion_tokens"]
    total = time.perf_counter() - t0
    text = "".join(chunks)
    reasoning = "".join(reason_chunks)
    if completion_tokens is None:
        completion_tokens = max(1, round((len(text) + len(reasoning)) / 4))
    gen_time = max(1e-6, total - (ttft or 0))
    return {"text": text, "reasoning": reasoning, "finish_reason": finish_reason,
            "ttft": ttft if ttft is not None else total, "total": total,
            "completion_tokens": completion_tokens, "tokens_per_sec": completion_tokens / gen_time}


# ===========================================================================
#  PDF
# ===========================================================================

def _register_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    base = "/usr/share/fonts/truetype/dejavu/"
    fallback = base + "DejaVuSansCondensed.ttf"
    for name, path in {"DejaVu": base + "DejaVuSans.ttf",
                       "DejaVu-Bold": base + "DejaVuSans-Bold.ttf",
                       "DejaVuMono": base + "DejaVuSansMono.ttf"}.items():
        try:
            pdfmetrics.registerFont(TTFont(name, path if os.path.exists(path) else fallback))
        except Exception:
            pass
    return "DejaVu", "DejaVu-Bold", "DejaVuMono"


def _para(text):
    text = html.escape(text)
    out = []
    for ln in text.split("\n"):
        stripped = ln.lstrip(" ")
        out.append("&nbsp;" * (len(ln) - len(stripped)) + stripped)
    return "<br/>".join(out)


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    f, fb, fm = _register_fonts()
    base = getSampleStyleSheet()
    S = {
        "H1": ParagraphStyle("H1", parent=base["Title"], fontName=fb, fontSize=18, spaceAfter=6),
        "H2": ParagraphStyle("H2", fontName=fb, fontSize=13, spaceBefore=12, spaceAfter=4,
                             textColor=colors.HexColor("#1a3c5e")),
        "H3": ParagraphStyle("H3", fontName=fb, fontSize=10.5, spaceBefore=9, spaceAfter=3),
        "BODY": ParagraphStyle("BODY", fontName=f, fontSize=9.5, leading=13, spaceBefore=4, spaceAfter=2),
        "SMALL": ParagraphStyle("SMALL", fontName=f, fontSize=8, leading=10, textColor=colors.grey,
                                spaceBefore=2),
        "CODE": ParagraphStyle("CODE", fontName=fm, fontSize=8, leading=11,
                               backColor=colors.HexColor("#f4f4f4"), borderPadding=5,
                               spaceBefore=4, spaceAfter=8),
    }
    return (f, fb, fm), S


def render_output_block(output_info, fonts, S):
    """Modelin kodunun/sorgusunun GERÇEK çıktısını (+ beklenen) gösteren flowable'lar."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Table, TableStyle, Paragraph
    f, fb, fm = fonts
    out = []
    if not output_info:
        return out
    if output_info["type"] == "code":
        # Hücreler Paragraph -> uzun metin sütun içinde satır kaydırır (taşma olmaz)
        cell = ParagraphStyle("cell", fontName=fm, fontSize=7, leading=8.5, wordWrap="CJK")
        head = ParagraphStyle("hcell", fontName=fb, fontSize=7.5, leading=9, textColor=colors.white)

        def C(x):
            return Paragraph(html.escape(str(x)), cell)

        data = [[Paragraph("Çağrı", head), Paragraph("Beklenen çıktı", head),
                 Paragraph("Modelin çıktısı", head), Paragraph("", head)]]
        styles = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
                  ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                  ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                  ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        for i, r in enumerate(output_info["rows"], 1):
            mark = ('<font color="#15803d">✔</font>' if r["ok"]
                    else '<font color="#b91c1c">✘</font>')
            data.append([C(r["call"]), C(r["expected"]), C(str(r["got"])[:120]),
                         Paragraph(mark, cell)])
            if not r["ok"]:
                styles.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fdecec")))
        t = Table(data, colWidths=[54*mm, 38*mm, 52*mm, 8*mm], repeatRows=1)
        t.setStyle(TableStyle(styles))
        out.append(Paragraph("<b>Modelin kodunun çıktısı (çalıştırıldı):</b>", S["BODY"]))
        out.append(t)
    elif output_info["type"] == "sql":
        got = output_info["got"]
        exp = output_info["expected"]
        gtxt = "\n".join(str(r) for r in got) if isinstance(got, list) else str(got)
        etxt = "\n".join(str(r) for r in exp) if isinstance(exp, list) else str(exp)
        out.append(Paragraph("<b>Beklenen sonuç:</b>", S["BODY"]))
        out.append(Paragraph(_para(etxt), S["CODE"]))
        out.append(Paragraph("<b>Modelin sorgu çıktısı:</b>", S["BODY"]))
        out.append(Paragraph(_para(gtxt), S["CODE"]))
    return out


def _verdict_tag(passed):
    return {True: '<font color="#15803d">GEÇTİ ✔</font>',
            False: '<font color="#b91c1c">KALDI ✘</font>', None: "—"}[passed]


def build_pdf(out_path, model_info, gpu_summary, results, run_meta):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable)
    (f, fb, fm), S = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm,
                            topMargin=15*mm, bottomMargin=15*mm, title="LLM Performans Raporu")
    el = [Paragraph("LLM Performans Test Raporu", S["H1"]),
          Paragraph(f"Model: <b>{html.escape(model_info['name'])}</b>", S["BODY"]),
          Paragraph(f"Sunucu: {html.escape(run_meta['url'])} &nbsp;|&nbsp; {run_meta['timestamp']} "
                    f"&nbsp;|&nbsp; temperature={run_meta['temperature']} &nbsp;|&nbsp; "
                    f"max_tokens={run_meta['max_tokens']}", S["SMALL"]),
          HRFlowable(width="100%", color=colors.grey, spaceBefore=6, spaceAfter=6)]

    # Kategori skor tablosu
    el.append(Paragraph("Skor & Süre Özeti", S["H2"]))
    cs = category_summary(results)
    head = ["Kategori", "Skor", "Süre (s)"]
    rows = [head]
    for cat in CATEGORIES:
        c = cs[cat]
        skor = "—" if c["graded"] == 0 else f"{c['passed']}/{c['graded']}"
        rows.append([cat, skor, f"{c['time']:.1f}"])
    auto_p = sum(cs[c]["passed"] for c in CATEGORIES)
    auto_n = sum(cs[c]["graded"] for c in CATEGORIES)
    rows.append(["TOPLAM (otomatik)", f"{auto_p}/{auto_n}",
                 f"{sum(c['total'] for c in results):.1f}"])
    t = Table(rows, colWidths=[60*mm, 40*mm, 40*mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), fb), ("FONTNAME", (0, -1), (-1, -1), fb),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2f6")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc"))]))
    el.append(t)
    el.append(Paragraph("<b>Sütunlar:</b> Skor = geçilen / otomatik değerlendirilen soru sayısı · "
                        "Süre = o kategorideki tüm soruların toplam yanıt süresi (saniye).", S["SMALL"]))

    # GPU
    el.append(Paragraph("GPU / VRAM Kullanımı", S["H2"]))
    if gpu_summary:
        grows = [["GPU", "Model", "VRAM min/ort/maks (GB)", "Util min/ort/maks (%)"]]
        for idx, s in gpu_summary.items():
            grows.append([str(idx), s["name"],
                          f"{s['mem_min']/1024:.1f}/{s['mem_avg']/1024:.1f}/{s['mem_max']/1024:.1f}",
                          f"{s['util_min']:.0f}/{s['util_avg']:.0f}/{s['util_max']:.0f}"])
        gt = Table(grows, colWidths=[12*mm, 45*mm, 55*mm, 50*mm])
        gt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("FONTNAME", (0, 0), (-1, 0), fb),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc"))]))
        el.append(gt)
        el.append(Paragraph("<b>Sütunlar:</b> VRAM ve Util değerleri, test boyunca her GPU için "
                            "en düşük / ortalama / en yüksek ölçümlerdir (VRAM = gigabayt, "
                            "Util = GPU kullanım yüzdesi).", S["SMALL"]))
    else:
        el.append(Paragraph("GPU verisi yok.", S["SMALL"]))

    # Kaynak Kullanımı (özet) + ortalama token/s
    el.append(Paragraph("Kaynak Kullanımı", S["H2"]))
    atps = avg_tokens_per_sec(results)
    ttok = sum(r.get("completion_tokens", 0) for r in results)
    ttime = sum(r.get("total", 0) for r in results)
    vram_gb = sum(s["mem_max"] for s in gpu_summary.values()) / 1024 if gpu_summary else 0.0
    uavg, umax = gpu_util_stats(gpu_summary)
    krows = [["Metrik", "Değer"],
             ["Ortalama hız", f"{atps:.1f} token/s"],
             ["Toplam üretilen token", f"{ttok}"],
             ["Toplam süre", f"{ttime:.1f} s"],
             ["Tepe VRAM (tüm GPU toplamı)", f"{vram_gb:.1f} GB"],
             ["GPU kullanımı (ortalama / tepe)", f"{uavg:.0f}% / {umax:.0f}%"]]
    kt = Table(krows, colWidths=[70*mm, 70*mm])
    kt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), fb),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")])]))
    el.append(kt)
    el.append(Paragraph("<b>Açıklama:</b> Ortalama hız = toplam üretilen token / toplam üretim süresi · "
                        "Tepe VRAM = iki GPU'da test sırasında görülen en yüksek VRAM toplamı · "
                        "GPU kullanımı = işlemcinin meşguliyet yüzdesi (ortalama ve tepe).", S["SMALL"]))

    # Detay (kategoriye göre)
    el.append(Paragraph("Soru Detayları", S["H2"]))
    for cat in CATEGORIES:
        items = sorted([r for r in results if r["kategori"] == cat], key=lambda r: r["seviye"])
        if not items:
            continue
        el.append(Paragraph(cat, S["H2"]))
        for r in items:
            el.append(Paragraph(f"{html.escape(r['baslik'])} &nbsp; {_verdict_tag(r['passed'])}", S["H3"]))
            el.append(Paragraph(f"<b>Soru:</b>", S["BODY"]))
            el.append(Paragraph(_para(r["prompt"]), S["CODE"]))
            el.append(Paragraph(f"TTFT {r['ttft']:.2f}s · toplam {r['total']:.2f}s · "
                                f"{r['tokens_per_sec']:.1f} tok/s · {r['completion_tokens']} token", S["SMALL"]))
            if r.get("agentic_info"):
                ai = r["agentic_info"]
                el.append(Paragraph(f"<b>Agentic:</b> {ai['turns']} tur · {ai['tool_calls']} araç çağrısı · "
                                    f"önce-oku: {'evet' if ai['read_before'] else 'hayır'}", S["SMALL"]))
            if r["passed"] is not None and r["grade_detail"]:
                el.append(Paragraph(_para(r["grade_detail"]), S["SMALL"]))
            elif r["passed"] is None:
                el.append(Paragraph(html.escape(r.get("kriter", "")), S["SMALL"]))
            el.append(Paragraph('<b><font color="#15803d">Doğru cevap / Beklenen:</font></b>', S["BODY"]))
            el.append(Paragraph(_para(correct_answer_text(r)), S["CODE"]))
            el.append(Paragraph("<b>Modelin cevabı:</b>", S["BODY"]))
            txt = r["text"]
            if len(txt) > 4000:
                txt = txt[:4000] + "\n... [kısaltıldı]"
            el.append(Paragraph(_para(txt), S["CODE"]))
            el.extend(render_output_block(r.get("grade_output"), (f, fb, fm), S))
            el.append(HRFlowable(width="100%", color=colors.HexColor("#e5e5e5"),
                                 spaceBefore=6, spaceAfter=6))
    doc.build(el)


# ===========================================================================
#  ÇALIŞTIRMA
# ===========================================================================

def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "model"


def normalize_answer(resp, max_tokens):
    """Modelin nihai cevabını ayıkla. <think> bloklarını çıkar; cevap boşsa nedenini açıkla.
    -> (grade_text, display_text). grade_text boşsa model gerçekten cevap vermemiştir."""
    raw = (resp.get("text") or "")
    if raw.startswith("[İSTEK HATASI"):
        return raw, raw
    # content içine gömülü <think>...</think> bloklarını ayıkla
    content = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    if "<think>" in content and "</think>" not in content:
        content = ""   # düşünme yarıda kesilmiş, nihai cevap yok
    content = content.strip()
    if content:
        return content, content
    # cevap boş -> nedenini bul
    fr = resp.get("finish_reason")
    ct = resp.get("completion_tokens", 0)
    if fr == "length" or ct >= max_tokens:
        why = (f"token limitine (max_tokens={max_tokens}) takıldı; muhtemelen düşünme "
               f"(reasoning) aşamasında tükendi. Çözüm: --max-tokens artır veya --no-think kullan")
    else:
        why = f"boş cevap döndü (finish_reason={fr})"
    display = f"[Model nihai cevap üretmedi — {why}.]"
    if resp.get("reasoning"):
        display += "\n\n[Düşünme (reasoning) içeriği — ilk 1200 karakter]:\n" + resp["reasoning"][:1200]
    return "", display


def effective_max_tokens(args, n_ctx):
    """args.max_tokens > 0 ise onu kullan; <=0 ise bağlamın izin verdiği MAKSİMUM (n_ctx - rezerv)."""
    mt = getattr(args, "max_tokens", 0) or 0
    if mt and mt > 0:
        return int(mt)
    try:
        n = int(n_ctx)
    except (TypeError, ValueError):
        n = 32768
    return max(2048, n - 2048)   # prompt + şablon için küçük rezerv


def run_questions(base_url, model_id, args, max_tokens, gpu=None, log=print):
    """Tüm soruları sorar, değerlendirir; sonuç listesi döndürür. max_tokens: kullanılacak limit."""
    no_think = getattr(args, "no_think", False)
    results = []
    for q in QUESTIONS:
        log(f"   -> {q['baslik']}")
        if q.get("agentic"):
            # Çok-turlu araç döngüsü (model araç çağırır, biz çalıştırıp geri besleriz)
            try:
                ar = agentic_loop(base_url, model_id, q["agentic"], args.temperature, max_tokens,
                                  no_think=no_think)
            except Exception as e:
                ar = {"text": f"[İSTEK HATASI: {e}]", "turns": 0, "tool_calls": 0,
                      "read_before_answer": False, "transcript": [], "total": 0, "ttft": 0,
                      "completion_tokens": 0, "tokens_per_sec": 0}
            passed, detail, outinfo = grade_answer(q, ar["text"])
            disp = ar["text"] or "[boş]"
            results.append({**q, "text": disp, "ttft": ar["ttft"], "total": ar["total"],
                            "completion_tokens": ar["completion_tokens"],
                            "tokens_per_sec": ar["tokens_per_sec"], "passed": passed,
                            "grade_detail": detail, "grade_output": outinfo,
                            "agentic_info": {"turns": ar["turns"], "tool_calls": ar["tool_calls"],
                                             "read_before": ar["read_before_answer"]}})
            continue
        try:
            resp = ask_llm(base_url, model_id, q["prompt"], args.temperature, max_tokens,
                           no_think=no_think)
        except Exception as e:
            resp = {"text": f"[İSTEK HATASI: {e}]", "reasoning": "", "finish_reason": "error",
                    "ttft": 0, "total": 0, "completion_tokens": 0, "tokens_per_sec": 0}
        grade_text, display = normalize_answer(resp, max_tokens)
        passed, detail, outinfo = grade_answer(q, grade_text)
        results.append({**q, **resp, "text": display, "passed": passed,
                        "grade_detail": detail, "grade_output": outinfo})
    return results


def run_live(args):
    base = args.url.rstrip("/")
    print(f"-> Model tespit ediliyor: {base}")
    info = detect_model(base)
    print(f"   Model: {info['name']}")
    mt = effective_max_tokens(args, info["params"].get("n_ctx"))
    print(f"   max_tokens: {mt}")
    gpu = GpuMonitor(interval=args.gpu_interval)
    gpu.start()
    try:
        results = run_questions(base, info["served_id"], args, mt)
    finally:
        gpu.stop()
    ts = _dt.datetime.now()
    run_meta = {"url": base, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "temperature": args.temperature, "max_tokens": mt}
    # Her çalıştırmada Model_raporları altında YENİ çalışma klasörü (çakışmaya karşı bağışık)
    base = os.path.join(args.out_dir, f"calisma_{ts.strftime('%Y%m%d_%H%M%S')}")
    run_dir, k = base, 2
    while os.path.exists(run_dir):
        run_dir = f"{base}_{k}"
        k += 1
    folder = os.path.join(run_dir, "model_raporlari")
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, f"rapor_{safe_name(info['name'])}_{ts.strftime('%Y%m%d_%H%M')}.pdf")
    build_pdf(out, info, gpu.summary(), results, run_meta)
    cs = category_summary(results)
    print("   Skorlar:", {c: f"{cs[c]['passed']}/{cs[c]['graded']}" for c in CATEGORIES if cs[c]['graded']})
    print(f"✔ Rapor: {out}")


def reference_answer(q):
    """Bir soru için referans (doğru) cevabı üretir — selftest ve doğrulama için."""
    g = q["grader"]
    if not g:
        return "Örnek kısa öykü."
    gtype, spec = g
    if gtype == "code":
        return "```python\n" + CODE_SOLUTIONS[spec["func"]] + "\n```"
    if gtype == "sql":
        return "```sql\n" + spec["ref"] + ";\n```"
    if gtype == "math":
        return f"... hesap ...\n#### {spec['expected']:g}"
    if gtype == "metin":
        return f"... çıkarım ...\n#### {spec['expected']}"
    return ""


def run_selftest(args):
    print("-> SELFTEST: tüm referans çözümler grader'dan GEÇMELİ; bir yanlış cevap KALMALI.")
    results = []
    fails = 0
    for q in QUESTIONS:
        text = reference_answer(q)
        passed, detail, outinfo = grade_answer(q, text)
        if q["grader"] and not passed:
            fails += 1
            print(f"   ✗ {q['baslik']}: referans GEÇMEDİ! {detail[:80]}")
        results.append({**q, "text": text, "ttft": 0.1, "total": 1.2, "completion_tokens": 40,
                        "tokens_per_sec": 25.0, "passed": passed, "grade_detail": detail,
                        "grade_output": outinfo})
    # bir de kasıtlı yanlış (kod_1) -> KALMALI
    wrongq = next((x for x in QUESTIONS if x["key"] == "kod_1"), None)
    if wrongq:
        wp, _, _ = grade_answer(wrongq, "```python\ndef roman_sayi(s):\n    return 0\n```")
        print(f"   kasıtlı yanlış kod_1 -> passed={wp} (False olmalı) {'✓' if wp is False else '✗'}")
    print(f"   Referans sonucu: {len([r for r in results if r['grader'] and r['passed']])}"
          f"/{len([r for r in results if r['grader']])} GEÇTİ, {fails} hata.")
    info = {"name": "SELFTEST", "model_path": None, "params": {"n_ctx": 8192}, "served_id": "selftest"}
    ts = _dt.datetime.now()
    rm = {"url": "(selftest)", "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
          "temperature": 0.3, "max_tokens": args.max_tokens}
    # ÖNEMLİ: selftest çıktısı ASLA Model_raporları'na yazılmaz -> ayrı _selftest/ klasörü
    sdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_selftest")
    os.makedirs(sdir, exist_ok=True)
    out = os.path.join(sdir, f"rapor_SELFTEST_{ts.strftime('%Y%m%d_%H%M%S')}.pdf")
    build_pdf(out, info, {0: {"name": "RTX 4090", "mem_min": 7000, "mem_avg": 7200, "mem_max": 7400,
                              "util_min": 0, "util_avg": 50, "util_max": 99, "n": 20}}, results, rm)
    print(f"✔ SELFTEST PDF: {out}")


def main():
    ap = argparse.ArgumentParser(description="Lokal LLM performans testi (tek model).")
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--out-dir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "Model_raporları"),
                    help="Raporların üst klasörü (vars: ./Model_raporları)")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--max-tokens", type=int, default=0,
                    help="Yanıt başına maksimum token. 0 = OTOMATİK: bağlamın izin verdiği maksimum (n_ctx - 2048)")
    ap.add_argument("--no-think", action="store_true",
                    help="Düşünmeyi (reasoning) kapat — destekleyen modeller için (enable_thinking=false)")
    ap.add_argument("--gpu-interval", type=float, default=0.5)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    try:
        import reportlab  # noqa
    except ImportError:
        sys.exit("HATA: 'reportlab' kurulu değil ->  pip install reportlab")
    run_selftest(args) if args.selftest else run_live(args)


if __name__ == "__main__":
    main()

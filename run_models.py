#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seçili lokal LLM'leri test eden orkestratör.

HANGİ MODELLER TEST EDİLİR? -> SADECE `launch/` klasöründe `.sh` dosyası olan modeller.
Bir modeli testten çıkarmak için onun `open_*.sh` dosyasını `launch/` dışına (örn. `launch_1/`)
taşı. Tekrar dahil etmek için geri koy. Kod, `launch/`'ı KENDİLİĞİNDEN yeniden ÜRETMEZ
(taşıdıkların korunur); ilk kurulumda `launch/` boşsa tüm modeller için launcher üretir.

Her model için sırayla: llama-server'ı TEK GPU'da açar -> /health hazır olunca
tüm soruları (1 yaratıcılık + 5 kod + 5 SQL + 5 matematik) uygular + GPU/VRAM ölçer
-> sunucuyu kapatır -> sonraki model. Açılmazsa durmaz, sonrakine geçer.

ÇIKTI YAPISI (her çalıştırmada YENİ, benzersiz klasör; eskiler silinmez):
    Model_raporları/
        calisma_<tarih-saat>/                <- bu çalıştırmanın klasörü
            KARSILASTIRMA_<tarih>.pdf        <- genel rapor
            model_raporlari/                 <- tekli model PDF'leri (alt klasör)
                rapor_<model>_<tarih>.pdf

TÜM modeller eşit/adil koşul için TEK GPU (-sm none, cihaz 0) + flash attention (-fa on) ile
açılır. (17 Ağu 2026: makinede tek RTX 4090 kaldı; eski çift-GPU kurulumu yok.)

Kullanım:
    python run_models.py                       # launch/ içindeki modelleri test et
    python run_models.py --gen-launchers       # tüm modeller için launch/*.sh üret
    python run_models.py --only <dosya.gguf>   # ek filtre
    python run_models.py --combined-selftest
"""

import argparse
import datetime as _dt
import glob
import html
import os
import re
import signal
import subprocess
import sys
import time

import requests

import models_config as CFG
from bench import kayit as KAYIT
from bench import profiles as PROFIL
from bench import scoring as SCORE
from llm_perf_test import (QUESTIONS, CATEGORIES, run_questions, category_summary,
                           detect_model, GpuMonitor, safe_name, build_pdf,
                           _styles, _para, _verdict_tag, correct_answer_text,
                           render_output_block, effective_max_tokens,
                           avg_tokens_per_sec, gpu_util_stats)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LAUNCH_DIR = os.path.join(BASE_DIR, "launch")
LOG_DIR = os.path.join(BASE_DIR, "logs")
OUTPUT_BASE = os.path.join(BASE_DIR, "Model_raporları")   # tüm raporların üst klasörü
BASE_URL = f"http://{CFG.HOST}:{CFG.PORT}"


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def model_path(cfg):
    return cfg.get("path") or os.path.join(CFG.MODELS_DIR, cfg["file"])


def models_from_launchers():
    """launch/ içindeki open_*.sh dosyalarından test edilecek modelleri çıkarır.
    Source of truth = launch/ klasörü. Her .sh'nin -m yolundan model bulunur."""
    cfgs = []
    for sh in sorted(glob.glob(os.path.join(LAUNCH_DIR, "open_*.sh"))):
        try:
            txt = open(sh).read()
        except OSError:
            continue
        m = re.search(r'-m\s+"([^"]+)"', txt) or re.search(r"-m\s+(\S+)", txt)
        if not m:
            continue
        path = m.group(1)
        cfgs.append({"file": os.path.basename(path), "path": path, "sh": os.path.basename(sh)})
    return cfgs


def alias_of(cfg):
    return re.sub(r"\.gguf$", "", cfg["file"], flags=re.IGNORECASE)


def read_gpu_mem():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        res = {}
        for line in out.splitlines():
            idx, mem = [p.strip() for p in line.split(",")]
            res[int(idx)] = float(mem)
        return res
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Sunucu yönetimi (her model TEK GPU)
# ---------------------------------------------------------------------------

def _parse_sh_params(txt):
    """Bir .sh launcher metninden gösterim/log için parametreleri çıkarır (-c, GPU modu)."""
    m = re.search(r"-c\s+(\d+)", txt)
    ctx = int(m.group(1)) if m else CFG.DEFAULT_CTX
    cvd = re.search(r"CUDA_VISIBLE_DEVICES=(\S+)", txt)
    sm = re.search(r"-sm\s+(\S+)", txt)
    devs = cvd.group(1) if cvd else "0"
    n_dev = len([d for d in devs.split(",") if d != ""])
    if n_dev >= 2 and (not sm or sm.group(1) != "none"):
        mode = "çift GPU"
    else:
        mode = "tek GPU"
    return ctx, mode


def launch_server(cfg, log_path):
    """Modeli, launch/ içindeki KENDİ open_*.sh dosyasını ÇALIŞTIRARAK açar.
    .sh = tek doğru kaynak: dosyada hangi parametreler yazıyorsa model birebir öyle açılır
    (-c, -fa, -sm, CUDA_VISIBLE_DEVICES, ...). Kod artık parametreleri kendisi DAYATMAZ."""
    sh_path = os.path.join(LAUNCH_DIR, cfg["sh"]) if cfg.get("sh") else None
    logf = open(log_path, "w")
    if sh_path and os.path.exists(sh_path):
        txt = open(sh_path).read()
        ctx, gpu_mode = _parse_sh_params(txt)
        logf.write(f"LAUNCHER: {sh_path}\n--- .sh içeriği (gerçek açılış komutu) ---\n{txt}\n---\n\n")
        logf.flush()
        # start_new_session=True: bash + llama-server'ı tek process-group'a koyar ki
        # stop_server tüm grubu öldürebilsin (yoksa bash ölür, llama-server orphan kalıp 8080'i tutar).
        proc = subprocess.Popen(["bash", sh_path], stdout=logf, stderr=subprocess.STDOUT,
                                start_new_session=True)
        return proc, logf, ctx, gpu_mode
    # Yedek (cfg'de .sh yoksa): config varsayılanlarıyla doğrudan komut
    ctx = cfg.get("ctx", CFG.DEFAULT_CTX)
    ngl = cfg.get("ngl", CFG.DEFAULT_NGL)
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = "0"
    cmd = [CFG.LLAMA_SERVER, "-m", model_path(cfg), "-c", str(ctx), "-ngl", str(ngl),
           "-fa", "on", "-sm", "none", "--host", CFG.HOST, "--port", str(CFG.PORT),
           "-a", alias_of(cfg), "--jinja"]
    logf.write("CMD (.sh bulunamadı, yedek): " + " ".join(cmd) + "\n\n")
    logf.flush()
    proc = subprocess.Popen(cmd, env=env, stdout=logf, stderr=subprocess.STDOUT,
                            start_new_session=True)
    return proc, logf, ctx, "tek GPU"


def wait_health(proc, timeout=300):
    deadline = time.time() + timeout
    url = BASE_URL + "/health"
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _signal_group(proc, sig):
    """proc'un process-group'una sinyal gönderir (bash + llama-server birlikte). Grup yoksa proc'a."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError):
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            pass


def stop_server(proc, logf):
    if proc and proc.poll() is None:
        _signal_group(proc, signal.SIGTERM)   # tüm grubu (bash + llama-server) durdur
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _signal_group(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
    if logf:
        logf.close()


def wait_vram_free(baseline, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        cur = read_gpu_mem()
        if not cur or all(cur.get(i, 0) <= baseline.get(i, 0) + 800 for i in cur):
            return
        time.sleep(2)


# ---------------------------------------------------------------------------
# Tek model testi
# ---------------------------------------------------------------------------

def test_one_model(cfg, args):
    name_guess = alias_of(cfg)
    rec = {"file": cfg["file"], "name": name_guess, "ok": False, "error": None,
           "params": {}, "ctx": None, "max_tokens": None, "results": [],
           "gpu_summary": {}, "vram_peak_delta": 0.0}
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{safe_name(name_guess)}.log")
    baseline = read_gpu_mem()
    proc, logf, ctx, gpu_mode = launch_server(cfg, log_path)
    print(f"   açılıyor ({gpu_mode}) ...")
    if not wait_health(proc, timeout=args.load_timeout):
        stop_server(proc, logf)
        wait_vram_free(baseline)
        rec["error"] = f"Sunucu hazır olmadı (log: {log_path})"
        print(f"      ✘ AÇILMADI -> atlanıyor.")
        return rec

    try:
        info = detect_model(BASE_URL)
        rec["name"] = info["name"] or name_guess
        rec["params"] = info["params"]
        rec["ctx"] = ctx
        mt = effective_max_tokens(args, info["params"].get("n_ctx") or ctx)
        rec["max_tokens"] = mt
        print(f"      max_tokens: {mt}")
        # Profil, modelin KENDİ kartındaki örnekleme ayarını getirir (bkz. bench/profiles.py).
        # Model adı .sh'den değil, sunucunun bildirdiği addan çözülür.
        profil = PROFIL.profil_bul(rec["name"], deterministik=args.deterministik)
        rec["profil"] = profil
        print(f"      profil: {PROFIL.ozet(profil)}")
        if args.tekrar > 1:
            print(f"      tekrar: her puanlı soru ×{args.tekrar} (avg@{args.tekrar})")
        gpu = GpuMonitor(interval=args.gpu_interval)
        gpu.start()
        try:
            rec["results"] = run_questions(BASE_URL, info["served_id"], args, mt, profil=profil,
                                           n_ctx=info["params"].get("n_ctx") or ctx)
        finally:
            gpu.stop()
        rec["gpu_summary"] = gpu.summary()
        rec["vram_peak_delta"] = sum(max(0.0, s["mem_max"] - baseline.get(idx, 0))
                                     for idx, s in rec["gpu_summary"].items())
        rec["ok"] = True
    except Exception as e:
        rec["error"] = f"Test sırasında hata: {e}"
        print(f"      ✘ {rec['error']}")
    finally:
        stop_server(proc, logf)
        wait_vram_free(baseline)
    return rec


# ---------------------------------------------------------------------------
# Birleşik PDF
# ---------------------------------------------------------------------------

# Sütun başlıkları DAR hücrelere giriyor: her branşın kısa adı OLMAK ZORUNDA.
# Kısa adı olmayan branş tam adıyla yazılır ve komşu sütunun üstüne taşar
# (12 branşa çıkıldığında "Halüsinasyon" ile "Türkçe" iç içe geçmişti).
SHORT_CAT = {"Yaratıcılık": "Yarat.", "Kod": "Kod", "SQL": "SQL",
             "Matematik": "Mat", "Hata Ayıklama": "Hata", "Agentic": "Agent.",
             "Medikal": "Medik.", "Talimat": "Talim.", "JSON": "JSON",
             "Halüsinasyon": "Halüs.", "Türkçe": "Türkçe", "Uzun Bağlam": "Uzun B."}

# Renk sayısı branş sayısından AZ olursa modulo ile tekrar eder ve yığılmış
# sütunda iki farklı branş aynı renge düşer — grafik okunamaz hâle gelir.
# Liste CATEGORIES'ten uzun tutulmalı; birbirinden ayırt edilebilir 12 ton.
CAT_COLORS = ["#1a3c5e", "#0891b2", "#15803d", "#65a30d", "#d97706", "#c2410c",
              "#be123c", "#a21caf", "#7c3aed", "#4338ca", "#0f766e", "#78716c",
              "#0369a1", "#ca8a04", "#db2777", "#4d7c0f"]

# A4 - 2×14 mm kenar boşluğu. Tablo genişlikleri bunu AŞMAMALI, yoksa son
# sütun sayfa dışında kalır.
KULLANILABILIR_MM = 182.0


def _kisa_model_ad(ad):
    """Grafik ekseni için model adını kısalt: sağlayıcı öneki + kuantizasyon eki at.

    'google_gemma-4-26B-A4B-it-Q5_K_M' -> 'gemma-4-26B-A4B-it'
    Uzun adlar 90° döndürülünce grafiğin altında 130 pt yer kaplıyordu.
    """
    ad = re.sub(r"^(google_|Qwen_|unsloth_|bartowski_)", "", str(ad))
    ad = re.sub(r"[-_.]?(UD[-_.]?)?(I?Q\d(_\d)?[-_.]?[KMS]?([-_.]?[A-Z]+)?)$", "", ad)
    return ad.strip("-_. ") or str(ad)


def graded_categories():
    """Puanlanan kategoriler (Yaratıcılık hariç), CATEGORIES sırasında + soru sayıları."""
    from collections import Counter
    gc = Counter(q["kategori"] for q in QUESTIONS if q["grader"])
    return [c for c in CATEGORIES if gc.get(c, 0) > 0], gc


def build_perf_chart(records):
    """Modellerin otomatik skorunu, puanlanan TÜM kategorilere göre yığılmış sütun grafiği çizer
    (kategori sayısı/branş eklense de kendini günceller). reportlab.graphics ile."""
    from reportlab.graphics.shapes import Drawing, String, Rect
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.lib import colors
    from reportlab.pdfbase.pdfmetrics import stringWidth

    gcats, gc = graded_categories()
    maxscore = sum(gc[c] for c in gcats)

    def total_score(r):
        cs = category_summary(r["results"])
        return sum(cs[c]["passed"] for c in gcats)

    ok = sorted([r for r in records if r["ok"]], key=total_score, reverse=True)
    if not ok:
        return None
    # Sessizce bozulmasın: renk/etiket eksikse grafik okunamaz hâle gelir.
    if len(gcats) > len(CAT_COLORS):
        print(f"   [uyarı] {len(gcats)} branş var, CAT_COLORS'ta {len(CAT_COLORS)} renk — "
              "renkler tekrar edecek, listeye yeni ton ekleyin")
    _kisasiz = [c for c in gcats if c not in SHORT_CAT]
    if _kisasiz:
        print(f"   [uyarı] SHORT_CAT'te kısa adı olmayan branş: {', '.join(_kisasiz)} — "
              "tablo başlığı daralacak")
    names = [_kisa_model_ad(r["name"]) for r in ok]
    cs_all = [category_summary(r["results"]) for r in ok]
    series = [[cs[c]["passed"] for cs in cs_all] for c in gcats]   # her kategori bir seri
    totals = [sum(cs[c]["passed"] for c in gcats) for cs in cs_all]

    # ---- YERLEŞİM ÖNCE HESAPLANIR ----------------------------------------
    # Sabit yükseklikte çizim alanı, branş sayısı arttıkça taşıyordu: gösterge
    # (legend) tek satıra sığmayıp sayfa dışına çıkıyor, döndürülmüş model
    # adları da çizim alanının altından taşıyordu. Artık üç blok da ölçülür.
    width = 524
    etiketler = [f"{SHORT_CAT.get(c, c)} /{gc[c]}" for c in gcats]
    KUTU, ARA, YAZI_ARA, LEG_PT = 7, 14, 3, 7.5
    oge_w = [KUTU + YAZI_ARA + stringWidth(e, "DejaVu", LEG_PT) for e in etiketler]

    satirlar, cur, cur_w = [], [], 0.0            # göstergeyi satırlara böl
    for i, w_ in enumerate(oge_w):
        if cur and cur_w + ARA + w_ > width - 8:
            satirlar.append(cur); cur, cur_w = [], 0.0
        cur_w += (ARA if cur else 0) + w_
        cur.append(i)
    if cur:
        satirlar.append(cur)

    leg_h = len(satirlar) * 12 + 6
    # 90° döndürülmüş model adlarının kapladığı DİKEY yer = metnin genişliği.
    etiket_h = max(stringWidth(n, "DejaVu", 6.5) for n in names) + 10
    govde_h = 160
    height = leg_h + govde_h + etiket_h + 14

    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x, bc.y = 28, etiket_h
    bc.width, bc.height = width - 56, govde_h
    bc.data = series
    bc.categoryAxis.style = "stacked"
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = maxscore
    bc.valueAxis.valueStep = max(1, maxscore // 6)
    bc.valueAxis.labels.fontName = "DejaVu"
    bc.valueAxis.labels.fontSize = 7
    bc.categoryAxis.categoryNames = names
    bc.categoryAxis.labels.boxAnchor = "e"
    bc.categoryAxis.labels.angle = 90
    bc.categoryAxis.labels.dy = -2
    bc.categoryAxis.labels.fontName = "DejaVu"
    bc.categoryAxis.labels.fontSize = 6.5
    for i in range(len(gcats)):
        bc.bars[i].fillColor = colors.HexColor(CAT_COLORS[i % len(CAT_COLORS)])
    d.add(bc)

    group_w = bc.width / max(1, len(ok))
    for i, tot in enumerate(totals):
        x = bc.x + group_w * (i + 0.5)
        y = bc.y + bc.height * (tot / maxscore) + 3
        d.add(String(x, y, str(tot), fontName="DejaVu", fontSize=7,
                     fillColor=colors.HexColor("#333333"), textAnchor="middle"))

    # ---- GÖSTERGE: sütunların hemen ÜSTÜNDE, gerektiği kadar satırda --------
    # reportlab'in Legend'ı sabit deltax ile tek satıra diziyordu; 11 branşta
    # 770 pt yer isteyip 524 pt'lik alanın dışına taşıyordu. Elle diziyoruz ki
    # renkler hem sığsın hem de ait oldukları sütunlara yakın dursun.
    y = height - 11
    for satir in satirlar:
        x = 4.0
        for i in satir:
            d.add(Rect(x, y - 1, KUTU, KUTU,
                       fillColor=colors.HexColor(CAT_COLORS[i % len(CAT_COLORS)]),
                       strokeColor=None))
            d.add(String(x + KUTU + YAZI_ARA, y, etiketler[i], fontName="DejaVu",
                         fontSize=LEG_PT, fillColor=colors.HexColor("#333333")))
            x += oge_w[i] + ARA
        y -= 12
    return d


def build_combined_pdf(out_path, records, run_meta):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable, PageBreak)
    from reportlab.lib.styles import ParagraphStyle
    (f, fb, fm), S = _styles()
    namep = ParagraphStyle("namep", fontName=f, fontSize=7.5, leading=9, wordWrap="CJK")

    def NM(x):
        return Paragraph(html.escape(str(x)), namep)

    # Düz metin hücreler SARMAZ: sütuna sığmayan başlık komşusunun üstüne
    # taşıyor ve iki yazı iç içe geçiyordu ("Halüsinasy|Türkçe"). Paragraph
    # sarar; wordWrap="CJK" boşluksuz uzun kelimeyi de böler.
    def _hp(size, cjk):
        # Boşluklu başlıkta CJK kullanılmaz: karakter karakter sardığı için
        # "Bağlam yetersiz" -> "Bağlam yetersi / z" gibi bölünüyor. Boşluksuz
        # tek kelimede ise sarmanın TEK yolu CJK'dır (yoksa taşar).
        return ParagraphStyle(f"th{size}{int(cjk)}", fontName=fb, fontSize=size,
                              leading=size + 1.4, alignment=1,
                              wordWrap=("CJK" if cjk else None),
                              textColor=colors.white)

    def TH(x, size=7):
        """Tablo başlığı hücresi — taşmak yerine satır kaydırır."""
        x = str(x)
        return Paragraph(html.escape(x), _hp(size, " " not in x.strip()))

    def _sigan_punto(etiketler, sutun_mm, azami=7.0, asgari=4.8):
        """Başlıkların sütuna sığdığı en büyük puntoyu bul.

        Branş sayısı arttıkça sütun daralıyor; sabit punto ile başlıklar
        sarmak zorunda kalıp tabloyu yükseltiyor ya da (sarmıyorsa) taşıyor.
        Yeni branş eklendiğinde punto kendiliğinden küçülsün diye ölçülüyor.
        """
        from reportlab.pdfbase.pdfmetrics import stringWidth
        kullan = sutun_mm * mm - 5              # sol+sağ dolgu payı
        pt = azami
        while pt > asgari and max(stringWidth(str(e), fb, pt) for e in etiketler) > kullan:
            pt -= 0.25
        return pt

    def CELL(x, size=6.5, align=0):
        """Uzun metin içeren gövde hücresi (ör. örnekleme profili)."""
        return Paragraph(html.escape(str(x)),
                         ParagraphStyle(f"td{size}{align}", fontName=f, fontSize=size,
                                        leading=size + 1.6, alignment=align,
                                        wordWrap="CJK"))

    def cat_score(rec, cat):
        cs = category_summary(rec["results"])[cat]
        return cs

    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=14*mm, bottomMargin=14*mm, title="LLM Karşılaştırma")
    el = [Paragraph("LLM Karşılaştırma Raporu", S["H1"])]
    ok_n = sum(1 for r in records if r["ok"])
    el.append(Paragraph(f"{run_meta['timestamp']} &nbsp;|&nbsp; {ok_n}/{len(records)} model "
                        f"&nbsp;|&nbsp; temperature={run_meta['temperature']} &nbsp;|&nbsp; "
                        f"max_tokens={run_meta['max_tokens']} &nbsp;|&nbsp; ctx={CFG.DEFAULT_CTX} "
                        f"&nbsp;|&nbsp; tek GPU", S["SMALL"]))
    el.append(HRFlowable(width="100%", color=colors.grey, spaceBefore=6, spaceAfter=8))

    # ---- TABLO 1: skorlar (puanlanan tüm kategoriler dinamik) ----
    gcats, _gc = graded_categories()
    _ntot = sum(_gc[c] for c in gcats)
    el.append(Paragraph("1) Skor Karşılaştırması", S["H2"]))
    # Hücreler AĞIRLIKLI puan gösterir (kısmi puan × kademe ağırlığı), çünkü
    # "kaç soru tam geçti" sayısı kısmi puanı ve zorluk farkını yok sayıyordu.
    rows = [[TH("Model"), TH("Ağırlıklı puan"), TH("%"), TH("Tam geçen"),
             TH("Kararlılık"), TH("Σ süre (s)"), TH("ort tok/s"), TH("ctx")]]

    def sort_key(r):
        if not r["ok"]:
            return (1, 0, 9e9)
        cs = category_summary(r["results"])
        return (0, -SCORE.toplam_ozet(cs)["agirlikli_puan"],
                sum(x["total"] for x in r["results"]))

    import statistics as _st
    for rec in sorted(records, key=sort_key):
        if not rec["ok"]:
            rows.append([NM(rec["name"]), "AÇILMADI"] + ["—"] * 6)
            continue
        cs = category_summary(rec["results"])
        ozet = SCORE.toplam_ozet(cs)
        tot = sum(x["total"] for x in rec["results"])
        tps = _st.mean([x["tokens_per_sec"] for x in rec["results"] if x["tokens_per_sec"]] or [0])
        krr = [x["kararlilik"] for x in rec["results"] if x.get("kararlilik") is not None]
        rows.append([NM(rec["name"]),
                     f"{ozet['agirlikli_puan']:.0f} / {ozet['azami_agirlik']}",
                     f"%{ozet['yuzde']:.0f}",
                     f"{ozet['gecen']}/{ozet['puanli']}",
                     (f"{sum(krr)/len(krr):.2f}" if krr else "—"),
                     f"{tot:.0f}", f"{tps:.1f}",
                     f"{(rec.get('ctx') or 0)//1024}k"])
    colW = [54*mm, 24*mm, 11*mm, 19*mm, 19*mm, 20*mm, 19*mm, 16*mm]   # Σ = 182 mm
    t = Table(rows, colWidths=colW)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")])]))
    el.append(t)
    el.append(Paragraph(
        "<b>Ağırlıklı puan</b> = Σ (kısmi puan × kademe ağırlığı); ağırlıklar kolay 1, "
        f"orta 2, zor 3, acımasız 4 · <b>Tam geçen</b> = tam puan alınan soru / puanlanan "
        f"soru ({_ntot}) · <b>Kararlılık</b> = avg@K denemelerinin tutarlılığı (1,00 = her "
        "denemede aynı sonuç) · <b>ctx</b> = modelin ÖLÇÜLMÜŞ context tavanı. "
        "Yaratıcılık branşı otomatik puanlanmaz.",
        S["SMALL"]))

    # ---- GENEL PERFORMANS SÜTUN GRAFİĞİ ----
    chart = build_perf_chart(records)
    if chart is not None:
        el.append(Paragraph(f"Genel Performans (otomatik skor /{_ntot}, yüksekten düşüğe)", S["H2"]))
        el.append(chart)

    # ---- TABLO 2: süreler ----
    # ---- TABLO 1a: kategori kırılımı (12 branş tek tabloya sığmadığı için ayrıldı) ----
    el.append(Paragraph("1a) Branş Bazında Ağırlıklı Puan", S["H2"]))
    _kad = 34.0                                    # model sütunu (mm)
    _kw = (KULLANILABILIR_MM - _kad) / max(1, len(gcats))
    _kpt = _sigan_punto([SHORT_CAT.get(c, c) for c in gcats], _kw)
    krows = [[TH("Model", _kpt)] + [TH(SHORT_CAT.get(c, c), _kpt) for c in gcats]]
    for rec in sorted(records, key=sort_key):
        if not rec["ok"]:
            continue
        cs = category_summary(rec["results"])
        krows.append([NM(rec["name"])]
                     + [("—" if not cs[c]["graded"]
                         else f"{cs[c]['agirlikli_puan']:.0f}/{cs[c]['azami_agirlik']}")
                        for c in gcats])
    kt = Table(krows, colWidths=[_kad*mm] + [_kw*mm] * len(gcats))
    kt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("FONTNAME", (0, 0), (-1, -1), f),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9aa5b1")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    el.append(kt)
    el.append(Paragraph("Her hücre: alınan ağırlıklı puan / o branşın azami ağırlığı.", S["SMALL"]))
    el.append(Spacer(1, 6))

    # ---- TABLO 1b: hangi model hangi PARAMETRELERLE koştu ----
    # Modeller artık aynı koşullarda koşmuyor (her biri kendi kartının ayarıyla);
    # bu tablo olmadan karşılaştırma yorumlanamaz.
    el.append(Paragraph("1b) Model Parametreleri", S["H2"]))
    prow = [[TH("Model", 6.5), TH("Profil / örnekleme", 6.5), TH("ctx", 6.5),
             TH("En zor çözülen", 6.5), TH("Kesilen", 6.5), TH("Bağlam yetersiz", 6.5)]]
    for rec in records:
        if not rec["ok"]:
            continue
        cs = category_summary(rec["results"])
        kademeler = [cs[c]["en_zor_kademe"] for c in cs if cs[c]["en_zor_kademe"]]
        sira = SCORE.KADEME_SIRA
        enzor = max(kademeler, key=sira.index) if kademeler else "—"
        yetersiz = sum(1 for x in rec["results"] if x.get("baglam_yetersiz"))
        prow.append([NM(rec["name"]),
                     # Profil metni uzun ("… top_p=0.95 top_k=20 rep=1.0"); düz
                     # metin olarak ctx sütununun üstüne biniyordu -> sarmalı.
                     CELL(PROFIL.ozet(rec.get("profil") or {})),
                     f"{(rec.get('ctx') or 0)//1024}k",
                     enzor,
                     str(sum(1 for x in rec["results"] if x.get("kesildi"))),
                     str(yetersiz)])
    pt = Table(prow, colWidths=[38*mm, 72*mm, 13*mm, 22*mm, 15*mm, 22*mm])   # Σ = 182 mm
    pt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("FONTNAME", (0, 0), (-1, -1), f),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("ALIGN", (2, 1), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9aa5b1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    el.append(pt)
    el.append(Paragraph(
        "Koşullar model başına FARKLIDIR (her model kendi kartının önerdiği örnekleme ve "
        "ölçülmüş context tavanı ile açıldı). Sonuç 'aynı koşulda hangisi iyi' değil, "
        "'her biri en iyi hâliyle ne yapabiliyor' sorusunu yanıtlar. "
        "Kesilen = token tavanına çarpıp cevapsız kalan soru · Bağlam yetersiz = belgesi "
        "modelin context'ine sığmadığı için PUANLANMAYAN soru.", S["SMALL"]))
    el.append(Spacer(1, 6))

    el.append(Paragraph("2) Kategori Bazında Toplam Süre (s)", S["H2"]))
    _mw = 38.0
    _pw = (KULLANILABILIR_MM - _mw) / max(1, len(CATEGORIES))
    _ppt = _sigan_punto([SHORT_CAT.get(c, c) for c in CATEGORIES], _pw)
    rows2 = [[TH("Model", _ppt)] + [TH(SHORT_CAT.get(c, c), _ppt) for c in CATEGORIES]]
    for rec in records:
        if not rec["ok"]:
            continue
        rows2.append([NM(rec["name"])] + [f"{category_summary(rec['results'])[c]['time']:.0f}" for c in CATEGORIES])
    t2 = Table(rows2, colWidths=[_mw*mm] + [_pw*mm] * len(CATEGORIES))
    t2.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")])]))
    el.append(t2)
    el.append(Paragraph("<b>Sütunlar:</b> Her hücre, o kategorideki tüm soruların TOPLAM yanıt "
                        "süresidir (saniye). Düşük = daha hızlı.", S["SMALL"]))

    # ---- TABLO 3: Kaynak Kullanımı (modellerin harcadığı kaynaklar + ortalama token/s) ----
    # ---- MADDE ANALİZİ: sorular gerçekten ayırt ediyor mu? ----
    ms = {r["name"]: r["results"] for r in records if r.get("ok") and r.get("results")}
    analiz = SCORE.madde_analizi(ms)
    if analiz:
        oz = SCORE.analiz_ozeti(analiz)
        el.append(Paragraph("2b) Madde Analizi — sorular ayırt ediyor mu?", S["H2"]))
        el.append(Paragraph(
            f"{oz['toplam']} puanlı sorudan <b>{oz['ayirt_eden']}</b>'i modelleri ayırıyor "
            f"(%{oz['oran']}). Hiç ayrım üretmeyen (emeklilik adayı): "
            f"<b>{oz['emeklilik_adayi']}</b>. Ayrım üretmeyen soru, testin o koşuda boşa "
            f"harcadığı süredir; zorlaştırılmalı ya da emekliye ayrılmalıdır.", S["SMALL"]))
        arows = [["Soru", "Kademe", "Yayılım"] + [NM(m) for m in ms]]
        for a in [x for x in analiz if x["ayirt_ediyor"]][:14]:
            arows.append([a["baslik"][:34], a["kademe"] or "—", f"{a['yayilim']:.2f}"]
                         + [f"{a['puanlar'].get(m, 0):.2f}" for m in ms])
        if len(arows) > 1:
            at = Table(arows, colWidths=[52*mm, 16*mm, 14*mm] + [24*mm] * len(ms))
            at.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15803d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), f), ("FONTNAME", (0, 0), (-1, 0), fb),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9aa5b1")),
                ("ALIGN", (2, 1), (-1, -1), "CENTER")]))
            el.append(at)
            el.append(Paragraph("En ayırt edici 14 soru. Tam liste: "
                                "<b>python madde_analizi.py &lt;koşu klasörü&gt; --hepsi</b>",
                                S["SMALL"]))
        el.append(Spacer(1, 6))

    el.append(Paragraph("3) Kaynak Kullanımı", S["H2"]))
    rows3 = [[TH("Model"), TH("Ort. token/s"), TH("Toplam token"), TH("Σ süre (s)"),
              TH("Tepe VRAM (GB)"), TH("GPU ort/tepe %")]]
    for rec in records:
        if not rec["ok"]:
            continue
        atps = avg_tokens_per_sec(rec["results"])
        ttok = sum(r.get("completion_tokens", 0) for r in rec["results"])
        ttime = sum(r.get("total", 0) for r in rec["results"])
        uavg, umax = gpu_util_stats(rec["gpu_summary"])
        rows3.append([NM(rec["name"]), f"{atps:.1f}", f"{ttok}", f"{ttime:.0f}",
                      f"{rec['vram_peak_delta']/1024:.1f}", f"{uavg:.0f}/{umax:.0f}"])
    t3 = Table(rows3, colWidths=[58*mm, 22*mm, 24*mm, 20*mm, 24*mm, 24*mm])   # Σ = 172 mm
    t3.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")])]))
    el.append(t3)
    el.append(Paragraph(
        "<b>Sütunlar:</b> Ort. token/s = toplam üretilen token / toplam üretim süresi (yüksek = hızlı) · "
        "Toplam token = üretilen toplam token sayısı · Σ süre (s) = toplam yanıt süresi · "
        "Tepe VRAM (GB) = açılış öncesine göre görülen en yüksek VRAM artışı · "
        "GPU ort/tepe % = test boyunca ortalama ve en yüksek GPU kullanım yüzdesi.", S["SMALL"]))

    # ---- Sorular (bir kez) ----
    el.append(PageBreak())
    el.append(Paragraph("Sorular", S["H2"]))
    for cat in CATEGORIES:
        el.append(Paragraph(cat, S["H2"]))
        for q in sorted([x for x in QUESTIONS if x["kategori"] == cat], key=lambda x: x["seviye"]):
            el.append(Paragraph(html.escape(q["baslik"]), S["H3"]))
            el.append(Paragraph(_para(q["prompt"]), S["CODE"]))
            el.append(Paragraph('<font color="#15803d"><b>Doğru cevap / Beklenen:</b></font>', S["SMALL"]))
            el.append(Paragraph(_para(correct_answer_text(q)), S["CODE"]))

    # ---- Alt bölüm: her model, her soruya cevabı ----
    for rec in records:
        el.append(PageBreak())
        el.append(Paragraph(html.escape(rec["name"]), S["H2"]))
        if not rec["ok"]:
            el.append(Paragraph(f'<font color="#b91c1c">Test edilemedi: '
                                f'{html.escape(str(rec["error"]))}</font>', S["BODY"]))
            continue
        cs = category_summary(rec["results"])
        skor = " · ".join(f"{c}: {cs[c]['passed']}/{cs[c]['graded']}" for c in CATEGORIES if cs[c]['graded'])
        el.append(Paragraph(f"ctx: {rec['ctx']} · VRAM tepe: {rec['vram_peak_delta']/1024:.1f} GB · {skor}", S["SMALL"]))
        if rec["params"]:
            el.append(Paragraph(html.escape(", ".join(f"{k}={v}" for k, v in rec["params"].items())), S["SMALL"]))
        for cat in CATEGORIES:
            items = sorted([r for r in rec["results"] if r["kategori"] == cat], key=lambda r: r["seviye"])
            if not items:
                continue
            el.append(Paragraph(cat, S["H2"]))
            for r in items:
                el.append(Paragraph(f"{html.escape(r['baslik'])} &nbsp; {_verdict_tag(r['passed'])} "
                                    f"&nbsp;<font size=7 color='#888888'>"
                                    f"({r['total']:.1f}s · {r['tokens_per_sec']:.0f} tok/s)</font>", S["H3"]))
                if r.get("agentic_info"):
                    ai = r["agentic_info"]
                    el.append(Paragraph(f"<b>Agentic:</b> {ai['turns']} tur · {ai['tool_calls']} araç çağrısı "
                                        f"· önce-oku: {'evet' if ai['read_before'] else 'hayır'}", S["SMALL"]))
                if r["passed"] is not None and r["grade_detail"]:
                    el.append(Paragraph(_para(r["grade_detail"][:400]), S["SMALL"]))
                txt = r["text"]
                if len(txt) > 3500:
                    txt = txt[:3500] + "\n... [kısaltıldı]"
                el.append(Paragraph(_para(txt), S["CODE"]))
                el.extend(render_output_block(r.get("grade_output"), (f, fb, fm), S))
                el.append(Spacer(1, 3))
    doc.build(el)


# ---------------------------------------------------------------------------
# Launcher üreteci (hepsi tek GPU)
# ---------------------------------------------------------------------------

def gen_launchers():
    """Her model için açılış betiği üretir.

    Context ve KV tipi model PROFİLİNDEN gelir (bench/profiles.py) — modeller
    aynı context'e zorlanmaz, her biri kendi ölçülmüş tavanında açılır.
    `models_config.MODELS` içindeki açık `ctx` değeri profili ezer."""
    os.makedirs(LAUNCH_DIR, exist_ok=True)
    n = 0
    for cfg in CFG.MODELS:
        profil = PROFIL.profil_bul(alias_of(cfg))
        ctx = cfg.get("ctx") or profil.get("ctx") or CFG.DEFAULT_CTX
        ngl = cfg.get("ngl", CFG.DEFAULT_NGL)
        kv = cfg.get("kv_tipi") or profil.get("kv_tipi")
        kv_satir = f" -ctk {kv} -ctv {kv}" if kv else ""
        sh = os.path.join(LAUNCH_DIR, "open_" + safe_name(alias_of(cfg)) + ".sh")
        content = f"""#!/usr/bin/env bash
# {cfg['file']}  (tek GPU, {ctx // 1024}k{', KV ' + kv if kv else ''}, -fa on)  -> http://{CFG.HOST}:{CFG.PORT}
# profil: {PROFIL.ozet(profil)}
set -e
export CUDA_VISIBLE_DEVICES=0
"{CFG.LLAMA_SERVER}" \\
  -m "{model_path(cfg)}" \\
  -c {ctx} -ngl {ngl} -sm none -fa on{kv_satir} \\
  --host {CFG.HOST} --port {CFG.PORT} \\
  -a {alias_of(cfg)} --jinja
"""
        with open(sh, "w") as fp:
            fp.write(content)
        os.chmod(sh, 0o755)
        n += 1
    print(f"✔ {n} launcher üretildi -> {LAUNCH_DIR}/open_*.sh")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _madde_analizi_yaz(records):
    """Konsola madde analizi özeti basar: hangi sorular ayırt ediyor, hangileri boşa çalışıyor.

    Testin kendi bakımını söylemesi için var. En az 2 başarılı model gerekir."""
    ms = {r["name"]: r["results"] for r in records if r.get("ok") and r.get("results")}
    analiz = SCORE.madde_analizi(ms)
    if not analiz:
        print("\n(madde analizi için en az 2 başarılı model gerekir — atlandı)")
        return
    ozet = SCORE.analiz_ozeti(analiz)
    print("\n==== MADDE ANALİZİ ====")
    print(f"  {ozet['toplam']} puanlı sorudan {ozet['ayirt_eden']}'i modelleri ayırıyor "
          f"(%{ozet['oran']}). Emeklilik adayı: {ozet['emeklilik_adayi']}")
    ayirt = [a for a in analiz if a["ayirt_ediyor"]]
    if ayirt:
        print("  En ayırt edici sorular:")
        for a in ayirt[:10]:
            puanlar = " · ".join(f"{m[:18]}={p:.2f}" for m, p in a["puanlar"].items())
            print(f"    {a['baslik'][:36]:<36} yayılım={a['yayilim']:.2f}  {puanlar}")
    if ozet["emeklilik_adayi"]:
        print(f"  Hiçbir ayrım üretmeyen {ozet['emeklilik_adayi']} soru var; "
              f"ayrıntı: python madde_analizi.py <kosu_klasoru>")


def make_output_dirs(out_root, ts):
    """Her çalıştırmada Model_raporları altında YENİ bir çalışma klasörü açar (benzersiz isim).
    Genel rapor bu klasöre, tekli raporlar onun altındaki model_raporlari/ alt klasörüne gider.
    Eski klasörler silinmez (her çalıştırma farklı tarih-saat damgalı)."""
    base = os.path.join(out_root, f"calisma_{ts.strftime('%Y%m%d_%H%M%S')}")
    run_dir, k = base, 2
    while os.path.exists(run_dir):   # aynı saniyede ikinci çalıştırma olsa bile çakışma/üzerine yazma yok
        run_dir = f"{base}_{k}"
        k += 1
    per_model = os.path.join(run_dir, "model_raporlari")
    os.makedirs(per_model, exist_ok=True)
    return run_dir, per_model


def run_combined_selftest(args):
    from llm_perf_test import grade_answer, reference_answer
    # Her soru için DOĞRU cevabı referanslardan üret (tüm grader tipleri için)
    correct = {q["key"]: reference_answer(q) for q in QUESTIONS}
    # Modeller farklı zorluk eşiğine kadar doğru cevaplasın -> farklı skorlar
    fake = [("sahte_google_modelA", True, 6), ("sahte_Qwen_modelB", True, 4),
            ("sahte_modelC", True, 2), ("sahte_modelD_acilmadi", False, 0)]
    records = []
    for i, (name, ok, esik) in enumerate(fake):
        if not ok:
            records.append({"file": name, "name": name, "ok": False,
                            "error": "Sunucu hazır olmadı (selftest)", "results": [],
                            "gpu_summary": {}, "vram_peak_delta": 0, "params": {}, "ctx": None})
            continue
        results = []
        for q in QUESTIONS:
            # seviyesi eşiğin altındaysa doğru, üstündeyse yanlış cevap ver
            text = correct[q["key"]] if q["seviye"] < esik else "(yanlış / eksik cevap)"
            passed, detail, outinfo, puan = grade_answer(q, text)
            results.append({**q, "text": text, "ttft": 0.1, "total": 1.0 + i,
                            "completion_tokens": 50, "tokens_per_sec": 30 - i * 4,
                            "passed": passed, "puan": puan, "kararlilik": None, "kesildi": False,
                            "grade_detail": detail, "grade_output": outinfo})
        records.append({"file": name, "name": name, "ok": True, "error": None,
                        "params": {"n_ctx": 8192}, "ctx": 8192, "results": results,
                        "gpu_summary": {}, "vram_peak_delta": 12000 + i * 3000})
    ts = _dt.datetime.now()
    # ÖNEMLİ: selftest çıktısı ASLA Model_raporları'na yazılmaz -> ayrı _selftest/ klasörü
    sdir = os.path.join(BASE_DIR, "_selftest")
    os.makedirs(sdir, exist_ok=True)
    rm = {"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "temperature": args.temperature,
          "max_tokens": args.max_tokens}
    out = os.path.join(sdir, f"KARSILASTIRMA_SELFTEST_{ts.strftime('%Y%m%d_%H%M%S')}.pdf")
    build_combined_pdf(out, records, rm)
    KAYIT.yaz(sdir, records, rm)          # kayıt + analiz yolu selftest'te de sınansın
    print(f"✔ Birleşik selftest PDF: {out}")
    _madde_analizi_yaz(records)


def main():
    ap = argparse.ArgumentParser(description="Tüm lokal LLM'leri test eden orkestratör (tek GPU).")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out-dir", default=OUTPUT_BASE,
                    help="Raporların üst klasörü (vars: ./Model_raporları)")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="0 = greedy (tekrarlanabilir/deterministik kıyas)")
    ap.add_argument("--repeat-penalty", type=float, default=1.1,
                    help="Tekrar cezası (0000 bozulmasını önler; model kartı önerisi 1.1)")
    ap.add_argument("--max-tokens", type=int, default=0,
                    help="Yanıt başına maksimum token. 0 = OTOMATİK: bağlamın izin verdiği maksimum (n_ctx - 2048)")
    ap.add_argument("--no-think", action="store_true",
                    help="Düşünmeyi (reasoning) kapat — enable_thinking=false")
    ap.add_argument("--tekrar", type=int, default=1, metavar="K",
                    help="Her puanlı soru K kez sorulur, puan ortalanır (avg@K). "
                         "Kart ayarıyla koşarken gürültüyü bastırır.")
    ap.add_argument("--deterministik", action="store_true",
                    help="Model profillerini yok say, hepsini temperature=0 ile koş "
                         "(eski rejim; karşılaştırılabilir taban).")
    ap.add_argument("--gpu-interval", type=float, default=0.5)
    ap.add_argument("--load-timeout", type=int, default=300)
    ap.add_argument("--gen-launchers", action="store_true")
    ap.add_argument("--no-per-model-pdf", action="store_true")
    ap.add_argument("--combined-selftest", action="store_true")
    args = ap.parse_args()
    try:
        import reportlab  # noqa
    except ImportError:
        sys.exit("HATA: reportlab kurulu değil -> pip install reportlab")

    if args.gen_launchers:
        gen_launchers()
        return
    if args.combined_selftest:
        run_combined_selftest(args)
        return

    # Yollar makineye göre değişir; eksikse NE yapılacağını söyleyip dur.
    # (selftest sunucu/model istemediği için ondan SONRA denetlenir.)
    _hata = CFG.dogrula()
    if _hata:
        sys.exit(_hata)

    try:
        requests.get(BASE_URL + "/health", timeout=2)
        sys.exit(f"HATA: {BASE_URL} meşgul. Açık llama-server'ı kapat (betik modelleri kendi açar).")
    except requests.exceptions.RequestException:
        pass

    # İlk kurulum: launch/ boşsa tüm modeller için launcher üret. Doluysa DOKUNMA
    # (kullanıcının launch_1/ gibi yerlere taşıdığı modeller testten çıkmış sayılır).
    if not glob.glob(os.path.join(LAUNCH_DIR, "open_*.sh")):
        print("launch/ boş — ilk kurulum: tüm modeller için launcher üretiliyor...")
        gen_launchers()

    models = models_from_launchers()
    if not models:
        sys.exit(f"launch/ klasöründe test edilecek model yok. "
                 f"Önce: python {os.path.basename(__file__)} --gen-launchers")
    if args.only:
        wanted = set(args.only)
        models = [m for m in models if m["file"] in wanted or alias_of(m) in wanted]
        if not models:
            sys.exit("--only ile launch/ içinde eşleşen model yok.")

    ts0 = _dt.datetime.now()
    root, per_model_dir = make_output_dirs(args.out_dir, ts0)
    print(f"== launch/ içindeki {len(models)} model test edilecek (tek GPU) ==")
    print(f"   (testten çıkarmak için ilgili open_*.sh'yi launch/ dışına taşı, örn. launch_1/)")
    print(f"   çalışma klasörü: {root}")
    print(f"   (genel rapor buraya, tekli raporlar -> model_raporlari/ alt klasörüne)")

    records, seen = [], set()
    for i, cfg in enumerate(models, 1):
        print(f"\n[{i}/{len(models)}] {cfg['file']}")
        if not os.path.exists(model_path(cfg)):
            print("   ✘ dosya yok, atlanıyor.")
            records.append({"file": cfg["file"], "name": alias_of(cfg), "ok": False,
                            "error": "Model dosyası bulunamadı", "results": [],
                            "gpu_summary": {}, "vram_peak_delta": 0, "params": {}, "ctx": None})
            continue
        if alias_of(cfg) in seen:
            print(f"   (aynı model '{alias_of(cfg)}' zaten test edildi — atlanıyor.)")
            continue
        seen.add(alias_of(cfg))
        rec = test_one_model(cfg, args)
        records.append(rec)
        if rec["ok"] and not args.no_per_model_pdf:
            ts = _dt.datetime.now()
            rm = {"url": BASE_URL, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                  "temperature": args.temperature, "max_tokens": rec.get("max_tokens") or args.max_tokens}
            mi = {"name": rec["name"], "model_path": None, "params": rec["params"], "served_id": rec["name"]}
            fn = os.path.join(per_model_dir, f"rapor_{safe_name(rec['name'])}_{ts.strftime('%Y%m%d_%H%M')}.pdf")
            try:
                build_pdf(fn, mi, rec["gpu_summary"], rec["results"], rm)
                print(f"   ✔ model PDF: {os.path.basename(per_model_dir)}/{os.path.basename(fn)}")
            except Exception as e:
                print(f"   [uyarı] model PDF üretilemedi: {e}")

    ts = _dt.datetime.now()
    mt_disp = args.max_tokens if args.max_tokens > 0 else f"oto(≈{CFG.DEFAULT_CTX - 2048})"
    rm = {"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "temperature": args.temperature,
          "max_tokens": mt_disp}
    out = os.path.join(root, f"KARSILASTIRMA_{ts.strftime('%Y%m%d_%H%M')}.pdf")
    build_combined_pdf(out, records, rm)
    # Ham sonuçlar: madde analizi ve yeniden puanlama modelleri tekrar
    # çalıştırmadan yapılabilsin diye PDF'in YANINA yazılır.
    try:
        jyol = KAYIT.yaz(root, records, rm)
    except Exception as e:
        jyol = None
        print(f"   [uyarı] sonuclar.json yazılamadı: {e}")
    ok_n = sum(1 for r in records if r["ok"])
    print(f"\n==== BİTTİ: {ok_n}/{len(records)} model test edildi ====")
    print(f"✔ Birleşik PDF: {out}")
    print(f"✔ Model PDF'leri: {per_model_dir}/")
    if jyol:
        print(f"✔ Ham sonuçlar: {jyol}")
    _madde_analizi_yaz(records)


if __name__ == "__main__":
    main()

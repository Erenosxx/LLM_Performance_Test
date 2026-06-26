#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seçili lokal LLM'leri test eden orkestratör.

HANGİ MODELLER TEST EDİLİR? -> SADECE `launch/` klasöründe `.sh` dosyası olan modeller.
Bir modeli testten çıkarmak için onun `open_*.sh` dosyasını `launch/` dışına (örn. `launch_1/`)
taşı. Tekrar dahil etmek için geri koy. Kod, `launch/`'ı KENDİLİĞİNDEN yeniden ÜRETMEZ
(taşıdıkların korunur); ilk kurulumda `launch/` boşsa tüm modeller için launcher üretir.

Her model için sırayla: llama-server'ı ÇİFT GPU'da açar -> /health hazır olunca
tüm soruları (1 yaratıcılık + 5 kod + 5 SQL + 5 matematik) uygular + GPU/VRAM ölçer
-> sunucuyu kapatır -> sonraki model. Açılmazsa durmaz, sonrakine geçer.

ÇIKTI YAPISI (her çalıştırmada YENİ, benzersiz klasör; eskiler silinmez):
    Model_raporları/
        calisma_<tarih-saat>/                <- bu çalıştırmanın klasörü
            KARSILASTIRMA_<tarih>.pdf        <- genel rapor
            model_raporlari/                 <- tekli model PDF'leri (alt klasör)
                rapor_<model>_<tarih>.pdf

TÜM modeller eşit/adil koşul için ÇİFT GPU (-sm layer, 0,1) + flash attention (-fa on) ile açılır.

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
import subprocess
import sys
import time

import requests

import models_config as CFG
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
# Sunucu yönetimi (her model ÇİFT GPU)
# ---------------------------------------------------------------------------

def launch_server(cfg, log_path):
    """TÜM modeller ÇİFT GPU + flash attention ile açılır (eşit/adil koşul, OOM riski yok)."""
    ctx = cfg.get("ctx", CFG.DEFAULT_CTX)
    ngl = cfg.get("ngl", CFG.DEFAULT_NGL)
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = "0,1"     # eşit kıyas: her model iki 4090'da
    cmd = [CFG.LLAMA_SERVER, "-m", model_path(cfg), "-c", str(ctx), "-ngl", str(ngl),
           "-fa", "on", "-sm", "layer", "--host", CFG.HOST, "--port", str(CFG.PORT),
           "-a", alias_of(cfg), "--jinja"]
    logf = open(log_path, "w")
    logf.write("CMD: " + " ".join(cmd) + "\nCUDA_VISIBLE_DEVICES=0,1\n\n")
    logf.flush()
    proc = subprocess.Popen(cmd, env=env, stdout=logf, stderr=subprocess.STDOUT)
    return proc, logf, ctx, "çift GPU"


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


def stop_server(proc, logf):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
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
        gpu = GpuMonitor(interval=args.gpu_interval)
        gpu.start()
        try:
            rec["results"] = run_questions(BASE_URL, info["served_id"], args, mt)
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

SHORT_CAT = {"Yaratıcılık": "Yarat.", "Kod": "Kod", "SQL": "SQL",
             "Matematik": "Mat", "Hata Ayıklama": "Hata"}
CAT_COLORS = ["#1a3c5e", "#15803d", "#d97706", "#7c3aed", "#be123c", "#0891b2"]


def graded_categories():
    """Puanlanan kategoriler (Yaratıcılık hariç), CATEGORIES sırasında + soru sayıları."""
    from collections import Counter
    gc = Counter(q["kategori"] for q in QUESTIONS if q["grader"])
    return [c for c in CATEGORIES if gc.get(c, 0) > 0], gc


def build_perf_chart(records):
    """Modellerin otomatik skorunu, puanlanan TÜM kategorilere göre yığılmış sütun grafiği çizer
    (kategori sayısı/branş eklense de kendini günceller). reportlab.graphics ile."""
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.legends import Legend
    from reportlab.lib import colors

    gcats, gc = graded_categories()
    maxscore = sum(gc[c] for c in gcats)

    def total_score(r):
        cs = category_summary(r["results"])
        return sum(cs[c]["passed"] for c in gcats)

    ok = sorted([r for r in records if r["ok"]], key=total_score, reverse=True)
    if not ok:
        return None
    names = [re.sub(r"^(google_|Qwen_)", "", r["name"]) for r in ok]
    cs_all = [category_summary(r["results"]) for r in ok]
    series = [[cs[c]["passed"] for cs in cs_all] for c in gcats]   # her kategori bir seri
    totals = [sum(cs[c]["passed"] for c in gcats) for cs in cs_all]

    width, height = 524, 300
    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x, bc.y = 28, 95
    bc.width, bc.height = width - 56, 160
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

    leg = Legend()
    leg.x, leg.y = 28, 288
    leg.boxAnchor = "nw"
    leg.fontName = "DejaVu"
    leg.fontSize = 8
    leg.dx = leg.dy = 7
    leg.dxTextSpace = 4
    leg.columnMaximum = 1
    leg.deltax = 70
    leg.colorNamePairs = [(colors.HexColor(CAT_COLORS[i % len(CAT_COLORS)]),
                           f"{SHORT_CAT.get(c, c)} /{gc[c]}") for i, c in enumerate(gcats)]
    d.add(leg)
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
                        f"&nbsp;|&nbsp; çift GPU", S["SMALL"]))
    el.append(HRFlowable(width="100%", color=colors.grey, spaceBefore=6, spaceAfter=8))

    # ---- TABLO 1: skorlar (puanlanan tüm kategoriler dinamik) ----
    gcats, _gc = graded_categories()
    _ntot = sum(_gc[c] for c in gcats)
    el.append(Paragraph("1) Skor Karşılaştırması", S["H2"]))
    rows = [["Model"] + [f"{SHORT_CAT.get(c, c)} /{_gc[c]}" for c in gcats]
            + [f"Oto /{_ntot}", "Σ süre (s)", "ort tok/s", "VRAM (GB)"]]

    def sort_key(r):
        if not r["ok"]:
            return (1, 0, 9e9)
        cs = category_summary(r["results"])
        tot = sum(cs[c]["passed"] for c in gcats)
        return (0, -tot, sum(x["total"] for x in r["results"]))

    import statistics as _st
    for rec in sorted(records, key=sort_key):
        if not rec["ok"]:
            rows.append([NM(rec["name"])] + ["—"] * len(gcats) + ["AÇILMADI", "—", "—", "—"])
            continue
        cs = category_summary(rec["results"])
        oto = sum(cs[c]["passed"] for c in gcats)
        oton = sum(cs[c]["graded"] for c in gcats)
        tot = sum(x["total"] for x in rec["results"])
        tps = _st.mean([x["tokens_per_sec"] for x in rec["results"] if x["tokens_per_sec"]] or [0])
        rows.append([NM(rec["name"])] + [f"{cs[c]['passed']}/{cs[c]['graded']}" for c in gcats]
                     + [f"{oto}/{oton}", f"{tot:.0f}", f"{tps:.1f}", f"{rec['vram_peak_delta']/1024:.1f}"])
    colW = [40*mm] + [14*mm] * len(gcats) + [15*mm, 18*mm, 15*mm, 16*mm]
    t = Table(rows, colWidths=colW)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), fb),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")])]))
    el.append(t)
    el.append(Paragraph(
        f"<b>Sütunlar:</b> Kategori sütunları = o kategoride geçilen soru / toplam soru "
        f"(Kod=kod yazma+okuma, Hata=hata ayıklama) · Oto /{_ntot} = tüm otomatik puanların toplamı · "
        "Σ süre (s) = tüm soruların toplam yanıt süresi · ort tok/s = ortalama üretim hızı · "
        "VRAM (GB) = açılış öncesine göre tepe VRAM artışı (iki GPU). Yaratıcılık otomatik puanlanmaz.",
        S["SMALL"]))

    # ---- GENEL PERFORMANS SÜTUN GRAFİĞİ ----
    chart = build_perf_chart(records)
    if chart is not None:
        el.append(Paragraph(f"Genel Performans (otomatik skor /{_ntot}, yüksekten düşüğe)", S["H2"]))
        el.append(chart)

    # ---- TABLO 2: süreler ----
    el.append(Paragraph("2) Kategori Bazında Toplam Süre (s)", S["H2"]))
    rows2 = [["Model"] + [SHORT_CAT.get(c, c) for c in CATEGORIES]]
    for rec in records:
        if not rec["ok"]:
            continue
        rows2.append([NM(rec["name"])] + [f"{category_summary(rec['results'])[c]['time']:.0f}" for c in CATEGORIES])
    _pw = (170 - 44) / max(1, len(CATEGORIES))
    t2 = Table(rows2, colWidths=[44*mm] + [_pw*mm] * len(CATEGORIES))
    t2.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), fb),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")])]))
    el.append(t2)
    el.append(Paragraph("<b>Sütunlar:</b> Her hücre, o kategorideki tüm soruların TOPLAM yanıt "
                        "süresidir (saniye). Düşük = daha hızlı.", S["SMALL"]))

    # ---- TABLO 3: Kaynak Kullanımı (modellerin harcadığı kaynaklar + ortalama token/s) ----
    el.append(Paragraph("3) Kaynak Kullanımı", S["H2"]))
    rows3 = [["Model", "Ort. token/s", "Toplam token", "Σ süre (s)", "Tepe VRAM (GB)", "GPU ort/tepe %"]]
    for rec in records:
        if not rec["ok"]:
            continue
        atps = avg_tokens_per_sec(rec["results"])
        ttok = sum(r.get("completion_tokens", 0) for r in rec["results"])
        ttime = sum(r.get("total", 0) for r in rec["results"])
        uavg, umax = gpu_util_stats(rec["gpu_summary"])
        rows3.append([NM(rec["name"]), f"{atps:.1f}", f"{ttok}", f"{ttime:.0f}",
                      f"{rec['vram_peak_delta']/1024:.1f}", f"{uavg:.0f}/{umax:.0f}"])
    t3 = Table(rows3, colWidths=[54*mm, 22*mm, 24*mm, 20*mm, 26*mm, 24*mm])
    t3.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), fb),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")])]))
    el.append(t3)
    el.append(Paragraph(
        "<b>Sütunlar:</b> Ort. token/s = toplam üretilen token / toplam üretim süresi (yüksek = hızlı) · "
        "Toplam token = üretilen toplam token sayısı · Σ süre (s) = toplam yanıt süresi · "
        "Tepe VRAM (GB) = açılış öncesine göre iki GPU'daki en yüksek VRAM artışı toplamı · "
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
# Launcher üreteci (hepsi çift GPU)
# ---------------------------------------------------------------------------

def gen_launchers():
    os.makedirs(LAUNCH_DIR, exist_ok=True)
    n = 0
    for cfg in CFG.MODELS:
        ctx = cfg.get("ctx", CFG.DEFAULT_CTX)
        ngl = cfg.get("ngl", CFG.DEFAULT_NGL)
        sh = os.path.join(LAUNCH_DIR, "open_" + safe_name(alias_of(cfg)) + ".sh")
        content = f"""#!/usr/bin/env bash
# {cfg['file']}  (çift GPU)  -> http://{CFG.HOST}:{CFG.PORT}
set -e
export CUDA_VISIBLE_DEVICES=0,1
"{CFG.LLAMA_SERVER}" \\
  -m "{model_path(cfg)}" \\
  -c {ctx} -ngl {ngl} -sm layer -fa on \\
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
            passed, detail, outinfo = grade_answer(q, text)
            results.append({**q, "text": text, "ttft": 0.1, "total": 1.0 + i,
                            "completion_tokens": 50, "tokens_per_sec": 30 - i * 4,
                            "passed": passed, "grade_detail": detail, "grade_output": outinfo})
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
    print(f"✔ Birleşik selftest PDF: {out}")


def main():
    ap = argparse.ArgumentParser(description="Tüm lokal LLM'leri test eden orkestratör (çift GPU).")
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
    print(f"== launch/ içindeki {len(models)} model test edilecek (çift GPU) ==")
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
    ok_n = sum(1 for r in records if r["ok"])
    print(f"\n==== BİTTİ: {ok_n}/{len(records)} model test edildi ====")
    print(f"✔ Birleşik PDF: {out}")
    print(f"✔ Model PDF'leri: {per_model_dir}/")


if __name__ == "__main__":
    main()

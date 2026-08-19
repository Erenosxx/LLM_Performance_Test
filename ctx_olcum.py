#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Her model için tek GPU'ya SIĞAN en büyük context'i ÖLÇER.

Neden ölçüm: VRAM hesabı modelin katman/başlık düzenine bağlı ve tahminle
yapılamıyor. 17-18 Ağu ölçümlerinde aynı boyuttaki iki model 4k'da 17,6 GB ve
20,8 GB kullandı; KV büyüme hızları da farklıydı (65 vs 95 MiB/1k token).

Yöntem: her aday context için sunucuyu gerçekten açar, /health bekler, kısa bir
üretim yaptırır (yükleme sığıp üretimde patlayan durumları yakalamak için) ve
VRAM tepe değerini kaydeder. Başarısız olan adayda o model için durur.

Kullanım:
    python ctx_olcum.py                    # launch/ içindeki tüm modeller
    python ctx_olcum.py --only Qwen3.8-27B-Q4_K_M
    python ctx_olcum.py --kv q8_0          # KV kuantizasyonu ile dene
    python ctx_olcum.py --merdiven 32768,65536,98304

Çıktı: ctx_olcum_sonuc.json + konsol tablosu. Sonuçlar bench/profiles.py'deki
`ctx` değerlerine ELLE işlenir (otomatik yazmaz — ölçüm ile yapılandırma
arasına insan kararı girsin).
"""

import argparse
import json
import os
import re
import signal
import subprocess
import time

import requests

import models_config as CFG

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LAUNCH_DIR = os.path.join(BASE_DIR, "launch")
URL = f"http://{CFG.HOST}:{CFG.PORT}"
MERDIVEN = [32768, 49152, 65536, 98304, 131072]
GUVENLIK_PAYI_MIB = 400          # üretim sırasındaki küçük büyümeler için


def vram():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        kul, top = (int(x) for x in out.splitlines()[0].split(","))
        return kul, top
    except Exception:
        return -1, -1


def modeller():
    cikti = []
    for sh in sorted(os.listdir(LAUNCH_DIR)):
        if not sh.startswith("open_") or not sh.endswith(".sh"):
            continue
        txt = open(os.path.join(LAUNCH_DIR, sh)).read()
        m = re.search(r'-m\s+"([^"]+)"', txt)
        if m:
            cikti.append({"ad": re.sub(r"\.gguf$", "", os.path.basename(m.group(1))),
                          "yol": m.group(1)})
    return cikti


def dene(yol, ad, ctx, kv=None, zaman_asimi=300):
    """Tek deneme -> (basarili, tepe_vram, not)."""
    cmd = [CFG.LLAMA_SERVER, "-m", yol, "-c", str(ctx), "-ngl", "99",
           "-sm", "none", "-fa", "on", "--host", CFG.HOST, "--port", str(CFG.PORT),
           "-a", ad, "--jinja"]
    if kv:
        cmd += ["-ctk", kv, "-ctv", kv]
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="0")
    log = open(os.path.join(BASE_DIR, "logs", f"ctx_{ad}_{ctx}.log"), "w")
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        son = time.time() + zaman_asimi
        hazir = False
        while time.time() < son:
            if proc.poll() is not None:
                return False, 0, "süreç çıktı (büyük olasılıkla OOM)"
            try:
                if requests.get(URL + "/health", timeout=2).ok:
                    hazir = True
                    break
            except requests.RequestException:
                pass
            time.sleep(2)
        if not hazir:
            return False, 0, "zaman aşımı"
        yukleme, toplam = vram()
        # Üretim denemesi: yükleme sığıp üretimde patlayan durumu yakalar.
        try:
            r = requests.post(URL + "/v1/chat/completions", timeout=180, json={
                "messages": [{"role": "user", "content": "Merhaba, kısa bir cümle yaz."}],
                "max_tokens": 64, "temperature": 0})
            if not r.ok:
                return False, yukleme, f"üretim hatası HTTP {r.status_code}"
        except requests.RequestException as e:
            return False, yukleme, f"üretim isteği başarısız: {str(e)[:60]}"
        tepe, toplam = vram()
        tepe = max(tepe, yukleme)
        if tepe > toplam - GUVENLIK_PAYI_MIB:
            return False, tepe, f"pay yetersiz ({tepe}/{toplam} MiB)"
        return True, tepe, f"{tepe}/{toplam} MiB"
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=30)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        log.close()
        time.sleep(6)      # VRAM'in geri verilmesi


def main():
    ap = argparse.ArgumentParser(description="Model başına sığan en büyük context'i ölç.")
    ap.add_argument("--only", nargs="*", help="yalnız bu modeller")
    ap.add_argument("--kv", default=None, choices=["q8_0", "q4_0"],
                    help="KV kuantizasyonu (varsayılan: f16)")
    ap.add_argument("--merdiven", default=None, help="virgülle ayrık context adayları")
    args = ap.parse_args()

    merdiven = ([int(x) for x in args.merdiven.split(",")] if args.merdiven else MERDIVEN)
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    hedefler = modeller()
    if args.only:
        hedefler = [m for m in hedefler if m["ad"] in args.only]
    if not hedefler:
        raise SystemExit("launch/ içinde model bulunamadı.")

    _, toplam = vram()
    print(f"GPU toplam: {toplam} MiB · KV: {args.kv or 'f16'} · "
          f"merdiven: {', '.join(str(c) for c in merdiven)}\n")
    sonuc = {}
    for m in hedefler:
        print(f"== {m['ad']}")
        en_iyi, kayit = None, []
        for ctx in merdiven:
            ok, tepe, aciklama = dene(m["yol"], m["ad"], ctx, kv=args.kv)
            print(f"   {ctx:>7} → {'SIĞDI ' if ok else 'SIĞMADI'}  {aciklama}")
            kayit.append({"ctx": ctx, "ok": ok, "vram": tepe, "not": aciklama})
            if ok:
                en_iyi = ctx
            else:
                break            # merdiven artan; ilk başarısızlıkta dur
        sonuc[m["ad"]] = {"kv": args.kv or "f16", "en_buyuk_ctx": en_iyi, "denemeler": kayit}
        print(f"   -> en büyük: {en_iyi}\n")

    yol = os.path.join(BASE_DIR, f"ctx_olcum_sonuc{'_' + args.kv if args.kv else ''}.json")
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(sonuc, f, ensure_ascii=False, indent=1)
    print(f"{'model':<40}{'KV':<8}{'en büyük ctx':>13}")
    for ad, s in sonuc.items():
        print(f"{ad:<40}{s['kv']:<8}{str(s['en_buyuk_ctx']):>13}")
    print(f"\n✔ {yol}")
    print("Not: değerler bench/profiles.py'ye ELLE işlenir, sonra --gen-launchers.")


if __name__ == "__main__":
    main()

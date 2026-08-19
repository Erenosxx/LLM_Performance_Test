# LLM Performance Test

[Türkçe](README.md) · **English**

Benchmarks local LLMs (llama-server / any OpenAI-compatible `/v1` endpoint) against a
fixed question set, measures latency and GPU usage, **grades code/SQL/math answers
automatically**, and produces a PDF report.

## Quick start

The only configuration needed is **two paths**: where your models live and where the
`llama-server` binary is.

```bash
# 1) dependencies
pip install -r requirements.txt

# 2) machine-specific paths (this file is gitignored, it never reaches the repo)
cp ayarlar_yerel.ornek.py ayarlar_yerel.py
$EDITOR ayarlar_yerel.py         # LLM_MODELS_DIR and LLAMA_SERVER

# 3) pick which models to test: models_config.py -> MODELS list
#    (write the .gguf file names found in your model directory)

# 4) run — if launch/ is empty, the launch scripts are generated automatically
python run_models.py
```

You can also supply the paths as environment variables (these take precedence):

```bash
export LLM_MODELS_DIR=/data/models
export LLAMA_SERVER=~/llama.cpp/build/bin/llama-server
```

If a path is missing or wrong, the program tells you exactly what to do and stops —
it never fails halfway through a run.

**Is the setup correct?** Verify without any model or server:

```bash
python run_models.py --combined-selftest   # whole grading + PDF chain on fake data
python -m pytest bench/ -q                 # grader unit tests
```

> `llama-server` is not part of this project; build it from
> [llama.cpp](https://github.com/ggml-org/llama.cpp) and point to it. The `.gguf`
> model files are downloaded separately as well.

## Question set (identical for every model)

**12 branches, 139 questions — 133 of them graded automatically.**

| Branch | Questions | Graded | How it is graded |
|---|---|---|---|
| Creativity | 6 | 0 | No — human judgement (criteria printed in the PDF) |
| Code / algorithms | 16 | 16 | The function is executed against fixed input/output pairs |
| SQL | 13 | 13 | Compared row by row against a reference query in SQLite |
| Math | 13 | 13 | The `#### <number>` answer is compared to the known result |
| Debugging | 14 | 14 | BROKEN code is given; the fixed code is executed and tested |
| Agentic | 14 | 14 | Multi-turn TOOL use; the model must gather data and infer |
| Medical | 13 | 13 | Required medical term(s) searched together with synonyms |
| Instruction following | 13 | 13 | Every constraint is machine-checked (item count, banned word, ordering…) |
| JSON | 11 | 11 | Valid JSON (0.30) + schema conformance (0.40) + field values (0.30) |
| Hallucination | 10 | 10 | Must admit ignorance on unanswerable questions and reject false premises |
| Turkish | 10 | 10 | Medical terminology: fix the corrupted term, LEAVE the legitimate one alone |
| Long context | 6 | 6 | Needle / contradiction / synthesis tasks over a generated long document |

Three branches in more detail:
- **Hallucination** — (a) *unanswerable*: specific data is requested about a study or
  protocol that does not exist; the correct behaviour is to say so. (b) *false premise*:
  the question presents a fictional event as fact; the correct behaviour is to reject it.
- **Turkish** — the questions were not invented; they were derived from **real Whisper
  ASR corruptions** collected during the TÜBİTAK WP6 evaluation. (a) *correction*: the
  term really is broken (no such word as "intertorakal"); (b) *leave alone*: both forms
  are legitimate ("miyokart") or the text is a faithful transcript of spoken language
  ("nerden") — the model must not touch it.
- **Long context** — documents are generated programmatically (no external data, fixed
  seed, byte-identical on every run). *needle*: a single fact is buried at 10%/50%/90%
  depth; *contradiction*: the same fact appears differently in two places and the model
  must catch it; *synthesis*: the answer requires combining facts from three sections.

**Weighted scoring:** every question carries a difficulty tier — easy ×1, medium ×2,
hard ×3, brutal ×4. The "weighted score" in the report is Σ (partial credit × tier
weight), so solving one brutal question is worth four easy ones.

> **Note on the JSON branch:** if `jsonschema` is not installed, the schema stage is
> skipped and its 0.40 is granted unconditionally (a warning is printed during the
> run). `pip install -r requirements.txt` installs it.

**Competition level** (inspired by LeetCode / AIME / Spider 2.0 — the point is to
separate strong models), easy → very hard:

- **Code:** roman numerals → edit distance (Levenshtein) → word break → N-Queens →
  longest increasing path → **regex matching (DP)** → **largest rectangle in histogram
  (stack)** → **word ladder (BFS)** — the last three are LeetCode **Hard**
- **SQL** (schema `calisanlar` + `satislar`): HAVING → self-join → RANK() →
  ROW_NUMBER top-2 → cumulative SUM() OVER → **recursive CTE (hierarchy)** →
  **LAG (month-over-month delta)** → **DENSE_RANK (second highest)**
- **Math** (AIME/olympiad style, single integer, `#### <number>` format): modular
  Fermat → inclusion-exclusion → combinatorics → x²−y²=2025 → 1/x+1/y=1/12 →
  **trailing zeros of 100!** → **inclusion-exclusion committee** → **three-dice counting**
- **Debugging** (measures the diagnose → fix → verify loop): broken `en_buyuk` /
  `carpim` / `tekrar_eden_var_mi` / `ortalama` / `fib` are given, the model repairs
  them, the result is tested automatically
- **Code reading** (read before act): the model traces a snippet step by step and
  reports the output as `#### <number>`
- **Agentic** (`agentic.py` — multi-turn tool use): the model calls a tool → we run it
  in a sandbox and feed the result back → until it reaches a conclusion (25-turn limit).
  Medium: inconsistent bookkeeping entry (invariant), intersection of 5 clues (→462),
  multi-source inference. Very hard: black box — probe a hidden f(x) for 1–6, infer the
  rule, compute f(10) (induction); logic puzzle — zebra-style 4×city×profession
  (deduction); shortest path — A→F Dijkstra (algorithmic search). A model that cannot
  do tool calling, or infers wrongly, scores 0; the run does not stop.

## How answers are judged "correct"

- **CODE:** the function the model wrote is extracted, executed in a separate Python
  process (15 s timeout, infinite-loop protection) against fixed **input → expected
  output** pairs. It **passes** only if every input yields the right result.
- **SQL:** fixed data is loaded into an in-memory SQLite database; the model's query
  and the **reference query** run against it and must return **identical rows**
  (column names are irrelevant; ordering is checked when the question requires it).
- **MATH:** numbers and fractions in the answer (e.g. `12/5`, `2.4`) are parsed; it
  passes if the known result is found within tolerance.
- **CREATIVITY:** not graded automatically; the answer goes into the PDF along with the
  evaluation criteria (originality, language, structure, constraint compliance).

> Oracle consistency was verified: every reference solution **passes** the graders and
> wrong answers are **rejected**.

## A) Testing a single model

```bash
# start the model (example)
"$LLAMA_SERVER" -m <model.gguf> -c 32768 -ngl 99 \
  -sm none -fa on --host 127.0.0.1 --port 8080 --jinja
# test it
python llm_perf_test.py --url http://localhost:8080
```

Grader + PDF dry run without a server: `python llm_perf_test.py --selftest`

## B) Testing several models automatically (orchestrator)

`run_models.py` starts each model **itself**, tests it, shuts it down, moves on.

**WHICH MODELS? → ONLY those with a `.sh` file in the `launch/` directory.**
To exclude a model, move its `open_*.sh` out of `launch/` (e.g. into a `launch_1/`
directory next to it). To include it again, move it back. The code never regenerates
`launch/` on its own, so your choices persist.

```bash
# there must be NO llama-server already listening on 8080 (the script starts them)
python run_models.py                        # test the models in launch/
python run_models.py --gen-launchers        # (re)generate launch/*.sh for ALL models
python run_models.py --only Qwen3.8-27B-Q4_K_M   # extra filter, without moving files
python run_models.py --tekrar 3             # ask every graded question 3× (avg@3)
python run_models.py --deterministik        # ignore profiles, run everything at temp 0
python run_models.py --combined-selftest    # PDF layout test on fake data
```

> On a fresh clone `launch/` is empty, so launchers are generated automatically on the
> first run. Beware: `--gen-launchers` rewrites **all** of them — hand edits are lost.

**Output layout** (a NEW, unique directory per run; nothing is ever overwritten):

```
Model_raporları/
    calisma_<date-time>/                 # this run's directory
        KARSILASTIRMA_<date>.pdf         # comparison report
        sonuclar.json                    # raw results (re-scoring, item analysis)
        model_raporlari/                 # per-model PDFs
            rapor_<model1>_<date>.pdf
            ...
```

- **GPU:** launchers target a single GPU (`CUDA_VISIBLE_DEVICES=0`, `-sm none`,
  `-fa on`). For multi-GPU, edit `launch/open_*.sh` by hand — the code will not touch them.
- Model pool lives in `models_config.py` → `MODELS`; machine-specific paths in
  `ayarlar_yerel.py`. Launchers are generated from those two, and `launch/*.sh` is
  gitignored.
- If a model fails to start the run **does not stop**: the error goes to
  `logs/<model>.log` and the report shows "AÇILMADI" (did not start).

**What the comparison PDF contains:**

- Score comparison (weighted score, %, fully passed, stability, total time, tok/s,
  measured ctx), weighted score per branch, the parameters each model actually ran
  with, a stacked bar chart by branch, and a timing table
- **Item analysis:** which questions actually separate the models and which produce no
  discrimination at all
- A "Questions" section with every question and its reference answer
- One page per model with its answer to every question, branch by branch

## Measured metrics

- **TTFT** (time to first token), total time, **tokens/sec**, tokens generated
- **GPU/VRAM** in **GB**: min/avg/max VRAM and utilisation per GPU; the comparison
  report shows the peak VRAM increase over the pre-launch baseline

## Sampling parameters — two regimes

**a) Profile regime (default).** Every model runs with the sampling settings its own
model card recommends. The values are not guesses — they were taken from each model's
`generation_config.json` (`bench/profiles.py`):

| Model pattern | temp | top_p | top_k | rep | extra |
|---|---|---|---|---|---|
| `qwen3.8` | 1.0 | 0.95 | 20 | 1.0 | `reasoning_effort=medium` |
| `qwen3.5`–`3.7` | 0.6 | 0.95 | 20 | 1.0 | — |
| `gemma-4`, `gemma-3` | 1.0 | 0.95 | 64 | 1.0 | — |
| no match | 0.0 | 1.0 | — | 1.1 | — |

Rule order matters — the first match wins, which is why the `qwen3.8` rule comes before
`qwen3.[567]`. Adding a new model means adding a pattern to that list.

In this regime the result answers **"what can each model do at its best"** rather than
"which is best under identical conditions". Table 1b of the report prints the exact
parameters every model ran with.

**b) `--deterministik`.** Ignores the profiles and runs everything at `temperature=0`,
for a directly comparable baseline.

> The `--temperature` / `--repeat-penalty` flags of `run_models.py` have **no effect**
> in the profile regime: the request body is built with them first and then overwritten
> by the profile's values. To really change sampling, edit `bench/profiles.py` or use
> `--deterministik`.

### Other parameters

| Argument | Default | Description |
|---|---|---|
| `--max-tokens` | `0` (auto) | 0 = as high as the context allows (`n_ctx - 2048`) |
| `--tekrar K` | `1` | Ask every graded question K times and average the score (avg@K) |
| `--no-think` | off | Disable reasoning (`enable_thinking=false`) |
| `--gpu-interval` | `0.5` | GPU sampling interval (seconds) |
| `--load-timeout` | `300` | (orchestrator) how long to wait for a model to load |

**Context size** comes from a separate path: the explicit `ctx` in
`models_config.MODELS` → the profile's `ctx` → `DEFAULT_CTX` (32k). These values were
**measured** with `ctx_olcum.py`, which actually starts the server at each candidate
context and makes it generate. The ceilings differ by a factor of four between models.

## Reasoning models — why an empty answer?

Models such as Qwen3 first emit `reasoning_content` and only then the final `content`.
If `max_tokens` is too low the model hits the limit **while thinking**
(`finish_reason=length`) and never writes the answer → the report looks empty. Remedies:

- `max_tokens` defaults to AUTO: `n_ctx - 2048` (~30720 at a 32k context), leaving room
  to think and then answer.
- `--no-think` turns reasoning off: the model answers directly (faster, guaranteed output).
- If the answer is still empty the report states **why** (token limit / stuck in the
  thinking stage) and shows part of the reasoning content when available — it is never
  silently blank.

## Note

Timing, UTF-8 handling and the graders were verified end to end against real models
(`python -m pytest bench/ -q`). A full round (all models × 139 questions) can take hours
depending on model size and reasoning mode; narrow it down with `--only`.

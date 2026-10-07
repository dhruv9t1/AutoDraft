> **ARCHIVED / HISTORICAL — NOT CURRENT IMPLEMENTATION.** Legacy LLM training plan. The active backend is Python/FastAPI and the configured local model defaults to `qwen3:4b`. See `../../README.md`, `../../backend/README.md`, and `../CURRENT_ARCHITECTURE.md`.

# LLM Training Plan: Legal Document Variable Extractor

> **Goal:** Train a small, specialized LLM that accurately identifies variables (names, dates, amounts, references, etc.) in Indian legal documents for template drafting in Word.
>
> **Current State:** Using `gpt-oss:120b` via Ollama-compatible API with a 440-line system prompt.
> **Target State:** A fine-tuned 3B-parameter model running locally on Ollama with >95% F1 score, faster inference, and iterative keyword-based improvement.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Phase 1 — Data Collection & Preparation](#2-phase-1--data-collection--preparation)
3. [Phase 2 — Fine-Tuning a Small Model (QLoRA)](#3-phase-2--fine-tuning-a-small-model-qlora)
4. [Phase 3 — Training From Scratch (Optional)](#4-phase-3--training-from-scratch-optional)
5. [Phase 4 — Deployment to Ollama](#5-phase-4--deployment-to-ollama)
6. [Phase 5 — Iterative Keyword Monitoring & Ranking](#6-phase-5--iterative-keyword-monitoring--ranking)
7. [Phase 6 — Evaluation & Metrics](#7-phase-6--evaluation--metrics)
8. [Cloud Infrastructure](#8-cloud-infrastructure)
9. [Framework Comparison](#9-framework-comparison)
10. [Project Directory Structure](#10-project-directory-structure)
11. [Cost Estimates](#11-cost-estimates)
12. [Risk Mitigation](#12-risk-mitigation)
13. [Milestone Checklist](#13-milestone-checklist)

---

## 1. Architecture Overview

### Current Pipeline

```
Word Document
    │
    ▼
Frontend (Office.js) ──extracts text──▶ Rust Backend (Axum)
                                            │
                                            ▼
                                      Chunks document (4KB)
                                            │
                                            ▼
                                      Calls LLM API (gpt-oss:120b)
                                            │
                                            ▼
                                      Parses JSON response
                                            │
                                            ▼
                                      Validates originalText exists in doc
                                            │
                                            ▼
                                      Returns Variable[] to frontend
```

### Target Pipeline

```
Word Document
    │
    ▼
Frontend (Office.js) ──extracts text──▶ Rust Backend (Axum)
                                            │
                                            ▼
                                      Chunks document (3KB)
                                            │
                                            ▼
                                      Calls Ollama (legal-var-extractor 3B)  ◀── CHANGED
                                            │
                                            ▼
                                      Parses JSON response
                                            │
                                            ▼
                                      Validates originalText exists in doc
                                            │
                                            ▼
                                      Returns Variable[] to frontend
                                            │
                                            ▼
                                      Logs prediction for review  ◀── NEW
                                            │
                                            ▼
                                      Keyword tracker updates    ◀── NEW
```

### Iterative Improvement Loop

```
┌─────────────────────────────────────────────────────────────┐
│                    ITERATION CYCLE                           │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ 1. Run model │───▶│ 2. Human     │───▶│ 3. Update     │  │
│  │    on docs   │    │    review    │    │    keyword    │  │
│  │              │    │    outputs   │    │    rankings   │  │
│  └──────────────┘    └──────────────┘    └───────┬───────┘  │
│         ▲                                         │          │
│         │                                         ▼          │
│  ┌──────┴───────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ 6. Deploy    │◀───│ 5. Fine-tune │◀───│ 4. Augment    │  │
│  │    to Ollama │    │    (QLoRA)   │    │    training   │  │
│  │              │    │              │    │    data       │  │
│  └──────────────┘    └──────────────┘    └───────────────┘  │
│                                                              │
│  Target: F1 >= 0.95 on variable extraction                   │
│  Expected iterations to reach target: 3-5                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Phase 1 — Data Collection & Preparation

### 2.1 Data Sources

| Source | Description | Priority |
|--------|-------------|----------|
| Existing templates in database | Documents already processed through current LLM with verified variables | HIGH |
| Raw legal documents | Unprocessed legal notices, complaints, agreements from your practice | HIGH |
| Public legal datasets | Indian Kanoon, court records (for pre-training corpus only) | LOW |

### 2.2 Data Format

Each training sample is a chat-format JSONL entry that mirrors how the model will be called in production:

```jsonl
{
  "messages": [
    {
      "role": "system",
      "content": "You are a legal document variable extractor. Identify all values that would change when reusing this document as a template. Return JSON with variables array containing: variableName, originalText, position, confidenceScore."
    },
    {
      "role": "user",
      "content": "Extract all variables from this document:\n\n<document text here>"
    },
    {
      "role": "assistant",
      "content": "{\"variables\": [{\"variableName\": \"Complainant Name\", \"originalText\": \"Rajesh Kumar Sharma\", \"position\": -1, \"confidenceScore\": 0.95}, ...]}"
    }
  ]
}
```

### 2.3 Data Collection Steps

#### Step 1: Export Existing Data (Automated)

Write a script to pull all templates + verified variables from your PostgreSQL database:

```
Script: scripts/export_training_data.py
Input:  PostgreSQL (templates table + variables)
Output: raw_training_data.jsonl
```

- Query all templates that have been saved with human-reviewed variables
- For each template, reconstruct the (document_text, variables[]) pair
- Format into JSONL chat format
- Expected yield: however many templates you currently have in the database

#### Step 2: Generate Synthetic Labels (Semi-Automated)

For documents that don't have verified labels yet:

```
Script: scripts/generate_labels.py
Input:  Folder of .docx or .txt legal documents
Output: predicted_labels.jsonl (needs human review)
```

- Run each document through your current `gpt-oss:120b` model via the backend API
- Save the predicted variables alongside the document text
- These become "silver" labels (good but not verified)

#### Step 3: Human Review & Correction (Manual)

```
Script: scripts/review_tool.py
Input:  predicted_labels.jsonl
Output: gold_training_data.jsonl
```

Interactive CLI tool for reviewing each document's variables:
- Show each predicted variable and ask: **correct / rename / remove**
- Prompt for **missed variables** the model didn't find
- Track corrections to feed into keyword ranking system
- Export verified (gold) labels

#### Step 4: Data Validation & Splitting

```
Script: scripts/prepare_dataset.py
Input:  gold_training_data.jsonl
Output: train.jsonl (80%), eval.jsonl (10%), test.jsonl (10%)
```

Validation checks:
- Every `originalText` actually exists in the document text
- No duplicate documents across splits
- JSON output is valid and parseable
- Variable names follow naming conventions (PascalCase with spaces)
- Confidence scores are between 0.0 and 1.0

### 2.4 Minimum Data Requirements

| Training Approach | Minimum Samples | Recommended | Notes |
|-------------------|----------------|-------------|-------|
| QLoRA fine-tuning | 100 | 500-1000 | Quality > quantity |
| Full fine-tuning | 500 | 2000-5000 | More data needed without LoRA |
| Training from scratch | 10,000+ | 50,000+ | Need massive corpus |

### 2.5 System Prompt Simplification

Your current system prompt is ~440 lines with exhaustive variable categories. For training, **embed this knowledge into the training examples** instead of the prompt. The fine-tuned model will learn the patterns from data, so the inference prompt can be much shorter:

**Training-time system prompt (detailed):**
```
You are a legal document variable extractor. Identify all values that would change
when reusing this document as a template for a different case or parties...
[full 440-line prompt — used only during data generation]
```

**Inference-time system prompt (short — what the fine-tuned model will use):**
```
You are a legal document variable extractor. Identify all values that would change
when reusing this document as a template. Return JSON with variables array containing:
variableName, originalText, position, confidenceScore.
```

This is a major win: the 3B model doesn't waste context window on instructions it has already internalized through training.

---

## 3. Phase 2 — Fine-Tuning a Small Model (QLoRA)

### 3.1 Base Model Selection

| Model | Parameters | Context | JSON Quality | Hindi/English | Recommendation |
|-------|-----------|---------|-------------|---------------|----------------|
| **Qwen 2.5-3B-Instruct** | 3B | 32K | Excellent | Good | **Primary choice** |
| Phi-3.5-mini-instruct | 3.8B | 128K | Very Good | Fair | Backup option |
| SmolLM2-1.7B-Instruct | 1.7B | 8K | Good | Poor | If speed is critical |
| Llama 3.2-3B-Instruct | 3B | 128K | Good | Fair | Alternative |
| Gemma 2-2B-IT | 2B | 8K | Good | Fair | Lightweight option |

**Primary recommendation: Qwen 2.5-3B-Instruct**

Reasons:
1. Best-in-class JSON output reliability at this size (critical for your pipeline)
2. Good multilingual support (Hindi names, addresses common in Indian legal docs)
3. 32K context window (enough for your 4KB chunks with headroom)
4. Active community, good tooling support
5. Apache 2.0 license (commercial use OK)

### 3.2 QLoRA Configuration

QLoRA = Quantized Low-Rank Adaptation. Freezes the base model in 4-bit precision and trains small adapter layers on top. This means:
- ~75% less GPU memory vs full fine-tuning
- ~90% of full fine-tuning quality
- Can train a 3B model on a single 24GB GPU

**Key hyperparameters:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `r` (LoRA rank) | 32 | Higher than default 16 — structured extraction needs more capacity |
| `lora_alpha` | 64 | Standard 2x of rank |
| `target_modules` | All linear layers | Full coverage for maximum learning |
| `lora_dropout` | 0.05 | Light regularization to prevent overfitting on small dataset |
| `learning_rate` | 2e-4 | Standard for QLoRA |
| `epochs` | 3-5 | Start with 3, increase if training loss hasn't plateaued |
| `batch_size` | 4 (x4 gradient accumulation = effective 16) | Balance between speed and stability |
| `max_seq_length` | 4096 | Matches your OLLAMA_CHUNK_SIZE config |
| `warmup_ratio` | 0.1 | 10% of steps for learning rate warmup |
| `scheduler` | Cosine | Smooth learning rate decay |
| `quantization` | 4-bit (NF4) | QLoRA standard |

### 3.3 Training Script Location

```
File: training/fine_tune.py
```

**Dependencies:**
```
unsloth>=2024.12
transformers>=4.45
trl>=0.12
datasets>=3.0
peft>=0.13
bitsandbytes>=0.44
accelerate>=1.0
```

### 3.4 Training Process

```
Step 1: Load base model (Qwen 2.5-3B) in 4-bit
            │
            ▼
Step 2: Attach LoRA adapters to all linear layers
            │
            ▼
Step 3: Load training data (JSONL → HuggingFace Dataset)
            │
            ▼
Step 4: Apply chat template (Qwen's ChatML format)
            │
            ▼
Step 5: Train with SFTTrainer (3-5 epochs)
            │
            ▼
Step 6: Save LoRA adapter checkpoint
            │
            ▼
Step 7: Merge LoRA weights into base model (16-bit)
            │
            ▼
Step 8: Export merged model for GGUF conversion
```

### 3.5 What the Model Learns

Through fine-tuning, the model internalizes:

1. **Variable categories** — complainant names, accused addresses, cheque numbers, PIN codes, bank details, legal section references, etc.
2. **Output format** — consistent JSON structure with variableName, originalText, position, confidenceScore
3. **Naming conventions** — "Complainant Firm Name" not "Sender Company", "Accused Bank IFSC" not "Receiver's Bank Code"
4. **What NOT to extract** — boilerplate legal language, section headings, the lawyer's own details
5. **Confidence calibration** — assigning appropriate confidence scores based on ambiguity
6. **Table parsing** — extracting values from table cells vs headers
7. **Edge cases** — spaced digits ("0 5 6 9 0 5..."), PIN codes, multi-format dates

---

## 4. Phase 3 — Training From Scratch (Optional)

> **When to consider this:** Only if fine-tuning a 3B model doesn't reach your accuracy target after 5+ iterations, AND you have 10,000+ labeled documents.

### 4.1 Architecture Choice

For a domain-specific model, a smaller architecture trained on focused data can outperform a larger general model:

| Architecture | Parameters | Training Time | When to Use |
|-------------|-----------|---------------|-------------|
| GPT-2 style (decoder-only) | 124M-500M | 1-3 days | Lots of legal text, limited labels |
| Custom NER + classifier | <50M | Hours | If you only need entity extraction (not generation) |
| T5-style (encoder-decoder) | 250M-780M | 2-5 days | If you want both extraction and generation |

### 4.2 Pre-training Corpus

If training from scratch, you need a large corpus of legal text for the pre-training phase:

| Source | Size Estimate | Content |
|--------|--------------|---------|
| Your document archive | 1-10K documents | Indian legal notices, complaints, agreements |
| Indian Kanoon | Millions of judgments | Court judgments (scrape legally, respect ToS) |
| Legal templates online | 1-5K templates | Standard legal formats |
| Government gazette | Varies | Acts, amendments, notifications |

**Pre-training objective:** Standard next-token prediction on legal text (teaches language patterns)
**Fine-tuning objective:** Variable extraction task (teaches the specific output format)

### 4.3 Framework: LitGPT

```
pip install litgpt

# Step 1: Train tokenizer
litgpt tokenize --data ./legal_corpus --vocab_size 32000

# Step 2: Pre-train
litgpt pretrain \
  --model_name legal-extractor-500m \
  --data ./tokenized_corpus \
  --block_size 4096 \
  --n_layer 24 \
  --n_head 16 \
  --n_embd 1024 \
  --max_iters 100000

# Step 3: Fine-tune on variable extraction
litgpt finetune_lora \
  --checkpoint ./pretrained/legal-extractor-500m \
  --data ./training_data.jsonl \
  --out ./finetuned
```

### 4.4 Alternative: NER-Based Approach

If the task is purely extraction (no generation needed), consider a lighter approach:

```
SpaCy NER Pipeline:
  1. Train a custom SpaCy NER model on your labeled data
  2. Entity types = your variable categories
  3. Much faster inference (~10ms vs ~1-5s for LLM)
  4. No JSON parsing issues
  5. But: less flexible, can't handle novel variable types
```

This is a viable hybrid approach:
- Use SpaCy NER for high-confidence common variables (names, dates, amounts)
- Use the small LLM for complex/contextual variables (legal references, table data)

---

## 5. Phase 4 — Deployment to Ollama

### 5.1 GGUF Conversion

GGUF is the format Ollama uses. Convert your merged model:

```bash
# Option A: Using llama.cpp (most reliable)
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && make -j

python convert_hf_to_gguf.py \
  /path/to/legal-var-extractor/merged \
  --outfile legal-var-extractor.gguf \
  --outtype q8_0

# Option B: Using Unsloth (if you trained with Unsloth)
model.save_pretrained_gguf(
    "legal-var-extractor",
    tokenizer,
    quantization_method="q8_0"
)
```

### 5.2 Quantization Options

| Format | Size (3B model) | Quality | Speed | Recommendation |
|--------|-----------------|---------|-------|----------------|
| F16 | ~6 GB | Best | Slow | Development only |
| Q8_0 | ~3.2 GB | Excellent | Good | **Production (accuracy focus)** |
| Q5_K_M | ~2.3 GB | Very Good | Faster | Good balance |
| Q4_K_M | ~1.9 GB | Good | Fastest | If RAM constrained |
| Q4_0 | ~1.7 GB | Fair | Fastest | Not recommended (JSON quality drops) |

**Recommendation: Q8_0** — You need reliable JSON output. Lower quantizations can degrade structured output quality.

### 5.3 Ollama Modelfile

```dockerfile
# File: deployment/Modelfile
FROM ./legal-var-extractor-q8_0.gguf

# Low temperature for consistent, deterministic extraction
PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 4096
PARAMETER num_predict 4096
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"

SYSTEM """You are a legal document variable extractor. Identify all values that would change when reusing this document as a template. Return JSON with variables array containing: variableName, originalText, position, confidenceScore."""

TEMPLATE """<|im_start|>system
{{ .System }}<|im_end|>
<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
"""
```

### 5.4 Ollama Registration

```bash
# Create model
ollama create legal-var-extractor -f deployment/Modelfile

# Verify it loaded
ollama list

# Test with a sample
ollama run legal-var-extractor "Extract variables: Notice No. 602/2023 dated 28/06/2023. To: Rajesh Kumar, Partner of M/s ABC Traders, 45 MG Road, Ahmedabad-380006."

# Expected output:
# {"variables": [
#   {"variableName": "Reference Number", "originalText": "602/2023", "position": -1, "confidenceScore": 0.95},
#   {"variableName": "Notice Date", "originalText": "28/06/2023", "position": -1, "confidenceScore": 0.97},
#   {"variableName": "Accused Name", "originalText": "Rajesh Kumar", "position": -1, "confidenceScore": 0.96},
#   {"variableName": "Accused Firm Name", "originalText": "M/s ABC Traders", "position": -1, "confidenceScore": 0.94},
#   {"variableName": "Accused Address", "originalText": "45 MG Road, Ahmedabad", "position": -1, "confidenceScore": 0.93},
#   {"variableName": "Accused PIN Code", "originalText": "380006", "position": -1, "confidenceScore": 0.95}
# ]}
```

### 5.5 Backend Configuration Changes

Update your `.env` file — **no Rust code changes needed**:

```env
# Before (large cloud model)
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_URL=https://your-cloud-provider.com
OLLAMA_API_PATH=/v1/chat/completions
OLLAMA_THINK_LEVEL=medium
OLLAMA_CHUNK_SIZE=4000
OLLAMA_TIMEOUT_SECONDS=60

# After (small local model)
OLLAMA_MODEL=legal-var-extractor
OLLAMA_API_URL=http://localhost:11434
OLLAMA_API_PATH=/api/chat
OLLAMA_THINK_LEVEL=off
OLLAMA_CHUNK_SIZE=3000
OLLAMA_TIMEOUT_SECONDS=30
```

### 5.6 Deployment Options

| Environment | Setup | Inference Speed | Cost |
|-------------|-------|----------------|------|
| **Local (your server)** | Ollama on Ubuntu VM | ~2-5s per chunk | Free (after GPU purchase) |
| **RunPod Serverless** | GGUF on RunPod endpoint | ~1-3s per chunk | ~$0.0002/request |
| **AWS/GCP with GPU** | Ollama on g5.xlarge | ~1-3s per chunk | ~$1/hr |
| **CPU-only server** | Ollama with Q4_K_M | ~10-30s per chunk | Free (existing server) |

---

## 6. Phase 5 — Iterative Keyword Monitoring & Ranking

This is the core innovation: a systematic feedback loop that identifies what the model misses and boosts those patterns in subsequent training rounds.

### 6.1 Keyword Tracking Concept

Every variable category (e.g., "Complainant PIN Code", "Cheque Number", "Accused Bank Branch") is tracked as a **keyword**. After each review cycle:

- **Hit:** Model correctly identified this variable type -> keyword weight stays stable
- **Miss:** Model failed to identify this variable type -> keyword weight increases
- **Hallucination:** Model fabricated this variable type -> keyword weight decreases

### 6.2 Weight Formula

```
weight = 1.0 + (miss_rate * 2.0) - (hallucination_rate * 1.5)
```

- Clamped to range [0.1, 3.0]
- Weight > 1.0 = under-extracted (needs more training examples)
- Weight < 1.0 = over-extracted (needs negative examples)
- Weight = 1.0 = well-calibrated

### 6.3 Keyword Categories to Track

Based on your current system prompt, these are the keyword groups:

```
PARTIES & PEOPLE:
  - Complainant Name              - Accused Name
  - Complainant Firm Name         - Accused Firm Name
  - Complainant Address           - Accused Address
  - Complainant PIN Code          - Accused PIN Code
  - Complainant GSTIN             - Accused GSTIN
  - Complainant Mobile            - Accused Mobile
  - Complainant Email             - Accused Email
  - Proprietor/Partner Names

CASE & REFERENCE:
  - Reference Number              - Case Number
  - Notice Date                   - Court Name
  - Police Station                - Jurisdiction

LEGAL REFERENCES:
  - Section & Act Reference       - Amendment Reference

BANKING & CHEQUE:
  - Bank Name                     - Bank Branch
  - Account Number                - IFSC Code
  - Cheque Number                 - Cheque Date
  - Cheque Amount (Figures)       - Cheque Amount (Words)
  - Dishonour Date                - Endorsement Status

INVOICE & TRANSACTION:
  - Invoice Number                - Bill Date
  - Bill Amount                   - LR Number
  - Tax Invoice Number

TABLE DATA:
  - Table Cell Values             - GST Registration Details

DOCUMENT SIGNING:
  - Signing Place                 - Signing Date
```

### 6.4 Tracking Script

```
File: training/keyword_tracker.py
```

Features:
- Records every review session with timestamp and document ID
- Calculates per-keyword hit rate, miss rate, hallucination rate
- Computes keyword weights for data augmentation
- Generates reports showing top missed and top hallucinated keywords
- Tracks precision, recall, and F1 across iterations
- Persists state to JSON for continuity across sessions

### 6.5 Data Augmentation Based on Keyword Weights

```
File: training/augment_data.py
```

For each training iteration:
1. Load the keyword tracker state
2. Identify keywords with weight > 1.5 (consistently missed)
3. Find training examples containing those keywords
4. Duplicate those examples 2-5x in the training set
5. Optionally: generate synthetic examples for very weak keywords
6. Save augmented dataset for the next training run

### 6.6 Negative Example Generation

For keywords with weight < 0.5 (consistently hallucinated):

1. Find documents where the model predicts these variables but they don't exist
2. Create training examples where the correct output **does not** include these variables
3. This teaches the model to NOT extract certain patterns when they're not present

Example: If the model keeps hallucinating "Accused Bank Branch" in documents that don't mention banking:

```jsonl
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Extract variables from: <rent agreement with no banking details>"},
    {"role": "assistant", "content": "{\"variables\": [<only non-banking variables>]}"}
  ]
}
```

### 6.7 Review Workflow

```
Document processed by model
        │
        ▼
Human reviewer sees:
  ┌─────────────────────────────────────────────────┐
  │ Document: Notice No. 602/2023                    │
  │                                                  │
  │ Predicted Variables:                             │
  │   [1] Reference Number: "602/2023"     ✓ ✗ ✎   │
  │   [2] Notice Date: "28/06/2023"        ✓ ✗ ✎   │
  │   [3] Accused Name: "Rajesh Kumar"     ✓ ✗ ✎   │
  │   [4] Court Fee: "Rs. 100"             ✓ ✗ ✎   │
  │                                                  │
  │ ✓ = correct  ✗ = hallucinated  ✎ = rename       │
  │                                                  │
  │ Missed variables? [Add new]                      │
  │   → Complainant PIN Code: "380006"               │
  │   → Cheque Number: "456789"                      │
  └─────────────────────────────────────────────────┘
        │
        ▼
Keyword tracker updated:
  - "Reference Number": +1 hit
  - "Notice Date": +1 hit
  - "Accused Name": +1 hit
  - "Court Fee": +1 hallucination (if reviewer marked ✗)
  - "Complainant PIN Code": +1 miss
  - "Cheque Number": +1 miss
```

---

## 7. Phase 6 — Evaluation & Metrics

### 7.1 Metrics Definition

| Metric | Formula | Target | What It Measures |
|--------|---------|--------|-----------------|
| **Precision** | correct / (correct + hallucinated) | > 0.90 | How many predicted variables are real |
| **Recall** | correct / (correct + missed) | > 0.95 | How many real variables were found |
| **F1 Score** | 2 * (P * R) / (P + R) | > 0.93 | Harmonic mean of precision and recall |
| **JSON Valid Rate** | valid_json / total_responses | > 0.99 | How often the model outputs parseable JSON |
| **Name Accuracy** | correct_names / total_correct | > 0.85 | How often variable names match conventions |
| **Latency** | avg response time per chunk | < 5s | Inference speed |

### 7.2 Evaluation Matching Logic

Two variables "match" if:
1. **Name match:** Fuzzy match on variableName (Levenshtein distance < 3, or same after lowercasing and removing spaces)
2. **Text match:** originalText overlaps with gold label (exact, case-insensitive, or whitespace-normalized — same tiers as your existing Rust code)

### 7.3 Test Set Guidelines

- Hold out 10% of your gold-labeled data as a test set
- **Never** include test set documents in training data
- Test set should cover all document types: notices, complaints, agreements, cheque bounce cases
- Include edge cases: tables, spaced digits, mixed Hindi-English, long documents
- Re-evaluate on the same test set after each training iteration for fair comparison

### 7.4 A/B Comparison

Run both models on the same test documents and compare:

```
┌──────────────────────────────┬─────────────┬──────────────────┐
│ Metric                       │ gpt-oss:120b│ legal-var-ext-3B │
├──────────────────────────────┼─────────────┼──────────────────┤
│ Precision                    │    0.87     │      0.92        │
│ Recall                       │    0.91     │      0.96        │
│ F1                           │    0.89     │      0.94        │
│ JSON Valid Rate              │    0.95     │      0.99        │
│ Avg Latency (per chunk)      │    8.2s     │      2.1s        │
│ Cost per document            │   $0.03     │     $0.001       │
└──────────────────────────────┴─────────────┴──────────────────┘
```

---

## 8. Cloud Infrastructure

### 8.1 Training (RunPod Recommended)

| Provider | GPU | VRAM | Cost/hr | Use Case |
|----------|-----|------|---------|----------|
| **RunPod** | RTX A5000 | 24 GB | ~$0.30 | QLoRA fine-tuning (recommended) |
| RunPod | RTX A6000 | 48 GB | ~$0.60 | Full fine-tuning or larger models |
| Lambda Labs | A100 40GB | 40 GB | ~$1.10 | Fast training, large batches |
| Google Colab Pro | T4/A100 | 16-40 GB | ~$10/mo | Experimentation |
| Vast.ai | Various | 24+ GB | ~$0.20+ | Cheapest, less reliable |

**Recommended setup:**
- RunPod on-demand with RTX A5000 (24GB)
- Select PyTorch 2.1 template
- SSH access for full control
- Persistent volume for checkpoints

### 8.2 Inference/Deployment (Your Existing Server)

Your Ubuntu VM running the Rust backend can also run Ollama. Requirements for 3B Q8_0:

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 8 GB | 16 GB |
| VRAM (if GPU) | 4 GB | 8 GB |
| CPU (if no GPU) | 4 cores | 8 cores |
| Disk | 5 GB | 10 GB |

If your server has no GPU, the 3B model still runs on CPU at acceptable speed (~5-15s per chunk with Q4_K_M quantization).

### 8.3 Training Pipeline on Cloud

```bash
# 1. Launch RunPod instance (RTX A5000, PyTorch template)
# 2. SSH into the instance

# 3. Setup environment
pip install unsloth transformers trl datasets peft bitsandbytes

# 4. Upload training data
scp training_data.jsonl runpod:/workspace/

# 5. Run training
cd /workspace
python fine_tune.py \
  --data training_data.jsonl \
  --base-model Qwen/Qwen2.5-3B-Instruct \
  --output ./legal-var-extractor-v1 \
  --epochs 3

# 6. Convert to GGUF
python convert_to_gguf.py ./legal-var-extractor-v1/merged

# 7. Download GGUF
scp runpod:/workspace/legal-var-extractor-q8_0.gguf ./

# 8. Deploy to your server
scp legal-var-extractor-q8_0.gguf your-server:/models/
ssh your-server "cd /models && ollama create legal-var-extractor -f Modelfile"

# 9. Stop RunPod instance (stop billing)
```

---

## 9. Framework Comparison

### 9.1 Fine-Tuning Frameworks

| Framework | Ease of Use | Speed | Features | Best For |
|-----------|------------|-------|----------|----------|
| **Unsloth** | Easy | 2-5x faster | QLoRA, auto-optimization | **Your primary choice** |
| HuggingFace TRL | Moderate | Baseline | SFT, DPO, RLHF, PPO | Advanced training techniques |
| Axolotl | Very Easy | Good | YAML config, many models | Quick experiments |
| torchtune | Moderate | Good | Native PyTorch, clean code | Learning/customization |
| LitGPT | Moderate | Good | Train from scratch + fine-tune | If training from scratch |

**Recommendation: Unsloth** — 2-5x faster than standard HuggingFace, less VRAM usage, and the API is almost identical to TRL. If you need DPO/RLHF later, switch to TRL.

### 9.2 Data Preparation Tools

| Tool | Purpose |
|------|---------|
| `datasets` (HuggingFace) | Load, split, shuffle, map training data |
| `pandas` | Tabular data manipulation for review tracking |
| `spacy` | Tokenization, optional NER baseline |
| `scikit-learn` | Evaluation metrics (precision, recall, F1) |

### 9.3 Deployment Tools

| Tool | Purpose |
|------|---------|
| **Ollama** | Local model serving (you already use this) |
| llama.cpp | GGUF conversion and CPU inference |
| vLLM | High-throughput GPU serving (if scaling up) |
| Text Generation Inference (TGI) | HuggingFace's production server |

---

## 10. Project Directory Structure

```
word-addin/
├── training/                          # NEW — All training pipeline code
│   ├── README.md                      # Quick start guide
│   ├── requirements.txt               # Python dependencies
│   │
│   ├── scripts/
│   │   ├── export_training_data.py    # Export labeled data from PostgreSQL
│   │   ├── generate_labels.py         # Generate labels using current LLM
│   │   ├── review_tool.py             # Interactive human review CLI
│   │   ├── prepare_dataset.py         # Validate, clean, split data
│   │   └── augment_data.py            # Augment based on keyword weights
│   │
│   ├── fine_tune.py                   # Main QLoRA training script
│   ├── train_from_scratch.py          # Optional: LitGPT from-scratch training
│   ├── keyword_tracker.py             # Keyword monitoring & ranking
│   ├── evaluate.py                    # Evaluation metrics & A/B comparison
│   ├── iterate.py                     # Full iteration cycle runner
│   ├── convert_to_gguf.py            # GGUF conversion wrapper
│   │
│   ├── data/
│   │   ├── raw/                       # Raw exported data (gitignored)
│   │   ├── gold/                      # Human-verified gold labels (gitignored)
│   │   ├── train.jsonl                # Training split (gitignored)
│   │   ├── eval.jsonl                 # Evaluation split (gitignored)
│   │   └── test.jsonl                 # Test split (gitignored)
│   │
│   ├── models/                        # Trained model checkpoints (gitignored)
│   │   ├── v1/
│   │   ├── v2/
│   │   └── ...
│   │
│   ├── reports/                       # Iteration reports
│   │   ├── iteration_1.json
│   │   ├── iteration_2.json
│   │   └── ...
│   │
│   └── deployment/
│       ├── Modelfile                  # Ollama model definition
│       └── deploy.sh                  # Script to convert + register with Ollama
│
├── backend/                           # Existing Rust backend (no changes needed)
├── word-extension/                    # Existing frontend (no changes needed)
└── LLM_TRAINING_PLAN.md             # This document
```

---

## 11. Cost Estimates

### 11.1 Per-Iteration Cost (Cloud Training)

| Step | GPU Time | Cost (RunPod A5000) |
|------|----------|-------------------|
| Fine-tune (3B, QLoRA, 3 epochs, 500 samples) | ~30 min | ~$0.15 |
| Convert to GGUF | ~5 min | ~$0.03 |
| Evaluation run on test set | ~20 min | ~$0.10 |
| **Total per iteration** | **~55 min** | **~$0.28** |

### 11.2 Full Project Cost Estimate

| Phase | Estimated Cost | Notes |
|-------|---------------|-------|
| Data preparation (tooling) | $0 | Local development |
| Human review time | ~10-20 hrs | Your time or a legal assistant |
| Initial training (iteration 1) | ~$0.30 | Single RunPod session |
| Iterations 2-5 | ~$1.20 | 4 more training rounds |
| Experimentation / debugging | ~$2.00 | Extra GPU time for troubleshooting |
| **Total cloud compute** | **~$3.50** | |

### 11.3 Ongoing Cost (Inference)

| Setup | Cost per Document | Monthly (100 docs/day) |
|-------|-------------------|----------------------|
| Current (gpt-oss:120b cloud) | ~$0.03 | ~$90 |
| Fine-tuned 3B on your server (GPU) | ~$0.001 | ~$3 (electricity) |
| Fine-tuned 3B on your server (CPU) | ~$0.001 | ~$3 (electricity) |
| Fine-tuned 3B on RunPod serverless | ~$0.0005 | ~$1.50 |

---

## 12. Risk Mitigation

### 12.1 Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Not enough training data | Medium | High | Start with silver labels from current LLM; use data augmentation; 100 gold samples is enough for QLoRA |
| JSON output breaks | Medium | High | Use Q8_0 quantization (not Q4); add JSON repair in Rust backend (already exists); constrained decoding via Ollama `response_format` |
| Model misses critical variables | High (initially) | Medium | Keyword tracking catches this; augment weak categories; recall-focused training |
| Model hallucinates variables | Medium | Low | Existing validation in Rust (originalText must exist in document) catches most hallucinations |
| GGUF conversion fails | Low | Medium | Test with llama.cpp before Ollama; Unsloth has built-in GGUF export |
| 3B model too slow on CPU | Medium | Medium | Use Q4_K_M quantization; reduce chunk size; or add a cheap GPU to your server |
| Overfitting on small dataset | Medium | Medium | LoRA dropout, early stopping, evaluation on held-out set |

### 12.2 Fallback Strategy

If the fine-tuned model doesn't reach acceptable quality:

1. **Keep current model as fallback** — your `.env` can switch between models
2. **Hybrid approach** — use fine-tuned model for common variables, fall back to large model for complex cases
3. **Ensemble** — run both models, merge results (union of variables, deduplicated)

---

## 13. Milestone Checklist

### Milestone 1: Data Pipeline (Week 1-2)

- [ ] Create `training/` directory structure
- [ ] Write `export_training_data.py` — export templates + variables from PostgreSQL
- [ ] Write `generate_labels.py` — generate silver labels from current LLM
- [ ] Write `review_tool.py` — interactive review CLI
- [ ] Write `prepare_dataset.py` — validate, clean, split
- [ ] Collect and review first 50 documents (gold labels)
- [ ] Verify JSONL format is correct

### Milestone 2: First Training Run (Week 2-3)

- [ ] Set up RunPod account and test GPU access
- [ ] Install dependencies (Unsloth, TRL, etc.)
- [ ] Write `fine_tune.py` with Qwen 2.5-3B base
- [ ] Train first model (iteration 0) on 50+ gold samples
- [ ] Write `evaluate.py` with precision/recall/F1 metrics
- [ ] Establish baseline metrics

### Milestone 3: Deployment (Week 3)

- [ ] Write `convert_to_gguf.py`
- [ ] Create `deployment/Modelfile`
- [ ] Convert model to GGUF Q8_0
- [ ] Register with Ollama on your server
- [ ] Test end-to-end: Word document -> Rust backend -> Ollama -> Variables
- [ ] Compare latency and accuracy vs current model

### Milestone 4: Keyword Tracking (Week 3-4)

- [ ] Write `keyword_tracker.py`
- [ ] Write `augment_data.py`
- [ ] Write `iterate.py` — full iteration cycle runner
- [ ] Run iteration 1: identify weak keywords
- [ ] Augment training data for weak keywords
- [ ] Re-train and measure improvement

### Milestone 5: Iterate to Target (Week 4-6)

- [ ] Run iterations 2-5 (or until F1 >= 0.93)
- [ ] Collect 50+ more documents if needed
- [ ] Generate per-iteration reports
- [ ] A/B comparison report: fine-tuned vs current model
- [ ] Decision: switch to fine-tuned model or continue iterating

### Milestone 6: Production (Week 6+)

- [ ] Update production `.env` to use fine-tuned model
- [ ] Monitor production accuracy for 1 week
- [ ] Set up periodic re-evaluation (monthly)
- [ ] Document the training process for future iterations
- [ ] Archive training artifacts and reports

---

## Quick Start

To begin immediately:

```bash
# 1. Create the training directory
mkdir -p training/{scripts,data/{raw,gold},models,reports,deployment}

# 2. Install Python dependencies
cd training
pip install unsloth transformers trl datasets peft bitsandbytes \
            scikit-learn pandas requests

# 3. Export your existing template data
python scripts/export_training_data.py

# 4. Review and correct labels
python scripts/review_tool.py --input data/raw/predicted.jsonl --output data/gold/verified.jsonl

# 5. Prepare dataset
python scripts/prepare_dataset.py --input data/gold/ --output data/

# 6. Fine-tune on cloud GPU
# (upload data to RunPod, run fine_tune.py)

# 7. Convert and deploy
python convert_to_gguf.py models/v1/merged
bash deployment/deploy.sh
```

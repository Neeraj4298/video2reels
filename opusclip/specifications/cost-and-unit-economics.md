# Cost & Unit Economics Evaluation

**Document Scope:** Feasibility analysis and estimated variable costs for processing a standard 1-hour video through the proposed Serverless MVP architecture.

---

## 1. Variable Cost Breakdown per 1-Hour Video

### 1.1 Ingestion & Audio Extraction
*   **Compute:** CPU-only serverless function (AWS Lambda / Modal CPU).
*   **Time:** ~60 seconds to download and run FFmpeg audio extraction.
*   **Cost Estimate:** **~$0.005**

### 1.2 Transcription & Diarization (Deepgram Nova-2)
*   **Service:** Deepgram API (Pay-as-you-go).
*   **Rate:** $0.0043 per minute of audio.
*   **Time:** 60 minutes.
*   **Cost Estimate:** 60 * 0.0043 = **$0.258**

### 1.3 LLM Curation & Scoring (Claude 3.5 Sonnet)
*   **Input Tokens:** 1 hour of speech $\approx$ 9,000 words $\approx$ 12,000 tokens.
*   **Output Tokens:** Generating 10 clips with hooks, summaries, and scores $\approx$ 2,500 tokens.
*   **Rates:** $3.00 / 1M Input, $15.00 / 1M Output.
*   **Cost Estimate:** (12k * $0.000003) + (2.5k * $0.000015) = $0.036 + $0.0375 = **~$0.074**

### 1.4 Face Tracking (Modal.com Serverless GPU)
*   **Compute:** Nvidia A10G (Modal pricing: ~$1.10 / hour).
*   **Load:** YOLOv8-face tracking the 10 selected clips (totaling ~10 minutes of video, sampled at 10 fps).
*   **Time:** ~2 minutes of GPU time.
*   **Cost Estimate:** (2 / 60) * 1.10 = **~$0.036**

### 1.5 Video Rendering (Remotion on AWS Lambda or Modal)
*   **Compute:** Rendering 10x 60-second clips at 1080p.
*   **Time:** Highly parallelized, ~3-4 minutes total compute time across workers.
*   **Cost Estimate:** **~$0.050**

### 1.6 Storage & Bandwidth
*   **Service:** Cloudflare R2.
*   **Egress Fees:** $0 (Massive advantage over AWS S3).
*   **Storage Cost:** Negligible for 30-day retention on a per-video basis.
*   **Cost Estimate:** **~$0.010**

---

## 2. Total Estimated Unit Cost

| Pipeline Stage | Estimated Cost (USD) |
| :--- | :--- |
| Ingestion & Audio | $0.005 |
| Deepgram ASR | $0.258 |
| Claude 3.5 LLM | $0.074 |
| GPU Face Tracking | $0.036 |
| Video Rendering | $0.050 |
| Storage | $0.010 |
| **Total Variable Cost** | **$0.433 per 1-Hour Video** |

---

## 3. Gross Margin Analysis

*   **Retail Pricing Target:** $15.00 / month for 150 processing minutes (2.5 hours).
*   **Revenue per Hour:** $6.00
*   **COGS per Hour:** $0.43
*   **Gross Margin:** **~92.8%**

**Conclusion:** The unit economics are highly favorable. By leveraging Deepgram and Serverless GPUs (Modal), we completely eliminate idle GPU costs. We can scale from 0 to 1,000 videos a day with near-linear variable costs and zero upfront hardware capital expenditure.

# Plan Restrictions & Credit System Architecture

**Document Scope:** Analysis of OpusClip's monetization model, credit consumption mechanics, and feature gating.

---

## 1. The Credit Economy

OpusClip operates on a compute-based credit system.
*   **Base Exchange Rate:** 1 Credit = 1 Minute of video processed.
*   **Rounding Rules:** 
    *   Videos < 1 minute are rounded UP to 1 credit.
    *   Videos > 1 minute with partial seconds are rounded DOWN (e.g., 4m 30s = 4 credits).
*   **Minimum Cost:** Processing any project requires a minimum balance of 10 credits.

### 1.1 Credit Types & Expirations
*   **Free Plan Credits:** 60 credits given once. Do NOT refresh monthly.
*   **Monthly Subscription Credits:** Expire after 60 days (they roll over for exactly one month).
*   **Annual Subscription Credits:** Expire after 12 months.
*   **Top-up (On-Demand) Credits:** Expire 12 months from purchase. *Crucial limitation: Top-up credits are frozen/locked if the user cancels their base subscription.*

### 1.2 Feature Surcharges
*   **X (Twitter) Publishing:** Deducts **3 credits** per clip, per account posted.
*   **AI Expand (Beta):** Dynamically priced based on the AI model chosen, target resolution, and clip length.
*   **Multi-angle Processing:** Charged per successfully rendered shot; refunds reserved credits if a technical failure occurs.

---

## 2. Feature Gating by Tier

### 2.1 Free Plan
*   **Price:** $0 (No credit card required).
*   **Credits:** 60 lifetime (no monthly refresh).
*   **Key Restrictions:** 
    *   Burned-in OpusClip watermark.
    *   Maximum 1080p resolution.
    *   No access to the timeline/text editor (must accept AI output as-is).
    *   0 Brand Templates.
    *   Storage retention: Clips expire and delete after **3 days**.
    *   Enhance Speech is disabled.

### 2.2 Starter Plan
*   **Price:** ~$15 / month.
*   **Credits:** 150 / month.
*   **Key Unlocks:** 
    *   Watermark removed.
    *   Full editor unlocked.
    *   1 Brand Template.
    *   Storage retention: **30 days**.
    *   AI B-Roll (Limited to Image and Stock video, no AI Video).

### 2.3 Pro Plan
*   **Price:** ~$29 / month (or $14.50/mo billed annually).
*   **Credits:** 300 / mo (3,600 / yr).
*   **Key Unlocks:**
    *   **Export to XML** (Premiere / DaVinci).
    *   **Full AI B-Roll** (includes generative AI Video).
    *   **Enhance Speech** (10 free uses per day).
    *   **Social Scheduler** fully unlocked.
    *   **Team Workspace:** 2 seats included (expandable up to 4).
    *   **Storage:** 100 GB fixed persistent storage.
    *   API Access (Beta).

### 2.4 Business / Enterprise Plan
*   **Key Unlocks:** Priority GPU processing queue, unlimited team seats, 4K rendering support, Single Sign-On (SSO), SOC II Type 2 compliance, custom font uploads, and unlimited storage.

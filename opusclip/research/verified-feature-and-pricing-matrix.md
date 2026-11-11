# Verified Feature & Pricing Matrix

**Document Scope:** Formal resolution of all observed pricing, credit, and capability contradictions across OpusClip marketing pages, Help Center articles, and API specifications.

---

## 1. Contradiction Resolution Log

### Contradiction 1: Free Plan Credit Allocation
*   **Conflicting Statements:**
    *   *Claim A (Marketing / Hero Copy):* "Free Plan: 60 credits every month."
    *   *Claim B (Help Center / Billing Documentation):* "The Free plan does not refresh its credits monthly. It provides a one-time allowance of 60 credits... Once spent, they are not replaced."
*   **Verified Official Evidence:** The official Help Center article on Free Plan credits (`help.opus.pro/billing/free-credits`) explicitly states that Free tier credits are a **one-time lifetime grant of 60 credits** (+ up to 25 onboarding bonus credits). They do NOT reset on a monthly cadence. To process more videos once 60 credits are consumed, users must subscribe to Starter or Pro.
*   **Final Verified Truth:** **60 Lifetime Credits (One-Time). No monthly refresh.**

---

### Contradiction 2: Brand Templates vs. Brand Kits Limit
*   **Conflicting Statements:**
    *   *Claim A:* Free has 0 templates; Starter has 1; Pro has 4.
    *   *Claim B:* Free has 1 template; Starter has 1; Pro has 2.
*   **Verified Official Evidence:** OpusClip maintains two distinct branding systems during an active product migration:
    1.  **Brand Templates (Classic Experience):** Used across mobile apps and API/MCP. Limits: Free = 1, Starter = 1, Pro = 2.
    2.  **Brand Kits (New Web Experience):** Desktop-first styling suite. Limits: Free = 0 custom (default kit only), Trial = 2, Starter = 1, Pro = Up to 4 (expandable via add-on packs).
*   **Final Verified Truth:** Both systems exist simultaneously; documentation variances reflect Classic (1 / 1 / 2) vs. New Brand Kit (0 / 1 / 4).

---

### Contradiction 3: Storage Limits & Video Retention
*   **Conflicting Statements:**
    *   *Claim A:* All plans have permanent video storage.
    *   *Claim B:* Free plans expire in 3 days; Starter in 30 days; Pro has 100 GB fixed.
*   **Verified Official Evidence:** Help Center documentation on project retention confirms strict data expiration policies:
    *   Free Tier: Projects and generated clips expire and are deleted **3 days** after generation.
    *   Starter Tier: Projects and clips expire after **30 days**.
    *   Pro Tier: Persistent **100 GB fixed storage** pool (no automatic time-based deletion).
    *   Business / Enterprise Tier: **Unlimited persistent storage**.
*   **Final Verified Truth:** Time-based expiration applies to Free (3 days) and Starter (30 days); quota-based storage applies to Pro (100 GB) and Business (Unlimited).

---

### Contradiction 4: AI B-Roll Availability by Subscription
*   **Conflicting Statements:**
    *   *Claim A:* AI B-roll is exclusive to the Pro plan.
    *   *Claim B:* Starter users can generate B-roll.
*   **Verified Official Evidence:** Help Center documentation differentiates between B-roll asset types:
    *   Free Plan: No B-roll access.
    *   Starter Plan: Supports **Stock Video** and **AI-Generated Static Images** only.
    *   Pro & Business Plans: Full generative **AI Video B-Roll** (using Hailuo 3 / Seedance 2.5) + Stock + AI Images.
*   **Final Verified Truth:** B-roll is tiered: Starter gets Stock/Images; Pro unlocks full generative AI Video.

---

### Contradiction 5: Enhance Speech Availability & Daily Limits
*   **Conflicting Statements:**
    *   *Claim A:* Enhance Speech costs minute credits like video clipping.
    *   *Claim B:* Enhance Speech is free and unlimited on Pro.
    *   *Claim C:* Enhance Speech is available on Starter.
*   **Verified Official Evidence:** Help Center documentation confirms:
    *   Free Plan: Disabled.
    *   Starter Plan: Disabled (restricted to "Pro plan and above").
    *   Pro & Business Plans: Included at **10 free uses per day**. It is governed by a daily invocation counter, NOT minute credits.
*   **Final Verified Truth:** Restricted to Pro and above; capped at **10 free uses per day**.

---

### Contradiction 6: Developer API Availability
*   **Conflicting Statements:**
    *   *Claim A:* API is available to all paid users (including Starter).
    *   *Claim B:* API requires an Enterprise contract.
*   **Verified Official Evidence:** The API Setup Guide states that calling programmatic endpoints requires an active **Pro (Beta), Max, or Business plan**. Starter tier accounts do not have access to API keys or MCP tool execution.
*   **Final Verified Truth:** Gated to **Pro (Beta), Max, and Business plans**.

---

### Contradiction 7: Social Publishing Platforms & Surcharges
*   **Conflicting Statements:**
    *   *Claim A:* Social scheduling is completely free across all connected accounts.
    *   *Claim B:* Social posting requires credits.
*   **Verified Official Evidence:**
    *   Starter Plan: Real-time "Post Now" only (YouTube, TikTok, Instagram). Future scheduling is disabled.
    *   Pro Plan: Future scheduling unlocked across 9 platforms (YouTube, TikTok, Instagram, Facebook Pages, LinkedIn, X, Pinterest, Threads, Bluesky).
    *   **Credit Surcharge:** Posting to **X (formerly Twitter)** consumes **3 credits per post, per account**. All other 8 platforms consume 0 additional credits.
*   **Final Verified Truth:** Posting is free on 8 platforms; X incurs a mandatory **3-credit fee per post**.

---

### Contradiction 8: AI Expand & Multi-Angle Availability
*   **Conflicting Statements:**
    *   *Claim A:* Included in base subscription credits.
    *   *Claim B:* Separate standalone subscription.
*   **Verified Official Evidence:** Both features reside in **Opus Labs** (experimental):
    *   **AI Expand (Beta):** Dynamically charges credits based on selected generative AI model, output resolution, source duration, and target aspect ratio.
    *   **Multi-Angle:** Consumes credits per successfully rendered shot (failed renders are refunded).
*   **Final Verified Truth:** Beta features available in Opus Labs drawing dynamically from the user's primary credit balance.

---

## 2. Definitive, Verified Feature-by-Tier Matrix

| Feature / Dimension | Free Plan | Starter Plan ($15/mo) | Pro Plan ($29/mo or $174/yr) | Business / Enterprise |
| :--- | :---: | :---: | :---: | :---: |
| **Price** | $0 | $15 / month | $29/mo ($14.50/mo billed annually) | Custom quote |
| **Credit Allocation** | **60 Lifetime (One-time)** | **150 / month** | **300 / mo (3,600 / yr)** | Custom quota |
| **Credit Rollover** | None (Spends once) | 60 days (1 mo rollover) | 60 days (Monthly) / 12 mos (Annual) | Custom SLA |
| **Watermark** | Yes (Burned-in) | No | No | No |
| **Maximum Resolution** | 1080p | 1080p | Highest Available (1080p / 2K) | **4K UHD** |
| **Storage Retention** | **3 days** | **30 days** | **100 GB Fixed (Persistent)** | **Unlimited** |
| **Web Editor Access** | No (Accept AI as-is) | Full Web Editor | Full Web Editor | Full Web Editor |
| **Classic Brand Templates**| 1 | 1 | 2 | Custom |
| **New Brand Kits** | 0 custom (Default only) | 1 | **Up to 4** | Unlimited / Custom |
| **AI B-Roll** | None | Stock & AI Images only | **Full (Generative AI Video)** | Full |
| **Enhance Speech** | No | No | **Yes (10 free uses/day)** | Yes (Higher/Unlimited) |
| **Export to XML (NLE)** | No | No | **Yes (Premiere & DaVinci)** | Yes |
| **Team Workspace Seats** | 1 (Personal only) | 1 | **2 Seats included (up to 4)** | Unlimited seats |
| **Social Publishing** | None | Real-time "Post Now" (YT/TT/IG)| **Full Scheduler (9 platforms)** | Full + Custom API |
| **X (Twitter) Surcharge** | N/A | 3 credits / post | 3 credits / post | 3 credits / post |
| **Developer API & MCP** | No | No | **Yes (Pro Beta)** | Full Production API |
| **AI Voiceover (TTS)** | Limited preview | Yes | Yes | Yes |
| **AI Video Dubbing** | No | Yes (Credit-based) | Yes (Credit-based) | Yes |
| **Opus Labs (Expand/Multi)**| No | Credit-based | Credit-based | Priority queue |
| **Support & Compliance** | Community | Standard | Priority email | Dedicated Slack, SSO, SOC 2 |

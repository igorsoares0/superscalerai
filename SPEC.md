# AI Image Enhancement SaaS
## Spec-Driven Development (SDD)

Version: 1.0
Status: MVP Specification

---

# Vision

Build a commercial AI-powered image enhancement platform capable of producing results comparable to products like Magnific AI through a modular enhancement pipeline rather than a single AI model.

The product should prioritize image quality over feature quantity.

The first release should already provide a sophisticated processing pipeline while maintaining a very simple user experience.

---

# Core Principles

- Image quality first.
- Pipeline-driven architecture.
- Every processing stage must be replaceable.
- AI models should be treated as plugins.
- Async processing.
- GPU-ready architecture.
- Self-host friendly.
- Commercial SaaS from day one.

---

# Tech Stack

## Backend

- FastAPI
- Python 3.13+
- SQLAlchemy 2
- Alembic
- Pydantic v2

## Database

Neon PostgreSQL (production; validated 2026-07-17 — all migrations run
clean, drift check empty, credit debit roundtrip ok). Dev and tests stay on
SQLite. `sqlalchemy_url()` in `app/database/session.py` pins the psycopg v3
driver onto Neon-style postgres:// URLs; `pool_pre_ping` covers Neon's
autosuspend. Use the DIRECT (non-pooler) connection string: Alembic needs
it, and at our volume it serves the app too.

## Queue

MVP: in-process background tasks (FastAPI BackgroundTasks) — no extra
infrastructure. The dispatch contract (`run_enhancement(job_id)` + job
status in the DB) is queue-agnostic.

Launch decision (2026-07-17): a real queue is NOT part of the launch block.
The two failure modes it would cover are handled in-process instead:
- restart kills in-flight jobs → startup sweep in `app/main.py` fails
  orphaned queued/running jobs and refunds their credits (idempotent);
- unbounded parallelism → `threading.BoundedSemaphore(max_concurrent_jobs)`
  in `app/workers/enhance.py` (default 4; Replicate 429s near 8 parallel
  predictions). Excess jobs wait on their threadpool thread, still "queued".

When multiple workers / retries / horizontal scale are needed: Redis + RQ,
swapped in at a single point (`app/jobs/queue.py`).

## Storage

S3-compatible storage — Cloudflare R2 in production (chosen 2026-07-17:
zero egress fees matter for a product that serves 20-30MB downloads; 10GB
free tier covers launch).

Implemented in `app/services/storage.py`: DB rows store KEYS
("uploads/x.png", "jobs/<id>/enhanced.png"), never paths. Backend chosen by
config: all four `r2_*` settings set → S3Storage (boto3, endpoint
`https://{account_id}.r2.cloudflarestorage.com`); otherwise LocalStorage
under `storage_dir` (dev default — dev never touches the network).
Downloads stream through the app (owner check stays; R2 egress is free).

## Frontend

- HTML
- TailwindCSS
- Vanilla JavaScript

---

# Project Structure

```
app/
    api/
    auth/
    core/
    database/
    jobs/
    pipeline/
    providers/
    services/
    workers/

templates/

static/

storage/

tests/
```

---

# Architecture

```
Browser

↓

FastAPI

↓

Job Queue

↓

Pipeline Engine

↓

Model Provider

↓

GPU

↓

Storage
```

---

# User Flow

```
Login

↓

Dashboard

↓

Upload Image

↓

Choose Preset

↓

Create Job

↓

Processing

↓

Compare

↓

Download
```

---

# MVP Features

## Authentication

- Register
- Login
- Logout
- Password Reset

---

## Dashboard

Displays

- Recent jobs
- Remaining credits
- Usage

---

## Upload

Supported formats

- JPG
- PNG
- WEBP

Maximum size configurable: `max_upload_mb` (default 25 MB) and
`max_image_px` (default 3072px on the longest edge, HTTP 413 above it).
The pixel cap exists because GPU cost grows ~quadratically with input size
(~$0.08 at 1792px 2x) while the credit price caps at 4 credits — huge
inputs would run at a loss and time out on the provider.

---

## Presets

Initial presets

- Portrait
- Product
- Architecture
- AI Generated

Presets determine which processing pipeline is executed.

Internally, a preset is a parameter bundle (base prompt fragment, denoise range, guidance weight, local enhancers) — see Pipeline Stages → Planner.

---

## Gallery

Each processed image stores

- Original
- Enhanced
- Thumbnail

---

## Compare

Interactive slider

Before / After

Zoom

Pan

Download

---

# Credits

Each enhancement consumes credits, by OUTPUT resolution (longest edge).
Tiers keep climbing because GPU cost grows ~quadratically with output size
(tier added 2026-07-17, user-approved).

| Output resolution | Credits |
|-------------------|---------|
| ≤1024px | 1 |
| ≤2048px | 2 |
| ≤4096px | 4 |
| >4096px | 8 |

---

# Pipeline Philosophy

The application is NOT based on a single AI model.

Instead:

```
Image

↓

Analyzer

↓

Captioner

↓

Planner

↓

Preprocessor

↓

Generative Upscaler

↓

Local Enhancers

↓

Post Processor

↓

Exporter
```

Every stage must be independent.

---

## Core Decision: The Generative Model IS the Upscaler

Resolution increase and detail synthesis happen in the same operation: a diffusion img2img pass guided by the structure of the original image (e.g. tile ControlNet, SUPIR-style restoration).

A deterministic upscaler (Real-ESRGAN or similar) exists only as:

- A pre-scale step to bring the image to the working resolution of the diffusion pass
- A cheap fallback when generative enhancement is disabled or fails

It is never the main quality path.

---

## Progressive Scaling

Maximum 2x of generative upscale per pass.

| Target | Passes |
|--------|--------|
| 2x | 1 |
| 4x | 2 |
| 8x | 3 (post-MVP; MVP caps at 4x) |

If the input is already at or above the target resolution, upscaling is skipped and the pipeline runs an enhance-only pass (img2img at 1x with low denoise).

---

## Tiling

No diffusion model natively processes 4096px.

Any generative pass above the model's native resolution MUST run tiled:

- Tiles at the model's native resolution
- Minimum 64px overlap between tiles
- Feathered blending on merge
- Same prompt and job seed across all tiles

Tiling may live inside the provider model (e.g. Clarity Upscaler handles it internally) or in the stage itself. The stage contract is: no visible seams in the output.

---

## Determinism

Every job has a seed.

- The seed and all resolved parameters are stored with the job
- Re-running with the same seed and parameters reproduces the same output
- "Regenerate" means: same parameters, new seed

---

# Pipeline Stages

---

## 1. Analyzer

Runs on the worker (CPU). No GPU calls.

Responsibilities

- Detect image resolution
- Detect image type
- Detect compression artifacts
- Detect blur
- Detect noise
- Detect faces (with bounding boxes)
- Detect text regions (with bounding boxes)
- Detect aspect ratio
- Extract metadata

Output

```
ImageContext
```

Example

```
Type: Portrait
Faces: 1 (bounding box)
Text regions: 0
Noise: Medium
Blur: Low
Compression: JPEG
Resolution: 1024x1024
```

The ImageContext exists to tune downstream parameters:

- Noise level → preprocessing denoise strength
- Faces detected → activates Face Enhancer + face protection masks
- Text detected → activates text protection masks
- Resolution vs target → number of generative passes, or enhance-only

---

## 2. Captioner

Generates the Internal Prompt used by the Generative Upscaler.

- Runs an image captioning model (e.g. Florence-2, BLIP-2, LLaVA)
- The caption is merged with the preset's base prompt fragment
- The user never writes prompts in the MVP

Without this stage the diffusion pass has nothing to guide it. This is how Magnific-style products steer enhancement without user prompts.

---

## 3. Planner

The user's preset ALWAYS selects the pipeline. The Analyzer never overrides the user's choice — it only tunes parameters within the chosen preset.

The Planner merges:

```
Preset (parameter bundle)

+

ImageContext (measured facts)

+

Job options (scale factor)

↓

ExecutionPlan
```

ExecutionPlan example

```
Passes: 2 (1024 → 2048 → 4096)
Denoise: 0.30
Guidance weight: 0.8
Prompt: <preset fragment> + <caption>
Seed: 831442
Local enhancers: FaceEnhancer
Protection masks: 1 face region
Post profile: portrait
```

### Presets Are Parameter Bundles

A preset is not a label — it is a concrete set of parameters:

| Preset | Denoise | Structural guidance | Local enhancers |
|--------------|-----------|---------------------|-----------------|
| Portrait | 0.20–0.35 | High | Face |
| Product | 0.20–0.30 | High | Text, Logo |
| Architecture | 0.30–0.40 | High | Text |
| AI Generated | 0.40–0.60 | Medium | — |

Denoise strength is the fidelity dial of the whole product: too low changes nothing, too high hallucinates (a portrait becomes a different person). Calibrating these ranges per preset is where the quality lives.

---

## 4. Preprocessor

Runs on the worker (CPU, OpenCV/PIL).

Responsibilities

- Orientation correction
- RGB conversion
- Noise reduction
- Color normalization
- Contrast normalization
- JPEG artifact removal
- Snapshot color/tone statistics of the ORIGINAL image (before any normalization), used later by the Post Processor's color match

Output

Clean image + color reference.

---

## 5. Generative Upscaler

The most important stage. Runs on a GPU provider.

One diffusion img2img pass per 2x step, guided by the original structure. Upscaling and detail synthesis are the same operation (see Core Decision above).

Responsibilities

- Increase resolution (max 2x per pass, progressive)
- Add realistic details
- Recover textures
- Improve lighting, materials and realism

Receives

- Image
- ExecutionPlan (prompt, seed, denoise, guidance weight, passes)
- Protection masks (face / text / logo regions where generation strength is reduced)

Constraints

- Above the model's native resolution, MUST run tiled (see Tiling above)
- Candidate models: Clarity Upscaler, SUPIR, ControlNet tile + SDXL
- Model implementation must be replaceable

The deterministic pre-scale (Real-ESRGAN or similar) is an internal detail of this stage, not a separate pipeline stage.

---

## 6. Local Enhancers

Corrective stages — not optional extras.

The generative pass is precisely what degrades small faces, text and logos. Local Enhancers exist to counter that, with two strategies:

1. Protect (text, logos) — after generation, composite the region back from a DETERMINISTIC upscale of the original (Real-ESRGAN), with a feathered mask. Validated: keeps text/logos pixel-faithful with no visible seam. Do NOT rely on provider-side generation masks: Clarity's `mask` parameter switches it to inpaint mode and disables upscaling entirely.
2. Repair via zoom-and-enhance (faces) — crop the face region, run the SAME generative upscaler on the crop alone (the face becomes a close-up, where the model is reliable: low creativity, accurate caption), then composite back supersampled with a feathered mask. Validated: identity preserved WITH real detail gain, ~8s GPU per face, no extra model and no extra license.

Face routing (by the Analyzer):

- Large face (close-up) → normal generative pass handles it well; no local enhancer
- Small face → zoom-and-enhance repair

Post-MVP: Text Recovery (OCR-guided), Logo Recovery, Material Recovery, optional specialist face model (license permitting).

Executed only when the ExecutionPlan activates them.

---

## 7. Post Processor

Runs on the worker (CPU).

Responsibilities

- Color match against the ORIGINAL image (wavelet color transfer or histogram matching) — corrects diffusion color drift; never a generic saturation adjustment
- Sharpen
- Contrast
- HDR adjustment
- Halo removal
- Seam inspection on tiled outputs
- Compression optimization

---

## 8. Exporter

Creates

- Final image
- Thumbnail
- Metadata (including seed and full ExecutionPlan, for reproducibility)

Stores everything in Storage.

---

# Execution Placement

| Stage | Runs on |
|---------------------|--------------|
| Analyzer | Worker (CPU) |
| Captioner | GPU provider |
| Planner | Worker |
| Preprocessor | Worker (CPU) |
| Generative Upscaler | GPU provider |
| Local Enhancers | GPU provider |
| Post Processor | Worker (CPU) |
| Exporter | Worker |

Rule: the image travels to a remote provider only for stages that need a GPU. CPU stages run on the worker to avoid an upload/download round-trip per stage.

---

# Internal Architecture

Each stage implements the same interface.

```python
class PipelineStage:

    async def process(self, image, context):
        ...
```

Pipeline

```python
Analyzer

↓

Captioner

↓

Planner

↓

Preprocessor

↓

GenerativeUpscaler

↓

LocalEnhancers

↓

PostProcessor

↓

Exporter
```

Each stage must be replaceable.

---

# Model Providers

The pipeline should never depend on a specific AI provider.

Instead

```
Provider

↓

Replicate

or

Runpod

or

Local GPU

or

Future Provider
```

Interface example

```python
class AIProvider:

    async def run(...)
```

The rest of the application never knows which provider executed the model.

---

## Initial Models (MVP)

Provider: Replicate.

| Stage | Model | License | Notes |
|---------------------|----------------------------------|-----------|----------------------------------------------|
| Generative Upscaler | `philz1337x/clarity-upscaler` | AGPL-3.0 | Commercial use OK. If the model code is MODIFIED and served, the modifications must be published (the SaaS itself is unaffected). Handles tiling and progressive scaling internally — the MVP stage delegates both to the model |
| Pre-scale / fallback| `nightmareai/real-esrgan` | BSD-3 | No restrictions |
| Captioner | `lucataco/florence-2-large` | MIT | No restrictions. Replaced BLIP-2 (2026-07-16): BLIP-2's brand/gender caption errors steered generation into changing the subject's gender — validated A/B, `validation/outputs/caption-compare.png` |
| Face Enhancer | `philz1337x/clarity-upscaler` (zoom-and-enhance) | AGPL-3.0 | Same model, run on the face crop alone — see Local Enhancers. No extra license needed |

Face Enhancer note: specialist face-restoration models are license-blocked for commercial use (CodeFormer is S-Lab 1.0 non-commercial; GFPGAN is Apache 2.0 but bundles non-commercial third-party components). The MVP instead repairs small faces with the zoom-and-enhance strategy using the generative upscaler itself — validated to preserve identity while adding real detail.

### Rules

- Only open-source / open-weight models in the critical path. All models above are Cog containers with public code — the same container runs on Replicate today and on Runpod Serverless later, with identical results. Proprietary models (Topaz, Recraft, Clarity AI hosted modes) may be used only as quality benchmarks during calibration, never as a dependency.
- "Code on GitHub" is not enough: verify that the license of BOTH code and weights allows commercial use before adopting any model. Research licenses (S-Lab, CC-NC, NVIDIA non-commercial) forbid it — e.g. CodeFormer and SUPIR are public code but non-commercial.
- Pin the model VERSION (version hash, not just `owner/name`) and record it in the ExecutionPlan. Unpinned models are updated upstream and silently break seed determinism and quality calibration.
- Track cost per image from day one (`jobs.execution_time` exists for this). The migration trigger is economic: move to dedicated GPUs when sustained volume keeps a GPU busy most of the day.

### Migration Path

```
Replicate (pay-per-run)

↓

Replicate Deployments (dedicated capacity, still zero ops)

↓

Runpod Serverless (same Cog containers, own infrastructure)

↓

Local GPU cluster (future)
```

---

# Jobs

Image enhancement is asynchronous.

Lifecycle

```
Pending

↓

Queued

↓

Running

↓

Completed

↓

Failed
```

---

# Database

## users

- id
- email
- password_hash
- credits
- created_at

---

## images

- id
- user_id
- original_path
- enhanced_path
- thumb_path
- width
- height

---

## jobs

- id
- user_id
- image_id
- preset
- seed
- params (resolved ExecutionPlan, JSON)
- status
- provider
- execution_time
- created_at

---

## payments

- id
- user_id
- credits
- amount
- provider
- created_at

---

# API

Authentication

```
POST /auth/register

POST /auth/login

POST /auth/logout
```

Images

```
POST /images/upload

GET /images

GET /images/{id}

DELETE /images/{id}
```

Jobs

```
POST /jobs

GET /jobs

GET /jobs/{id}
```

Downloads

```
GET /download/{id}
```

Payments

Provider: Paddle (Merchant of Record — handles global sales tax/VAT and
invoicing, which matters for selling internationally from day one).

```
POST /payments/webhook
```

Webhook must verify Paddle's signature and be idempotent (webhooks arrive
duplicated in practice).

---

# Frontend Pages

```
/

Login

Register

Dashboard

Upload

Gallery

Job Details

Billing

Settings
```

---

# Quality Roadmap

The current pipeline is the floor, not the ceiling. Improvement levers, in order of impact:

1. Preset calibration — build a golden set (10–20 images per category), fix the seed and sweep parameters systematically (creativity, resemblance, dynamic/HDR, steps, tile size). Calibration is most of the quality gap to Magnific-class products. STARTED 2026-07-16: harness in `validation/calibrate.py` (SFace identity + downscaled PSNR + Laplacian detail, resumable sweep); portrait calibrated on a 3-image people set — identity falls off a cliff above creativity 0.20 (SFace 0.8→0.5 at 0.28) while detail barely grows, so portrait moved to creativity 0.20 / resemblance 1.2. Still open: golden sets for product/architecture/ai-generated, HDR/steps sweep, zoom-and-enhance re-validation with the harness.
2. ~~Better captioner~~ DONE 2026-07-16 — Florence-2 replaced BLIP-2 ("Detailed Caption" level; "More Detailed" overflows SD 1.5's encoder). Still open: region-level captions (face, background) to guide each area with the right prompt; Florence-2's OCR/detection tasks could also replace the Analyzer's text heuristic.
3. Identity quality gate — compare face embeddings (ArcFace) before/after; if similarity drops below threshold, auto-retry with lower creativity. Turns identity preservation into a measurable guarantee.
4. Real post-processing — wavelet color match, grain matching for protected regions (deterministic patches read softer than enhanced surroundings), calibrated sharpening.
5. Prompt + LoRA bundles per preset — Clarity accepts `lora_links` and `custom_sd_model`; skin-texture LoRAs for Portrait, material LoRAs for Product.
6. Engine swap — Clarity is SD 1.5-based. When a commercially viable SDXL/FLUX-class upscaler matures, the provider abstraction makes it a swap, not a rewrite.
7. Evaluation harness (the meta-lever) — automated golden-set scoring: identity similarity, OCR legibility of text regions, no-reference IQA. Every tweak becomes a number instead of an opinion; no regressions.

---

# Future Features

- Batch processing
- API access
- Teams
- Shared workspaces
- Custom presets
- Prompt editor
- Creativity slider
- Detail slider
- Resemblance slider
- HDR slider
- Face-only enhancement
- Background enhancement
- OCR restoration
- Watermark removal (where legally appropriate)
- Multiple AI providers
- Local GPU cluster
- Image version history

---

# Non-Functional Requirements

- Async-first architecture
- Pipeline stages must be stateless
- Replaceable AI providers
- Horizontal worker scaling
- Database migrations via Alembic
- Type-safe Python code
- Comprehensive logging
- Retry failed jobs
- Secure file uploads
- Responsive UI
- Mobile-friendly dashboard

---

# Success Criteria (MVP)

A user should be able to:

1. Register.
2. Purchase credits.
3. Upload an image.
4. Select a preset.
5. Start enhancement.
6. Monitor processing.
7. Compare before/after.
8. Download the enhanced image.

The sophistication of the product should come from the quality and modularity of the processing pipeline—not from exposing many controls in the user interface.
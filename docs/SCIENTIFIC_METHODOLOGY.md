# CheiloScan — Scientific Methodology

**Status:** Phase 0 scientific methodology; current implementation notes added 2026-11-24
**Date:** 2026-11-11

---

## 1. Domain background

**Cheiloscopy** is the study of the grooves and ridges ("lip prints") visible on
the human lip, typically made visible by lipstick or other transfer media, or
photographed directly. The most widely cited descriptive classification is the
Suzuki–Tsuchihashi typology, which categorizes groove patterns as:

| Type | Description |
|---|---|
| I | Longitudinal (vertical) grooves, running roughly top-to-bottom |
| I′ | Longitudinal grooves with bifurcations (branched) |
| II | Branched grooves (bifurcating) |
| III | Intersecting / criss-crossed grooves |
| IV | Reticular (net-like) pattern |
| V | Irregular / undetermined |

It has been proposed — and debated — as a supplementary forensic identification
method, and lip-print features have been used in some casework contexts.
**However, cheiloscopy is not a validated biometric identification system.**
There is no large, independently verified reference population establishing
individuality with known error rates, and the method is not generally accepted
as stand-alone identification evidence in court.

CheiloScan therefore treats lip prints as **image texture measurement targets**,
not as identity tokens.

## 2. Positioning and claim policy (binding on all outputs)

1. CheiloScan outputs are **descriptive measurements** of images: numeric feature
   values and similarity scores between pairs of images.
2. CheiloScan **does not** produce identification conclusions, probability of
   match, likelihood ratios, or "same-source" verdicts.
3. No threshold converts a similarity score into a decision. Scores are shown
   with their components and method versions only.
4. Any accuracy statement (e.g., distributions of genuine vs. impostor scores)
   requires a real, documented dataset collected under a documented protocol.
   Until such a dataset exists under the researcher's control, **no error-rate
   statistics will be computed or reported**. Synthetic fixtures are used for
   software correctness testing only and are never treated as evidence about
   real-world accuracy.
5. Every generated report carries a fixed disclaimer block stating the
   experimental status of the tool and the absence of validation data.

These rules are enforced by design: the fusion layer has no thresholding
code path, and the report renderer injects the disclaimer unconditionally.

## 3. Acquisition metadata (recorded, not assumed)

Because print variability depends heavily on how the image was produced, every
sample records:

- `capture_type` (`print_document` | `photograph`)
- `medium` (e.g., lipstick type/paper, scanner bed)
- `collection_method` (free-text protocol note: pressure, technique)
- `donor_ref` (anonymized researcher-controlled label; no PII)
- `consent_confirmed` (boolean; recorded when supplied. Implementation note:
  v0.1 does not block analysis on this field — the operator must enforce the
  institutional consent policy before ingesting real samples.)

These fields are metadata for interpretation and later research stratification —
they are not used to alter computed features. The pipeline does **not** attempt to
compensate for unknown acquisition differences (that would require calibration
data we do not have); differences are simply measured.

## 4. Processing stages

### 4.1 Intake validation (gatekeeping, not scoring)

Deterministic, parameterized checks; results stored with the asset:

| Check | Method | Behavior |
|---|---|---|
| Format/decodability | content-sniff + full decode (OpenCV/Pillow) | Hard reject on failure |
| Size/resolution floors | byte size, pixel dimensions | Hard reject below floor |
| Blur | Variance of Laplacian on grayscale | Warning below configurable threshold |
| Luminance/contrast | mean/std of grayscale histogram percentiles | Warnings outside sane bands |

Validation thresholds are **configuration values, not universal constants** —
they will be tuned to the researcher's actual capture setup and re-tuned only
with documented justification (a threshold change is recorded per run via the
parameter snapshot).

### 4.2 Preprocessing

1. Grayscale conversion (luminance-preserving weights).
2. Optional gentle denoising: bilateral filter (edge-preserving) — parameterized,
   default conservative.
3. CLAHE (contrast-limited adaptive histogram equalization) for local contrast
   normalization; clip limit and tile grid recorded as parameters.
4. Resolution normalization to a standard working DPI/pixel scale for the ROI
   stage (documented per run), because spatial-frequency features are
   scale-sensitive.

### 4.3 Region of interest (ROI) detection

Two strategies by `capture_type`:

- **Print on document:** Otsu thresholding → morphological opening/closing →
  largest connected component → bounding box + convexity/aspect metrics as
  confidence proxies.
- **Photograph of lips:** color-space segmentation (HSV/lab skin/lip hue
  ranges) + contour analysis. This is research-grade and expected to be
  unreliable under varying lighting; therefore a **manual ROI specification
  path is mandatory** (user-drawn bbox persisted as a derived asset and recorded
  as a pipeline parameter override).

Detected ROIs always store a confidence value and the mask image as derived
assets. A low-confidence ROI is flagged in outputs, never silently accepted.

### 4.4 Groove-pattern enhancement

Lip grooves are quasi-linear, anisotropic structures. Enhancement aims to
suppress background and accentuate groove lines so that directional features
are measurable:

- **Gabor filter bank** tuned over a set of orientations and spatial
  frequencies (parameters: kernel size, θ set, λ set, bandwidth, aspect ratio);
  response aggregated by max/energy.
- **Ridge filters** (scikit-image: Sato, Frangi) — tubular-structure enhancers
  as an alternative stage (selected per pipeline version, recorded).
- **Adaptive thresholding** of the enhanced response to obtain a binary groove
  map where appropriate; **skeletonization** for topological analysis.

Enhancement quality is validated only *mechanically* (see §7): on synthetic
ridge patterns with known orientation/frequency, the post-enhancement
orientation estimate must recover the ground truth within tolerance. This
validates the implementation, **not** performance on real lip prints.

### 4.5 Feature extraction (versioned families)

All features computed on the standardized ROI (enhanced image unless stated).
Each family has an independent `feature_version`; definitions:

| Family | Metrics | Basis |
|---|---|---|
| Orientation | Orientation histogram (weighted by gradient magnitude); mean resultant length (coherence); dominant orientation(s) | Structure tensor over Gaussian-smoothed gradients |
| Ridge frequency | Mean groove spatial frequency (cycles/pixel, and cycles/mm if scale known); frequency dispersion | Radial FFT power spectrum and/or autocorrelation of the binary groove map |
| GLCM texture | Contrast, correlation, energy, homogeneity, entropy at configured distances/angles | scikit-image `graycomatrix`/`graycoprops` on quantized grayscale ROI |
| LBP | Rotation-invariant uniform LBP histogram (selected bins + histogram statistics) | scikit-image `local_binary_pattern` |
| Skeleton topology | Groove density (skeleton pixels/area), node count, branch count, mean segment length, segment-length distribution stats | Skeleton graph analysis (sknw-style or custom adjacency on the skeleton) |

Normalization policy: every stored feature records its units and normalization
(scale-normalized where spatial scale is known; raw otherwise). Feature vectors
are never silently rescaled inside the comparison layer without the
normalization being recorded in the feature document.

## 5. Comparison methodology

For a pair of runs (A, B) on standardized ROIs:

1. **Registration (alignment quality permitting):** phase correlation for
   translation; ECC refinement on the enhanced ROI. Registration confidence
   is stored; on failure, image-based scores are marked `not_computable` while
   feature-based scores remain available.
2. **Component scores (each stored separately):**
   - Feature-space: cosine similarity and standardized Euclidean distance per
     feature family (standardization parameters derived from *the pair being
     compared only*, and recorded — no population statistics are assumed).
   - Image-space: normalized cross-correlation and structural similarity
     (SSIM) of the aligned enhanced ROIs.
3. **Fusion (`heuristic_fusion_v1`):** fixed weighted sum of normalized
   component scores. Weights are **code constants, documented in the report,
   and chosen a priori** (no fitting to any data). The fused score is labeled
   heuristic in every output. It exists to give a single summary number for
   browsing comparisons, not as an inference.

**Interpretation policy:** higher similarity = more similar measurements. Not
"more likely same person." The UI and reports repeat this. There is no
threshold, no FAR/FRR, no ROC — those require data CheiloScan does not have.

**If the researcher later supplies a real dataset:** permissible analyses are
descriptive statistics of score distributions (genuine vs. non-genuine pairs if
labeled by the researcher's protocol), with explicit sample-size caveats.
Supervised classification (scikit-learn) would additionally require a
pre-registered train/test protocol and honest cross-validation — out of scope
until such data exists; never trained on synthetic fixtures.

## 6. Known scientific limitations (must be acknowledged in reports)

1. **Individuality unproven at population scale.** No validated reference
   population exists for lip-print individuality with known error rates.
2. **Intra-individual variability.** Lip prints vary with pressure, medium,
   hydration, pathology, trauma, and age; repeatability of the *biological*
   pattern is itself a research question.
3. **Acquisition dominance.** Differences between two images may reflect
   capture conditions (medium, lighting, resolution) rather than the underlying
   pattern. CheiloScan measures images, not lips.
4. **Segmentation error propagation.** ROI errors propagate to every
   downstream feature; hence confidence flags and the manual override.
5. **Feature sensitivity.** GLCM/LBP/frequency features respond to scale,
   contrast, and noise in ways that are not lip-specific; interpretation
   requires the recorded provenance.
6. **No calibration population.** Scores cannot be converted to likelihoods.
7. **Multiple-comparison bias.** Browsing many pair scores invites
   post-hoc selection of extreme values; reports list the full comparison
   history to make selection visible.
8. **Small-sample bias in any future validation.** With few samples,
   error-rate estimates are unstable; any future statistics must carry
   confidence intervals and sample-size disclosure.

## 7. Software validation without fabricated data

The pipeline's *implementation correctness* (not forensic accuracy) is
validated as follows:

- **Synthetic fixtures, clearly labeled:** procedurally generated images
  (drawn ridge patterns at known angles, spacings, noise levels) used only
  inside `tests/` to assert that algorithms recover known ground truth within
  tolerances (e.g., orientation ±5°, frequency ±10%).
- **Determinism tests:** identical input + parameters → byte-identical feature
  JSON (golden files), verifying reproducibility of the tool itself.
- **Integrity tests:** original asset hashes unchanged after full pipeline runs.
- **If the researcher collects real samples** under their own protocol,
  CheiloScan supports *self-consistency* studies (same print photographed
  twice → tool-measured similarity) as descriptive measurements of the
  *system's* behavior on that data — reported with all caveats above, and
  never extrapolated beyond the collected sample.

## 8. Report content requirements (checked by tests)

Every PDF report must contain:

1. Identification of both runs (IDs, pipeline names/versions, parameter
   snapshots, asset hashes).
2. All component scores with method versions, plus registration confidence.
3. The heuristic-fused score, explicitly labeled heuristic.
4. Acquisition metadata for both samples.
5. The methodology summary (this document's key points, condensed).
6. The limitations block (§6, condensed).
7. The fixed disclaimer: *"CheiloScan is an experimental research tool.
   Its outputs are descriptive image measurements and do not constitute
   biometric identification or forensic conclusions."*

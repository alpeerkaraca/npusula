# Legacy artifacts (pre base-potential / time-lift rework)

These files are kept for provenance and for the "same split protocol" comparison in
`artifacts/final_evaluation.json` (`legacy_comparison`). **Nothing in the runtime
loads them.** They were produced before the two-layer rework described in
`ENPUSULA_MODEL_VE_SAAT_ONERISI_DUZELTME_PLANI.md`.

| File | What it was | Why it is legacy |
|---|---|---|
| `lgbm_popularity.txt` | LightGBM booster, 36-feature contract (`M5`) | Feature vector mixed time-of-day features (`hour`, `weekday`, `month`, `hour_sin/cos`, `weekday_sin/cos`, `cat_x_hour`, `cat_x_weekday`, `history_x_hour`) with content features, and fed `account_baseline` in as an input *and* used it as the residual offset. Time is now a separate layer (Layer B). |
| `metrics.json` | Test metrics for `M5` (MAE≈0.853, Spearman≈0.870) | The same test split had already been inspected during tuning, so it was no longer a locked evaluation. Also, MAE/Spearman measure **post popularity**, not time-slot quality. |
| `tuning_results.json` | Random search ranked by **test** MAE | Model selection read the test split. Tuning now ranks by validation pinball loss only (`scripts/tune_lgbm.py`) and the test split is read once by `scripts/evaluate_final.py`. |
| `pytorch_popularity_gpu.pt` | Early PyTorch tabular-NN experiment | Never loaded by the runtime (`backend/services/recommendation.py` serves LightGBM only). Removed from the runtime story per plan §6.3. |

Old numbers must not be quoted as time-recommendation quality. See
`artifacts/final_evaluation.json` → `metric_interpretation` for the wording that is
allowed for each metric.

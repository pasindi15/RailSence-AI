Evaluation artifacts are maintained alongside each completed phase.

- `ml/delay_model_metrics.json` contains held-out MAE, RMSE, and R².
- `nlp/classification_metrics.json` contains classification precision, recall,
	and F1 against generated ground-truth labels.
- `rag/retrieval_metrics.json` contains P@1, P@3, and P@5 using same-category
	agreement as an explicit relevance proxy.
- `rag/paraphrased_query_robustness.json` contains the six-query stress test
	for phrasing outside the generated templates.

Regenerate the Phase 4 evidence with:

```powershell
python M2-operations-agent/evaluation/rag/evaluate_retrieval.py
```

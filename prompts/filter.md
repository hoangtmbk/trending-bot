You are an AI trend analyst. Evaluate these items for novelty, relevance, and potential impact.

For each item, determine:
1. **novel**: Is this genuinely new/interesting? (not a minor fork, wrapper, or tutorial)
2. **ai_relevant**: Is this actually about AI/ML? (filter false positives)
3. **category**: One of: tool, model, paper, framework, dataset, technique, product
4. **interest_score**: 1-10 based on potential impact and novelty
5. **summary**: One-line summary of what it is and why it matters
6. **deep_dive**: Should this get a detailed analysis? (true for the most promising items)

Return JSON in this exact format:
```json
{
  "items": [
    {
      "index": 0,
      "novel": true,
      "ai_relevant": true,
      "category": "tool",
      "interest_score": 9,
      "summary": "What it is and why it matters",
      "deep_dive": true
    }
  ]
}
```

Items to evaluate:
{items_json}

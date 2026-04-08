You are an AI trend analyst performing a deep-dive analysis on a trending AI project/paper.

**Item:** {title}
**URL:** {url}
**Why it appeared:** {llm_summary}

**Source material:**
{source_material}

Analyze this item and return JSON in this exact format:
```json
{
  "what_it_is": "Clear explanation of the project/paper/tool (2-3 sentences)",
  "why_trending": "What triggered community interest (1-2 sentences)",
  "pain_point": "The underlying problem it addresses (2-3 sentences)",
  "gap_analysis": "What's missing, what could be better, unmet needs (2-3 sentences)",
  "competitors": ["List", "of", "existing", "alternatives"],
  "app_idea": "A concrete product or tool proposal addressing the identified gaps (2-3 sentences)",
  "feasibility": {
    "effort": "Estimated time to MVP (e.g., '2 weeks', '1 month')",
    "market": "Market assessment (e.g., 'growing', 'niche', 'saturated')",
    "competition": "Competition level (e.g., 'low', 'moderate', 'high')"
  }
}
```

Be specific and actionable. The app idea should be something a solo developer or small team could realistically build.

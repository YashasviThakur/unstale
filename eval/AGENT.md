# Agent eval: a support agent answering customers

| Context | Correct | Confidently outdated answers | Prompt tokens per answer |
|---|---|---|---|
| Agent's own knowledge base | 29% (9/31) | 10 | 429 |
| **Own knowledge base + Unstale corrections** | 94% (29/31) | 0 | 545 |
| Every message in the org | 90% (28/31) | 2 | 3,156 |
| Vector RAG over every message (top 8) | 97% (30/31) | 0 | 544 |

# ContextForge benchmark results

Dataset `2026.10` (12 synthetic cases), tokenizer `o200k_base`, 5 timed runs per case. Regenerate with `make benchmark`.

Every case has a token budget well below its original size. Fact retention is strict (the gold fact must appear verbatim). Reader accuracy uses a **simulated** deterministic extractive reader, not a language model.

## Summary

| Method | Tokens before | Tokens after | Reduction | Budget met | Fact retention | Citation retention | Reader accuracy (simulated) | Latency p50 | Latency p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| contextforge-balanced | 147,626 | 14,388 | 90.2% | 12/12 | 100.0% | 100.0% | 100.0% | 20.0 ms | 85.1 ms |
| contextforge-aggressive | 147,626 | 13,185 | 91.1% | 12/12 | 100.0% | 100.0% | 100.0% | 17.0 ms | 80.7 ms |
| truncate-oldest | 147,626 | 19,650 | 86.7% | 12/12 | 52.8% | 75.0% | 33.3% | 0.0 ms | 0.0 ms |
| no-optimization | 147,626 | 147,626 | 0.0% | 0/12 | 100.0% | 100.0% | 94.5% | 0.0 ms | 0.0 ms |

## Per case

| Case | Workload | Method | Before | After | Budget | Met | Facts | Citations | Reader | p50 | Missing facts |
| --- | --- | --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | --- |
| coding-11 | coding | contextforge-balanced | 11,269 | 2,685 | 3,000 | yes | 100% | 100% | 100% | 24.3 ms | none |
| coding-11 | coding | contextforge-aggressive | 11,269 | 1,920 | 3,000 | yes | 100% | 100% | 100% | 23.4 ms | none |
| coding-11 | coding | truncate-oldest | 11,269 | 1,773 | 3,000 | yes | 67% | 100% | 33% | 0.0 ms | ENG-8629, v2.5.8 |
| coding-12 | coding | contextforge-balanced | 30,015 | 2,338 | 4,000 | yes | 100% | 100% | 100% | 45.4 ms | none |
| coding-12 | coding | contextforge-aggressive | 30,015 | 2,346 | 4,000 | yes | 100% | 100% | 100% | 45.5 ms | none |
| coding-12 | coding | truncate-oldest | 30,015 | 3,601 | 4,000 | yes | 67% | 100% | 33% | 0.0 ms | ENG-9669, v2.12.0 |
| coding-13 | coding | contextforge-balanced | 58,881 | 2,951 | 6,000 | yes | 100% | 100% | 100% | 81.5 ms | none |
| coding-13 | coding | contextforge-aggressive | 58,881 | 2,959 | 6,000 | yes | 100% | 100% | 100% | 79.5 ms | none |
| coding-13 | coding | truncate-oldest | 58,881 | 5,644 | 6,000 | yes | 67% | 100% | 33% | 0.0 ms | ENG-4042, v2.7.2 |
| support-21 | support | contextforge-balanced | 1,671 | 777 | 900 | yes | 100% | 100% | 100% | 9.2 ms | none |
| support-21 | support | contextforge-aggressive | 1,671 | 812 | 900 | yes | 100% | 100% | 100% | 7.3 ms | none |
| support-21 | support | truncate-oldest | 1,671 | 873 | 900 | yes | 33% | 100% | 0% | 0.0 ms | ACC-31620, 119, $79, finance-71@northwind.example |
| support-22 | support | contextforge-balanced | 3,561 | 1,005 | 1,200 | yes | 100% | 100% | 100% | 17.2 ms | none |
| support-22 | support | contextforge-aggressive | 3,561 | 795 | 1,200 | yes | 100% | 100% | 100% | 13.6 ms | none |
| support-22 | support | truncate-oldest | 3,561 | 1,164 | 1,200 | yes | 33% | 100% | 0% | 0.0 ms | ACC-28398, 74, $19, finance-33@northwind.example |
| support-23 | support | contextforge-balanced | 6,149 | 1,210 | 1,500 | yes | 100% | 100% | 100% | 26.2 ms | none |
| support-23 | support | contextforge-aggressive | 6,149 | 931 | 1,500 | yes | 100% | 100% | 100% | 22.1 ms | none |
| support-23 | support | truncate-oldest | 6,149 | 1,498 | 1,500 | yes | 33% | 100% | 0% | 0.0 ms | ACC-47999, 33, $19, finance-49@northwind.example |
| rag-31 | rag | contextforge-balanced | 1,577 | 181 | 900 | yes | 100% | 100% | 100% | 4.0 ms | none |
| rag-31 | rag | contextforge-aggressive | 1,577 | 181 | 900 | yes | 100% | 100% | 100% | 3.7 ms | none |
| rag-31 | rag | truncate-oldest | 1,577 | 865 | 900 | yes | 67% | 67% | 67% | 0.0 ms | 90 days |
| rag-32 | rag | contextforge-balanced | 3,207 | 182 | 1,200 | yes | 100% | 100% | 100% | 9.5 ms | none |
| rag-32 | rag | contextforge-aggressive | 3,207 | 182 | 1,200 | yes | 100% | 100% | 100% | 9.1 ms | none |
| rag-32 | rag | truncate-oldest | 3,207 | 1,194 | 1,200 | yes | 100% | 0% | 100% | 0.0 ms | none |
| rag-33 | rag | contextforge-balanced | 5,997 | 180 | 1,500 | yes | 100% | 100% | 100% | 22.8 ms | none |
| rag-33 | rag | contextforge-aggressive | 5,997 | 180 | 1,500 | yes | 100% | 100% | 100% | 20.5 ms | none |
| rag-33 | rag | truncate-oldest | 5,997 | 1,459 | 1,500 | yes | 67% | 33% | 33% | 0.0 ms | 600 requests per minute |
| research-41 | research | contextforge-balanced | 1,029 | 123 | 700 | yes | 100% | 100% | 100% | 2.8 ms | none |
| research-41 | research | contextforge-aggressive | 1,029 | 123 | 700 | yes | 100% | 100% | 100% | 2.8 ms | none |
| research-41 | research | truncate-oldest | 1,029 | 679 | 700 | yes | 50% | 50% | 50% | 0.0 ms | 42% more pull requests |
| research-42 | research | contextforge-balanced | 1,944 | 123 | 900 | yes | 100% | 100% | 100% | 5.3 ms | none |
| research-42 | research | contextforge-aggressive | 1,944 | 123 | 900 | yes | 100% | 100% | 100% | 4.7 ms | none |
| research-42 | research | truncate-oldest | 1,944 | 855 | 900 | yes | 50% | 50% | 50% | 0.0 ms | 25% more pull requests |
| agent-51 | agent | contextforge-balanced | 22,326 | 2,633 | 4,000 | yes | 100% | 100% | 100% | 84.5 ms | none |
| agent-51 | agent | contextforge-aggressive | 22,326 | 2,633 | 4,000 | yes | 100% | 100% | 100% | 41.5 ms | none |
| agent-51 | agent | truncate-oldest | 22,326 | 45 | 4,000 | yes | 0% | 100% | 0% | 0.0 ms | SKU-355346, Austin, $5,000, approved suppliers |

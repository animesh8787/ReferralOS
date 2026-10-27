# Performance (measured, one machine: 12 cores, 15.7 GB, synthetic data)
Per user: 11,000 LinkedIn + 5,000 HR rows, 500 jobs. Real API process plus a separate worker. Raw data: PERF_sqlite.json, PERF_postgres.json.

| | SQLite, 1 user | PostgreSQL 16, 3 concurrent users |
|---|---|---|
| LinkedIn import (11k rows) | 4.9 s | 8.5-22.9 s |
| HR import (5k rows) | 4.4 s | 14.8-20.7 s |
| Scoring 11k contacts | 5.1 s | 22-24 s |
| Prospects page p50/p95 | 351/370 ms | 109/126 ms |
| Opportunities page p50/p95 | 136/157 ms | 227/298 ms |
| Dashboard p50/p95 | 178/199 ms | 75/114 ms |
| Full JSON export | 12.7 s (56 MB) | 11.1 s (47 MB) |
| Peak memory (API+worker) | 740 MB | 635 MB |

No task failed; tenant isolation held.

## Limits
SQLite is single-user. In 3-user SQLite runs requests hit "database is locked" while the worker held a long write, and scoring sometimes produced no prospects. WAL and a 30 s busy timeout are on; use PostgreSQL for more than one active user. Those failed runs are not in the table. Larger inputs were not measured.

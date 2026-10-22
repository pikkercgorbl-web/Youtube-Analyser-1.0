# Fix 3C — Discovery queue policy

## Почему seed/active ждали до ~39h

Selector (до 3C): один пул due-ключей, сортировка **только по просрочке** (`now - next_scan_at`), затем tie-break source/lifecycle.

- Policy: probation **6h**, active **24h**, weak **72h** — одинаково для всех source.
- Факт: ~**1592** suggestion|probation due с p50 просрочки **~27h** (max **~51h**).
- Seed|active due: **53** ключей, p50 **~12h**, max **~39h**.
- Пропускная способность: **5** ключей / **300s** ≈ **1440** слотов/сутки (worker не менялся).
- Tie-break seed vs suggestion срабатывает **только при равной просрочке** — при backlog suggestion всегда забирает top-5.

Итог: worker жив, но **ёмкость + сортировка по просрочке** голодят seed/active; 6h для всего probation pool **невыполним** (~6400 слотов/сутки нужно для полного pool).

## Ограниченное исправление (3C)

1. **Tiered batch** (`discovery_keyword_selection.py`): **2/5** слотов зарезервированы под priority — `seed`, `manual`, **lifecycle active**; остальные — general pool с boost:
   - **+20h** virtual overdue для probation **без** `last_checked` (первый скан);
   - **+6h** для probation с просрочкой **>48h** (anti-starvation).
2. **Queue-aware probation schedule** (`apply_post_scan_schedule`): после успешного скана probation `next_scan_at` = max(6h, **24 × due_probation / slots_per_day**). Не ускоряет worker; честно растягивает интервал при backlog.
3. **Policy helpers** (`discovery_queue_policy.py`): оценка слотов/сутки, effective probation interval.

Discovery worker **не перезапускался**; код подхватится при следующем restart worker.

## Что система может обещать (при ~1440 slots/day)

| Группа | Policy | Реалистично сейчас |
|--------|--------|---------------------|
| seed / manual / active | 24h (active) | **Да**, с reserved slots |
| probation (полный due ~1600) | 6h | **Нет** — honest **~26.5h** rotation |
| weak | 72h | Да, если не вытеснен backlog (reserved не covers weak) |

Read-only replay: `artifacts/audit_3c_discovery_queue_report.json` (`python artifacts/audit_3c_discovery_queue_replay_readonly.py`).

## Fix 3C.1 — проверка ёмкости (до restart Discovery)

**Spillover в коде:** после `priority[:2]` цикл по `general` добивает batch до 5; неиспользованные reserved **переходят probation** (тест `test_unused_priority_slots_spill_to_general`).

**Фактический batch для selector:** worker `--batch-size 5`, exploration ON (0.2) → **`seed_slots=4`** (`resolve_selector_keyword_batch_size()`). Отсюда **181×4≈724** scan-runs/24h, не 288×5.

**Интервал probation (scheduling):** `min(measured_probation_scan_runs/day, structural (batch−reserved)×cycles/day)`; fallback при <15 cycles. **Не SLA:** при due≈1610 и ~372 probation slots/day оценка rotation **~104h** (см. live cycle). **6h не обещаем.**

**Факт за 24h / 72h** (`audit_3c_capacity_verification_report.json`):

| Метрика | 24h | 72h → /day |
|---------|-----|------------|
| Завершённых discovery cycles | 181 | ~186/day |
| **Scan-run rows** (слоты) | 724 | ~724/day |
| **Успешных scan-runs** (status ok) | 724 | — |
| **Уникальных keyword_id** | 724 | ~620/day |
| Среднее scans/cycle | 4.0 | (exploration забирает 1 слот) |

Measured rotation при due≈1610: **~53h** (24h) / **~52h** (72h) — медленнее теории 44.7h из‑за **~4 slots/cycle**, не 5.

**Replay 12 batch:** batch0–2 — seed **127–131** + never-checked probation; старые probation (282+) с batch1 — не бесконечное голодание.

Capacity script: `python artifacts/audit_3c_capacity_verification_readonly.py`

## Тесты

- `scripts/test_discovery_queue_policy_3c.py`
- `scripts/test_discovery_keyword_selection_3b.py` (совместимость)

#!/usr/bin/env python3
import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from migrate import load_dotenv

load_dotenv(ROOT / ".env.docker")
load_dotenv(ROOT / ".env")
user = os.environ["RADAR_LOCAL_DB_USER"].strip()
pw = quote(os.environ["RADAR_LOCAL_DB_PASSWORD"].strip(), safe="")
url = f"postgresql://{user}:{pw}@127.0.0.1:5433/youtube_radar_restore_check"
os.environ["DATABASE_URL"] = url

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.orm import Channel, ChannelSubscriberEnrichmentAttempt

smoke = json.loads((ROOT / "artifacts/stage25_smoke_report.json").read_text(encoding="utf-8"))
ids = smoke["stages"]["live_enrichment"].get("processed_channel_ids") or []
engine = create_engine(url)
Session = sessionmaker(bind=engine)
session = Session()
rows = {c.id: c for c in session.scalars(select(Channel).where(Channel.id.in_(ids))).all()}
attempts = {
    a.channel_id: a
    for a in session.scalars(
        select(ChannelSubscriberEnrichmentAttempt).where(
            ChannelSubscriberEnrichmentAttempt.channel_id.in_(ids),
        ),
    ).all()
}
counts: Counter[str] = Counter()
for cid in ids:
    ch = rows.get(cid)
    att = attempts.get(cid)
    if ch and ch.subscribers_api_status:
        counts[f"channel_row_status_{ch.subscribers_api_status}"] += 1
    elif att:
        counts[f"attempt_only_{att.last_outcome}"] += 1
    elif ch:
        counts["channel_exists_status_null"] += 1
    else:
        counts["no_channel_no_attempt"] += 1
print("old_smoke_ids", len(ids))
print(json.dumps(dict(counts), indent=2))
session.close()

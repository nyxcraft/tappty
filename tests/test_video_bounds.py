"""The render event-collection bounds (pure -- no pygame/ffmpeg, runs in the core profile).

`render_video` materializes events to size the timeline; `_collect_events` must bound that by
count AND real bytes, checking before appending so a final event can't overrun the ceiling.
"""

import tappty.video as video


def test_byte_budget_checked_before_append(monkeypatch):
    monkeypatch.setattr(video, "MAX_RENDER_BYTES", 100)
    monkeypatch.setattr(video, "MAX_RENDER_EVENTS", 1_000_000)
    evs = [(0.0, "x" * 60), (1.0, "y" * 60), (2.0, "z" * 60)]
    # 60 fits; 60+60 would exceed 100, so the 2nd is refused *before* being appended (no overrun)
    assert video._collect_events(iter(evs), byte_source=False) == evs[:1]


def test_event_count_cap(monkeypatch):
    monkeypatch.setattr(video, "MAX_RENDER_BYTES", 1 << 30)
    monkeypatch.setattr(video, "MAX_RENDER_EVENTS", 2)
    evs = [(float(i), "a") for i in range(5)]
    assert video._collect_events(iter(evs), byte_source=False) == evs[:2]


def test_budget_counts_bytes_not_code_points(monkeypatch):
    monkeypatch.setattr(video, "MAX_RENDER_EVENTS", 1_000_000)
    monkeypatch.setattr(video, "MAX_RENDER_BYTES", 5)
    # "🔥" is one code point but four UTF-8 bytes; counting chars would keep both (2 <= 5),
    # counting bytes keeps only the first (4 <= 5, 8 > 5).
    got = video._collect_events(iter([(0.0, "🔥"), (1.0, "🔥")]), byte_source=False)
    assert len(got) == 1


def test_byte_source_counts_latin1_bytes(monkeypatch):
    # A byte source hands up a latin-1 byte-transparent str (1 char == 1 byte), so len() is the
    # byte count directly -- no UTF-8 re-encode that would double-count high bytes.
    monkeypatch.setattr(video, "MAX_RENDER_EVENTS", 1_000_000)
    monkeypatch.setattr(video, "MAX_RENDER_BYTES", 4)
    evs = [(0.0, "\xff\xff"), (1.0, "\xff\xff"), (2.0, "\xff")]
    assert video._collect_events(iter(evs), byte_source=True) == evs[:2]  # 2 + 2 == 4 fits

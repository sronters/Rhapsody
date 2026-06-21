from __future__ import annotations

from prometheus_client import Gauge

rhapsody_active_calls = Gauge("rhapsody_active_calls", "Active live call sessions.")
rhapsody_available_listeners = Gauge(
    "rhapsody_available_listeners", "Recorder accounts available for live calls."
)
rhapsody_last_audio_age_seconds = Gauge(
    "rhapsody_last_audio_age_seconds", "Age of the oldest active call audio heartbeat."
)
rhapsody_listener_heartbeat_age_seconds = Gauge(
    "rhapsody_listener_heartbeat_age_seconds",
    "Age of the oldest active recorder heartbeat.",
)
rhapsody_call_reconnects_total = Gauge(
    "rhapsody_call_reconnects_total", "Total reconnect attempts recorded for call sessions."
)
rhapsody_audio_chunks_total = Gauge(
    "rhapsody_audio_chunks_total", "Total persisted live-call audio chunks."
)
rhapsody_pending_upload_chunks = Gauge(
    "rhapsody_pending_upload_chunks", "Live-call audio chunks waiting for object storage upload."
)
rhapsody_failed_transcription_chunks = Gauge(
    "rhapsody_failed_transcription_chunks", "Live-call chunks with failed transcription."
)
rhapsody_oldest_pending_chunk_age_seconds = Gauge(
    "rhapsody_oldest_pending_chunk_age_seconds",
    "Age of the oldest live-call chunk pending upload or transcription.",
)
rhapsody_spool_size_bytes = Gauge(
    "rhapsody_spool_size_bytes", "Total bytes currently present in the listener spool directory."
)

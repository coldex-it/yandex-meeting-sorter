from pathlib import Path

from app.storage import StateStore


def test_reads_paths_and_details_for_existing_message(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    try:
        store.record(
            uid=10,
            message_id="<message-10>",
            subject="Meeting",
            status="uploaded",
            disk_paths=["/Meetings/transcript.txt", "/Meetings/Конспект transcript.txt"],
            details="summary_v1_saved",
        )

        assert store.get_disk_paths(10, "<message-10>") == [
            "/Meetings/transcript.txt",
            "/Meetings/Конспект transcript.txt",
        ]
        assert store.get_details(10, "<message-10>") == "summary_v1_saved"
    finally:
        store.close()

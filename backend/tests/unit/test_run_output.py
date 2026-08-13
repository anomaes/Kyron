from pathlib import Path

from backend.api.run_routes import MAX_TAIL_READ_BYTES, _read_tail_lines


def test_tail_reader_reads_from_end_without_loading_the_whole_file(tmp_path: Path) -> None:
    output = tmp_path / "large.log"
    output.write_bytes(b"old\n" + b"x" * (MAX_TAIL_READ_BYTES + 1024) + b"\nlast\n")

    content, truncated = _read_tail_lines(output, 1)

    assert content == "last"
    assert truncated

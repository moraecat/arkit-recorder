# tests/test_clips.py
import json

import pytest

from arkit_recorder.clips import delete_clip, list_clips, rename_clip


def write_clip(dir_path, name, entries):
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / (name + ".jsonl")
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return path


def test_list_clips_sorted_and_filtered(tmp_path):
    write_clip(tmp_path, "b_second", [{"t": 0, "d": "x"}, {"t": 2500, "d": "x"}])
    write_clip(tmp_path, "a_first", [{"t": 0, "d": "x"}, {"t": 1200, "d": "x"}])
    write_clip(tmp_path, "_recording.tmp", [{"t": 0, "d": "x"}])
    infos = list_clips(tmp_path)
    assert [i.name for i in infos] == ["a_first", "b_second"]
    assert infos[0].duration_s == pytest.approx(1.2)
    assert infos[1].duration_s == pytest.approx(2.5)
    assert infos[0].size_bytes > 0
    assert infos[0].path == tmp_path / "a_first.jsonl"


def test_list_clips_missing_dir(tmp_path):
    assert list_clips(tmp_path / "nope") == []


def test_duration_none_for_corrupt_last_line(tmp_path):
    (tmp_path / "bad.jsonl").write_text(
        '{"t": 0, "d": "x"}\nnot json\n', encoding="utf-8"
    )
    assert list_clips(tmp_path)[0].duration_s is None


def test_duration_none_for_empty_file(tmp_path):
    (tmp_path / "empty.jsonl").write_text("", encoding="utf-8")
    assert list_clips(tmp_path)[0].duration_s is None


def test_duration_reads_tail_of_large_file(tmp_path):
    # 4096바이트 꼬리 읽기만으로 마지막 t를 얻는지 (파일 전체 스캔 불필요 확인)
    entries = [{"t": i * 16, "d": "a" * 100} for i in range(5000)]
    write_clip(tmp_path, "big", entries)
    assert list_clips(tmp_path)[0].duration_s == pytest.approx(4999 * 16 / 1000.0)


def test_rename_clip_ok(tmp_path):
    write_clip(tmp_path, "old", [{"t": 0, "d": "x"}])
    new_path = rename_clip(tmp_path, "old", "new")
    assert new_path == tmp_path / "new.jsonl"
    assert new_path.exists()
    assert not (tmp_path / "old.jsonl").exists()


def test_rename_clip_strips_whitespace(tmp_path):
    write_clip(tmp_path, "old", [{"t": 0, "d": "x"}])
    assert rename_clip(tmp_path, "old", "  new  ") == tmp_path / "new.jsonl"


def test_rename_clip_errors(tmp_path):
    write_clip(tmp_path, "old", [{"t": 0, "d": "x"}])
    write_clip(tmp_path, "taken", [{"t": 0, "d": "x"}])
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "   ")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "_hidden")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "taken")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "ghost", "new")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "../evil")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "a/b")


def test_delete_clip(tmp_path):
    path = write_clip(tmp_path, "gone", [{"t": 0, "d": "x"}])
    delete_clip(path)
    assert not path.exists()
    delete_clip(path)  # missing_ok — 예외 없음

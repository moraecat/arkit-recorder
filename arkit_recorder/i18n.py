# arkit_recorder/i18n.py
from __future__ import annotations

LANGUAGES = ("ko", "en", "ja")

_current = "ko"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "en"


def current_language() -> str:
    return _current


def tr(key: str, **kwargs) -> str:
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key  # 미존재 키: 키 그대로 (크래시 방지)
    text = entry.get(_current) or entry["ko"]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def _t(ko: str, en: str, ja: str) -> dict[str, str]:
    return {"ko": ko, "en": en, "ja": ja}


TRANSLATIONS: dict[str, dict[str, str]] = {
    # 모드
    "mode.passthrough": _t("패스스루", "Passthrough", "パススルー"),
    "mode.recording": _t("녹화 중", "Recording", "録画中"),
    "mode.playing": _t("재생 중", "Playing", "再生中"),
    "mode.scrubbing": _t("스크럽 중", "Scrubbing", "スクラブ中"),
    "mode.paused": _t("일시정지", "Paused", "一時停止"),
    # 상단 바
    "label.recv_placeholder": _t("수신: -", "Input: -", "受信: -"),
    "label.mode_placeholder": _t("모드: -", "Mode: -", "モード: -"),
    "label.forward_placeholder": _t("전달: -", "Output: -", "転送: -"),
    "label.recv_none": _t(
        "수신: 없음 (아이폰 미연결)",
        "Input: none (iPhone not connected)",
        "受信: なし (iPhone未接続)",
    ),
    "label.recv_stale": _t(
        "수신: 끊김 ({seconds:.1f}초 전)",
        "Input: lost ({seconds:.1f}s ago)",
        "受信: 途切れ ({seconds:.1f}秒前)",
    ),
    "label.recv_hz": _t("수신: {hz} Hz", "Input: {hz} Hz", "受信: {hz} Hz"),
    "label.error": _t("오류: {error}", "Error: {error}", "エラー: {error}"),
    "label.mode": _t("모드: {mode}", "Mode: {mode}", "モード: {mode}"),
    "label.forward": _t(
        "전달: {host}:{port}", "Output: {host}:{port}", "転送: {host}:{port}"
    ),
    "btn.settings": _t("설정", "Settings", "設定"),
    # 좌측 패널 / 컨트롤 바
    "btn.record_start": _t("녹화 시작", "Start Recording", "録画開始"),
    "btn.record_stop": _t("녹화 정지 (저장)", "Stop Recording (Save)", "録画停止 (保存)"),
    "btn.play": _t("재생", "Play", "再生"),
    "btn.pause": _t("일시정지", "Pause", "一時停止"),
    "btn.stop": _t("정지", "Stop", "停止"),
    "btn.loop": _t("루프", "Loop", "ループ"),
    "btn.rename": _t("이름 변경", "Rename", "名前変更"),
    "btn.delete": _t("삭제", "Delete", "削除"),
    "btn.save_trim": _t(
        "구간을 새 클립으로 저장", "Save Range as New Clip", "区間を新規クリップとして保存"
    ),
    "label.curve": _t("곡선:", "Curve:", "カーブ:"),
    "curve.activity": _t("활동량", "Activity", "アクティビティ"),
    "clip.item_unknown": _t("{name} — ?", "{name} — ?", "{name} — ?"),
    "clip.item": _t(
        "{name} — {seconds:.1f}초", "{name} — {seconds:.1f}s", "{name} — {seconds:.1f}秒"
    ),
    # 다이얼로그
    "dlg.save_clip.title": _t("클립 저장", "Save Clip", "クリップ保存"),
    "dlg.save_clip.prompt": _t("클립 이름:", "Clip name:", "クリップ名:"),
    "dlg.save_clip.discard": _t(
        "녹화를 저장하지 않고 버릴까요?",
        "Discard the recording without saving?",
        "録画を保存せずに破棄しますか?",
    ),
    "dlg.record_stop.title": _t("녹화 정지", "Stop Recording", "録画停止"),
    "dlg.record_stop.failed": _t(
        "녹화 정지 실패: {error}",
        "Failed to stop recording: {error}",
        "録画停止に失敗しました: {error}",
    ),
    "dlg.clip.title": _t("클립", "Clip", "クリップ"),
    "dlg.clip.select": _t("클립을 선택하세요.", "Select a clip.", "クリップを選択してください。"),
    "dlg.play.title": _t("재생", "Playback", "再生"),
    "dlg.play.failed": _t(
        "클립을 재생할 수 없습니다 (빈 파일 또는 녹화 중).",
        "Cannot play the clip (empty file or recording in progress).",
        "クリップを再生できません (空のファイルまたは録画中)。",
    ),
    "dlg.rename.title": _t("이름 변경", "Rename", "名前変更"),
    "dlg.rename.prompt": _t("새 이름:", "New name:", "新しい名前:"),
    "dlg.delete.title": _t("삭제", "Delete", "削除"),
    "dlg.delete.confirm": _t(
        "클립 {name}을(를) 삭제할까요?", "Delete clip {name}?", "クリップ {name} を削除しますか?"
    ),
    "dlg.trim.title": _t("구간 저장", "Save Range", "区間保存"),
    "dlg.trim.select_first": _t(
        "클립을 먼저 선택하세요.", "Select a clip first.", "先にクリップを選択してください。"
    ),
    "dlg.trim.empty": _t(
        "선택 구간에 프레임이 없습니다.",
        "No frames in the selected range.",
        "選択区間にフレームがありません。",
    ),
    "dlg.trim.prompt": _t("새 클립 이름:", "New clip name:", "新規クリップ名:"),
    # 타임라인
    "tl.recording": _t("녹화 중", "Recording", "録画中"),
    "tl.no_frames": _t("프레임 없음", "No frames", "フレームなし"),
    # 설정
    "set.title": _t("설정", "Settings", "設定"),
    "set.listen_port": _t("수신 포트", "Listen port", "受信ポート"),
    "set.forward_host": _t("전달 호스트", "Output host", "転送ホスト"),
    "set.forward_port": _t("전달 포트", "Output port", "転送ポート"),
    "set.crossfade_live": _t(
        "크로스페이드 라이브(ms)", "Crossfade live (ms)", "クロスフェード ライブ(ms)"
    ),
    "set.crossfade_loop": _t(
        "크로스페이드 루프(ms)", "Crossfade loop (ms)", "クロスフェード ループ(ms)"
    ),
    "set.language": _t("언어", "Language", "言語"),
    "set.lang_auto": _t("자동", "Auto", "自動"),
    "set.save": _t("저장", "Save", "保存"),
    "set.cancel": _t("취소", "Cancel", "キャンセル"),
    "set.err_int": _t(
        "{label}: 정수를 입력하세요", "{label}: enter an integer", "{label}: 整数を入力してください"
    ),
    "set.err_port_range": _t(
        "{label}: 1~65535 범위여야 합니다",
        "{label}: must be between 1 and 65535",
        "{label}: 1~65535の範囲で指定してください",
    ),
    "set.err_ms_range": _t(
        "{label}: 0 이상이어야 합니다",
        "{label}: must be 0 or greater",
        "{label}: 0以上で指定してください",
    ),
    "set.err_host_empty": _t(
        "전달 호스트: 비어 있을 수 없습니다",
        "Output host: cannot be empty",
        "転送ホスト: 空にできません",
    ),
    "set.restart_needed": _t(
        "언어 설정은 재시작 후 적용됩니다.",
        "The language setting takes effect after restart.",
        "言語設定は再起動後に適用されます。",
    ),
    # 코어 오류 (clips)
    "err.name_empty": _t(
        "클립 이름이 비어 있습니다", "Clip name is empty", "クリップ名が空です"
    ),
    "err.name_underscore": _t(
        "밑줄로 시작하는 이름은 사용할 수 없습니다",
        "Names starting with an underscore are not allowed",
        "アンダースコアで始まる名前は使用できません",
    ),
    "err.name_pathchars": _t(
        "이름에 경로 문자를 사용할 수 없습니다",
        "Path characters are not allowed in the name",
        "名前にパス文字は使用できません",
    ),
    "err.name_taken": _t(
        "같은 이름의 클립이 이미 있습니다: {name}",
        "A clip with the same name already exists: {name}",
        "同名のクリップが既に存在します: {name}",
    ),
    "err.clip_missing": _t(
        "클립을 찾을 수 없습니다: {name}", "Clip not found: {name}", "クリップが見つかりません: {name}"
    ),
    # 코어 오류 (proxy)
    "err.bind_failed": _t(
        "포트 {port} 바인드 실패 (다른 프로그램이 사용 중일 수 있음): {error}",
        "Failed to bind port {port} (another program may be using it): {error}",
        "ポート {port} のバインドに失敗しました (他のプログラムが使用中の可能性): {error}",
    ),
    "err.apply_not_passthrough": _t(
        "패스스루 상태에서만 설정을 적용할 수 있습니다",
        "Settings can only be applied in passthrough mode",
        "設定はパススルー状態でのみ適用できます",
    ),
    "err.port_change_kept": _t(
        "수신 포트 변경 실패, 이전 포트 유지: {error}",
        "Failed to change listen port, keeping the previous port: {error}",
        "受信ポートの変更に失敗、以前のポートを維持します: {error}",
    ),
    "err.port_change_lost": _t(
        "수신 포트 변경 실패, 이전 포트 복구도 실패 (수신이 중단됨, 설정에서 포트를 다시 지정하세요): {error}",
        "Failed to change listen port and to restore the previous one (input stopped; set the port again in Settings): {error}",
        "受信ポートの変更に失敗し、以前のポートの復元にも失敗しました (受信停止中、設定でポートを再指定してください): {error}",
    ),
}

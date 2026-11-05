"""Built-in notice text: "version 0", shown until an admin saves one. Task 6 refines the wording."""
from __future__ import annotations

from app.notice.content import NoticeContent

DEFAULT_NOTICE = NoticeContent(
    title="행동 감사 안내",
    body=(
        "이 PC의 원격 접속 세션은 보안 감사를 위해 기록됩니다.\n"
        "\n"
        "- 접속 정보(사용자, 접속 IP, 시각)\n"
        "- 실행한 프로그램과 명령\n"
        "- 창 전환 기록"
    ),
    button_text="확인",
)

"""Built-in notice text: "version 0", shown until an admin saves one.

Wording from the Task 6 ux-copy pass (formal 합니다체, U15 markup: blank-line paragraphs, a
paragraph of "- " lines is a list, **bold**). web/src/copy/ko.ts ``notice.builtIn`` carries the
same text for the standalone /notice page; web/src/copy/ko.test.ts fails if the two drift.
"""
from __future__ import annotations

from app.notice.content import NoticeContent

DEFAULT_NOTICE = NoticeContent(
    title="원격 접속 행동 감사 안내",
    body=(
        "**이 원격 데스크톱 연결에서 하는 작업은 보안 감사를 위해 기록됩니다.**\n"
        "\n"
        "기록하는 내용은 다음과 같습니다.\n"
        "\n"
        "- 접속 정보: 사용자, 접속한 PC 이름과 IP 주소, 연결 시각\n"
        "- 실행한 프로그램과 명령\n"
        "- 창 전환 기록\n"
        "\n"
        "이 안내는 연결할 때마다 표시됩니다. 확인을 누르면 작업을 계속할 수 있습니다."
    ),
    button_text="확인",
)

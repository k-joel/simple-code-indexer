from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simple_code_indexer.setup_wizard.prompts import Prompter


class FakeQuestion:
    def __init__(self, answer: Any) -> None:
        self._answer = answer

    def ask(self) -> Any:
        return self._answer


class FakeQuestionary:
    def __init__(
        self,
        *,
        select: Any = 0,
        checkbox: Any = None,
        confirm: bool = True,
        text: str = "",
        password: str = "",
    ) -> None:
        self.select_answer = select
        self.checkbox_answer = checkbox if checkbox is not None else []
        self.confirm_answer = confirm
        self.text_answer = text
        self.password_answer = password
        self.calls: list[tuple[str, Any, dict[str, Any]]] = []

    def Choice(self, title: str, value: Any, checked: bool = False) -> dict[str, Any]:
        return {"title": title, "value": value, "checked": checked}

    def select(self, message: str, **kwargs: Any) -> FakeQuestion:
        self.calls.append(("select", message, kwargs))
        return FakeQuestion(self.select_answer)

    def checkbox(self, message: str, **kwargs: Any) -> FakeQuestion:
        self.calls.append(("checkbox", message, kwargs))
        return FakeQuestion(self.checkbox_answer)

    def confirm(self, message: str, **kwargs: Any) -> FakeQuestion:
        self.calls.append(("confirm", message, kwargs))
        return FakeQuestion(self.confirm_answer)

    def text(self, message: str, **kwargs: Any) -> FakeQuestion:
        self.calls.append(("text", message, kwargs))
        return FakeQuestion(self.text_answer)

    def password(self, message: str, **kwargs: Any) -> FakeQuestion:
        self.calls.append(("password", message, kwargs))
        return FakeQuestion(self.password_answer)


def _install_fake(monkeypatch, fake: FakeQuestionary) -> None:
    monkeypatch.setattr(Prompter, "_questionary", staticmethod(lambda: fake))


def test_interactive_prompts_use_questionary(monkeypatch) -> None:
    fake = FakeQuestionary(
        select=1,
        checkbox=[2, 0],
        confirm=False,
        text="hello",
        password="secret",
    )
    _install_fake(monkeypatch, fake)
    prompter = Prompter(interactive=True)

    assert prompter.ask_choice("pick", ["a", "b", "c"], default=0, search=True) == 1
    _, _, select_kwargs = fake.calls[-1]
    assert select_kwargs["default"]["value"] == 0
    assert select_kwargs["use_search_filter"] is True

    assert prompter.ask_multi("toggle", ["a", "b", "c"], default=[0]) == [0, 2]
    _, _, checkbox_kwargs = fake.calls[-1]
    assert checkbox_kwargs["choices"][0]["checked"] is True
    assert checkbox_kwargs["choices"][1]["checked"] is False

    assert prompter.ask_yes_no("sure?", default=True) is False
    assert prompter.ask_text("name", default="x") == "hello"
    assert prompter.ask_text("key", secret=True) == "secret"


def test_cancelled_menu_raises_keyboard_interrupt(monkeypatch) -> None:
    _install_fake(monkeypatch, FakeQuestionary(select=None))
    prompter = Prompter(interactive=True)

    with pytest.raises(KeyboardInterrupt):
        prompter.ask_choice("pick", ["a", "b"])

    fake = FakeQuestionary()
    fake.checkbox_answer = None
    _install_fake(monkeypatch, fake)
    with pytest.raises(KeyboardInterrupt):
        prompter.ask_multi("toggle", ["a", "b"])


def test_non_interactive_fallback_uses_input() -> None:
    answers = iter(["2", "1,3", "y", "value"])
    output: list[str] = []

    def _input(_prompt: str) -> str:
        return next(answers)

    prompter = Prompter(input_fn=_input, output_fn=output.append, interactive=False)

    assert prompter.ask_choice("pick", ["a", "b"]) == 1
    assert prompter.ask_multi("toggle", ["a", "b", "c"]) == [0, 2]
    assert prompter.ask_yes_no("sure?") is True
    assert prompter.ask_text("name") == "value"
    assert any("1. a" in line for line in output)


def test_no_tui_env_disables_interactive(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_CI_NO_TUI", "1")

    assert Prompter().interactive is False
    assert Prompter(interactive=True).interactive is True


def test_choice_defaults_and_bounds() -> None:
    def _input(_prompt: str) -> str:
        return ""

    prompter = Prompter(
        input_fn=_input, output_fn=lambda _line: None, interactive=False
    )

    assert prompter.ask_choice("pick", ["a", "b"], default=99) == 1
    assert prompter.ask_multi("toggle", ["a", "b"], default=[1]) == [1]


def test_questionary_is_lazy_imported() -> None:
    from simple_code_indexer.setup_wizard import prompts

    module: Callable[[], Any] = prompts.Prompter._questionary
    assert module() is not None

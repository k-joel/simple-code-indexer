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

    def Separator(self, text: str = "") -> dict[str, Any]:
        return {"separator": text}

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
    assert select_kwargs["use_jk_keys"] is False

    assert prompter.ask_choice("pick", ["a", "b", "c"], default=0) == 1
    _, _, select_kwargs = fake.calls[-1]
    assert select_kwargs["use_search_filter"] is False
    assert select_kwargs["use_jk_keys"] is True

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


def test_harness_multi_offers_the_two_shortcut_rows(monkeypatch) -> None:
    fake = FakeQuestionary(checkbox=[0])
    _install_fake(monkeypatch, fake)

    Prompter(interactive=True).ask_harness_multi(
        "which", ["a (a)", "b (b)"], default=[0], detected=[1]
    )

    _, _, kwargs = fake.calls[-1]
    choices = kwargs["choices"]
    assert choices[0]["title"] == "Select all detected"
    assert choices[1]["title"] == "Unselect all"
    assert choices[2] == {"separator": ""}
    assert [choice["checked"] for choice in choices[3:]] == [True, False]


def test_select_all_detected_returns_the_detected_set(monkeypatch) -> None:
    fake = FakeQuestionary(checkbox=["__select_detected__"])
    _install_fake(monkeypatch, fake)

    selected = Prompter(interactive=True).ask_harness_multi(
        "which", ["a", "b", "c"], default=[2], detected=[0, 2]
    )

    assert selected == [0, 2]


def test_unselect_all_wins_over_select_all_detected(monkeypatch) -> None:
    """Clearing is the stronger intent, so it is never silently ignored."""
    fake = FakeQuestionary(checkbox=["__select_detected__", "__unselect_all__"])
    _install_fake(monkeypatch, fake)

    assert Prompter(interactive=True).ask_harness_multi("which", ["a"], detected=[0]) == []


def test_harness_multi_falls_back_to_numbered_answers() -> None:
    answers = iter(["", "all", "all-detected", "none", "1,3"])
    output: list[str] = []
    prompter = Prompter(
        input_fn=lambda _prompt: next(answers),
        output_fn=output.append,
        interactive=False,
    )

    assert prompter.ask_harness_multi("which", ["a", "b", "c"], default=[1]) == [1]
    assert prompter.ask_harness_multi("which", ["a", "b", "c"]) == [0, 1, 2]
    assert prompter.ask_harness_multi("which", ["a", "b", "c"], detected=[2]) == [2]
    assert prompter.ask_harness_multi("which", ["a", "b", "c"]) == []
    assert prompter.ask_harness_multi("which", ["a", "b", "c"]) == [0, 2]
    assert any("Select all detected" in line for line in output)

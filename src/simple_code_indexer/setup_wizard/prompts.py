"""Plain-stdlib prompts for the setup wizard (no questionary/tui dependency)."""

from __future__ import annotations

from collections.abc import Callable, Sequence


class Prompter:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn

    def say(self, message: str = "") -> None:
        self._output(message)

    def ask_yes_no(self, question: str, *, default: bool = True) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            answer = self._input(f"{question} {suffix} ").strip().lower()
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            self.say("Please answer y or n.")

    def ask_choice(
        self, question: str, options: Sequence[str], *, default: int = 0
    ) -> int:
        self.say(question)
        for index, label in enumerate(options, start=1):
            self.say(f"  {index}. {label}")
        while True:
            answer = self._input(f"Choice [{default + 1}]: ").strip()
            if not answer:
                return default
            try:
                choice = int(answer) - 1
            except ValueError:
                self.say("Enter a number from the list.")
                continue
            if 0 <= choice < len(options):
                return choice
            self.say("Enter a number from the list.")

    def ask_multi(
        self,
        question: str,
        options: Sequence[str],
        *,
        default: Sequence[int] = (),
    ) -> list[int]:
        self.say(question)
        for index, label in enumerate(options, start=1):
            self.say(f"  {index}. {label}")
        hint = ", ".join(str(item + 1) for item in default) or "none"
        while True:
            answer = (
                self._input(f"Numbers, comma-separated, 'all', or blank [{hint}]: ")
                .strip()
                .lower()
            )
            if not answer:
                return list(default)
            if answer == "all":
                return list(range(len(options)))
            selected: list[int] = []
            try:
                for token in answer.replace(" ", "").split(","):
                    index = int(token) - 1
                    if not 0 <= index < len(options):
                        raise ValueError
                    selected.append(index)
            except ValueError:
                self.say("Enter numbers from the list, or 'all'.")
                continue
            return sorted(set(selected))

    def ask_text(
        self,
        question: str,
        *,
        default: str | None = None,
        allow_empty: bool = False,
    ) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            answer = self._input(f"{question}{suffix}: ").strip()
            if answer:
                return answer
            if default is not None:
                return default
            if allow_empty:
                return ""
            self.say("A value is required.")

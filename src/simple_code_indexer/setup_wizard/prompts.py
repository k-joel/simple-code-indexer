"""Interactive prompts for the setup wizard.

questionary renders the menus (arrow keys, type-to-filter) on every platform we
support — including Windows, where ``simple-term-menu`` cannot even be imported
because it depends on ``termios``.

The numbered ``input()`` implementation is kept as the non-interactive
fallback: tests inject their own prompter, and piped/`--yes` runs must never
block on a TUI.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence

_DISABLE_ENV = "SIMPLE_CI_NO_TUI"


class Prompter:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        *,
        interactive: bool | None = None,
    ) -> None:
        self._input = input_fn
        self._output = output_fn
        self._interactive = interactive

    @property
    def interactive(self) -> bool:
        """True when a questionary TUI is safe to draw."""
        if self._interactive is not None:
            return self._interactive
        if os.environ.get(_DISABLE_ENV, "").lower() in {"1", "true", "yes"}:
            return False
        try:
            return sys.stdin.isatty() and sys.stdout.isatty()
        except (AttributeError, ValueError):
            return False

    def say(self, message: str = "") -> None:
        self._output(message)

    # -- yes/no ----------------------------------------------------------

    def ask_yes_no(self, question: str, *, default: bool = True) -> bool:
        if self.interactive:
            answer = (
                self._questionary()
                .confirm(
                    question,
                    default=default,
                    auto_enter=False,
                )
                .ask()
            )
            if answer is None:
                raise KeyboardInterrupt
            return bool(answer)
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

    # -- single select ---------------------------------------------------

    def ask_choice(
        self,
        question: str,
        options: Sequence[str],
        *,
        default: int = 0,
        search: bool = False,
        instruction: str | None = None,
    ) -> int:
        if not options:
            raise ValueError("ask_choice requires at least one option")
        default = max(0, min(default, len(options) - 1))
        if self.interactive:
            choices = [
                self._questionary().Choice(title=label, value=index)
                for index, label in enumerate(options)
            ]
            answer = (
                self._questionary()
                .select(
                    question,
                    choices=choices,
                    default=choices[default],
                    use_search_filter=search,
                    use_jk_keys=not search,
                    instruction=instruction,
                )
                .ask()
            )
            if answer is None:
                raise KeyboardInterrupt
            return int(answer)
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

    # -- multi select ----------------------------------------------------

    def ask_multi(
        self,
        question: str,
        options: Sequence[str],
        *,
        default: Sequence[int] = (),
        instruction: str | None = None,
    ) -> list[int]:
        if self.interactive:
            selected = set(default)
            choices = [
                self._questionary().Choice(
                    title=label,
                    value=index,
                    checked=index in selected,
                )
                for index, label in enumerate(options)
            ]
            answer = (
                self._questionary()
                .checkbox(
                    question,
                    choices=choices,
                    instruction=instruction,
                )
                .ask()
            )
            if answer is None:
                raise KeyboardInterrupt
            return sorted({int(item) for item in answer})
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
            selected = []
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

    # -- text ------------------------------------------------------------

    def ask_text(
        self,
        question: str,
        *,
        default: str | None = None,
        allow_empty: bool = False,
        secret: bool = False,
    ) -> str:
        if self.interactive:
            if secret:
                answer = self._questionary().password(question).ask()
            else:
                answer = self._questionary().text(question, default=default or "").ask()
            if answer is None:
                raise KeyboardInterrupt
            answer = answer.strip()
            if answer:
                return answer
            if default is not None:
                return default
            if allow_empty:
                return ""
            return self.ask_text(
                question,
                default=default,
                allow_empty=allow_empty,
                secret=secret,
            )
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

    @staticmethod
    def _questionary():
        import questionary

        return questionary

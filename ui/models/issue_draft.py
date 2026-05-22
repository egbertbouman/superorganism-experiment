from dataclasses import dataclass

from ui.constants import (
    ISSUE_TITLE_MIN_LENGTH,
    ISSUE_TITLE_MAX_LENGTH,
    ISSUE_DESCRIPTION_MIN_LENGTH,
    ISSUE_DESCRIPTION_MAX_LENGTH,
)


@dataclass(frozen=True)
class IssueDraft:
    title: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "description", self.description.strip())

    def validate_title(self) -> str:
        if not self.title:
            return "Title is required."
        if len(self.title) < ISSUE_TITLE_MIN_LENGTH:
            return f"Title must be at least {ISSUE_TITLE_MIN_LENGTH} characters."
        if len(self.title) > ISSUE_TITLE_MAX_LENGTH:
            return f"Title must be at most {ISSUE_TITLE_MAX_LENGTH} characters."
        return ""

    def validate_description(self) -> str:
        if not self.description:
            return "Description is required."
        if len(self.description) < ISSUE_DESCRIPTION_MIN_LENGTH:
            return f"Description must be at least {ISSUE_DESCRIPTION_MIN_LENGTH} characters."
        if len(self.description) > ISSUE_DESCRIPTION_MAX_LENGTH:
            return f"Description must be at most {ISSUE_DESCRIPTION_MAX_LENGTH} characters."
        return ""

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}

        title_error = self.validate_title()
        if title_error:
            errors["title"] = title_error

        description_error = self.validate_description()
        if description_error:
            errors["description"] = description_error

        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()

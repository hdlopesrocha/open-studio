"""Pydantic request models for the PDF API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2048)


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2048)
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    selected_pages: list[int] | None = Field(default=None, max_length=2000)
    ocr_enabled: bool = False
    ocr_language: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_pages(self) -> "ExtractRequest":
        if (
            self.start_page is not None
            and self.end_page is not None
            and self.end_page < self.start_page
        ):
            raise ValueError("end_page must be greater than or equal to start_page")
        if self.selected_pages is not None:
            if not self.selected_pages:
                raise ValueError("selected_pages cannot be empty")
            if any(page < 1 for page in self.selected_pages):
                raise ValueError("selected_pages must use 1-based page numbers")
            if len(set(self.selected_pages)) > 2000:
                raise ValueError("At most 2000 pages can be selected")
        if (
            self.start_page is not None
            and self.end_page is not None
            and self.end_page - self.start_page > 2000
        ):
            raise ValueError("The page range is too large")
        return self

    def resolved_pages(self, page_count: int) -> list[int]:
        if self.selected_pages:
            pages = sorted(set(self.selected_pages))
        elif self.start_page is not None and self.end_page is not None:
            pages = list(range(self.start_page, self.end_page + 1))
        elif self.start_page is not None:
            pages = [self.start_page]
        elif self.end_page is not None:
            pages = list(range(1, self.end_page + 1))
        else:
            pages = list(range(1, page_count + 1))
        if not pages:
            raise ValueError("At least one page must be selected")
        if any(page > page_count for page in pages):
            raise ValueError(f"Page numbers must be between 1 and {page_count}")
        return pages

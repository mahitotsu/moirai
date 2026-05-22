from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ReportType = Literal["incident-summary", "cost", "operational", "custom"]


class ReportCreate(BaseModel):
    title: str
    type: ReportType
    summary: str
    details: str


class Report(BaseModel):
    report_id: str
    title: str
    type: str
    summary: str
    details: str
    created_at: str

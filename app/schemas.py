from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Report(Strict):
    description: str = Field(min_length=10, max_length=8000)
    location: str = Field(min_length=2, max_length=250)
    time: str = Field(min_length=1, max_length=100)
    harm: str = Field(min_length=1, max_length=2000)
    remains: str = Field(min_length=1, max_length=2000)
    age_range: Literal['Under 18', '18 and over', 'Prefer not to say']
    consent: bool = False
    name: str = Field(default='', max_length=100)
    email: str = Field(default='', max_length=255)
    confirmed: Literal[True]

    @field_validator('email')
    @classmethod
    def email_check(cls, value):
        if value and ('@' not in value or '.' not in value.split('@')[-1] or '\n' in value or '\r' in value):
            raise ValueError('Enter a valid email address.')
        return value


class Login(Strict):
    email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=200)


class Revision(Strict):
    version: int = Field(ge=1)


class Triage(Revision):
    category: Literal['Hazard', 'Near miss', 'Minor injury', 'Other incident']
    priority: Literal['Immediate', 'Urgent', 'Routine']
    officer_id: str
    reason: str = Field(min_length=3, max_length=2000)
    approve: bool = False


class Findings(Revision):
    details: str = Field(min_length=3, max_length=4000)
    evidence: str = Field(min_length=3, max_length=4000)
    assistance: str = Field(min_length=1, max_length=2000)
    control: str = Field(min_length=3, max_length=4000)
    approve: bool = False


class Outcome(Revision):
    text: str = Field(min_length=3, max_length=8000)
    approve: bool = False


class Reopen(Revision):
    reason: str = Field(min_length=5, max_length=2000)


class Tracking(Strict):
    reference: str = Field(min_length=1, max_length=32)
    token: str = Field(min_length=1, max_length=100)


class GroupReview(Strict):
    case_ids: list[str] = Field(min_length=2, max_length=30)
    relationship: Literal['same_event', 'recurring']
    reason: str = Field(min_length=3, max_length=2000)


class Riddor(Revision):
    kind: Literal['unreviewed', 'none', 'ten', 'fifteen', 'disease']
    incident_date: str = ''
    notified_date: str = ''
    received_date: str = ''
    reason: str = Field(min_length=3, max_length=2000)

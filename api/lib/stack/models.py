from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator
from typing import Optional

class CreateStack(BaseModel):
    name: str
    description: str
    supervisor: int
    supporting: list[int]

class ExecuteStack(BaseModel):
    message: str
    verbose: bool = False

class UpdateStack(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    supervisor: Optional[int] = None
    supporting: Optional[list[int]] = None

class StackScheduleRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class StackScheduleType(str, Enum):
    INTERVAL = "interval"
    FIXED = "fixed"
    RECURRING = "recurring"

class StackScheduleRecurrence(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"

class StackScheduleTimeStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"

_MIN_SCHEDULE_INTERVAL_SECONDS = 60

class CreateStackSchedule(BaseModel):
    stack_id: int
    name: str
    message: str
    schedule_type: StackScheduleType = StackScheduleType.INTERVAL
    interval_seconds: Optional[int] = Field(default=None, ge=_MIN_SCHEDULE_INTERVAL_SECONDS)
    run_times: Optional[list[datetime]] = None
    recurrence: Optional[StackScheduleRecurrence] = None
    recurrence_day: Optional[int] = None
    recurrence_hour: int = Field(default=0, ge=0, le=23)
    recurrence_minute: int = Field(default=0, ge=0, le=59)
    enabled: bool = True
    verbose: bool = False

    @model_validator(mode="after")
    def validate_schedule_config(self) -> "CreateStackSchedule":
        if self.schedule_type == StackScheduleType.INTERVAL:
            if self.interval_seconds is None:
                raise ValueError("interval_seconds is required for interval schedules")
            if self.run_times:
                raise ValueError("run_times must not be set for interval schedules")
            if self.recurrence is not None or self.recurrence_day is not None:
                raise ValueError("recurrence fields must not be set for interval schedules")
        elif self.schedule_type == StackScheduleType.FIXED:
            if not self.run_times:
                raise ValueError("run_times is required for fixed schedules")
            if self.interval_seconds is not None:
                raise ValueError("interval_seconds must not be set for fixed schedules")
            if self.recurrence is not None or self.recurrence_day is not None:
                raise ValueError("recurrence fields must not be set for fixed schedules")
        else:
            if self.recurrence is None or self.recurrence_day is None:
                raise ValueError("recurrence and recurrence_day are required for recurring schedules")
            from lib.stack.recurrence import validate_recurrence_day

            validate_recurrence_day(self.recurrence, self.recurrence_day)
            if self.interval_seconds is not None:
                raise ValueError("interval_seconds must not be set for recurring schedules")
            if self.run_times:
                raise ValueError("run_times must not be set for recurring schedules")
        return self

class UpdateStackSchedule(BaseModel):
    name: Optional[str] = None
    message: Optional[str] = None
    schedule_type: Optional[StackScheduleType] = None
    interval_seconds: Optional[int] = Field(default=None, ge=_MIN_SCHEDULE_INTERVAL_SECONDS)
    run_times: Optional[list[datetime]] = None
    recurrence: Optional[StackScheduleRecurrence] = None
    recurrence_day: Optional[int] = None
    recurrence_hour: Optional[int] = Field(default=None, ge=0, le=23)
    recurrence_minute: Optional[int] = Field(default=None, ge=0, le=59)
    enabled: Optional[bool] = None
    verbose: Optional[bool] = None

    @model_validator(mode="after")
    def validate_schedule_config(self) -> "UpdateStackSchedule":
        if self.schedule_type == StackScheduleType.INTERVAL and self.run_times:
            raise ValueError("run_times must not be set for interval schedules")
        if self.schedule_type == StackScheduleType.FIXED and self.interval_seconds is not None:
            raise ValueError("interval_seconds must not be set for fixed schedules")
        if self.schedule_type == StackScheduleType.RECURRING:
            if self.interval_seconds is not None:
                raise ValueError("interval_seconds must not be set for recurring schedules")
            if self.run_times:
                raise ValueError("run_times must not be set for recurring schedules")
        if self.recurrence is not None and self.recurrence_day is not None:
            from lib.stack.recurrence import validate_recurrence_day

            validate_recurrence_day(self.recurrence, self.recurrence_day)
        return self

class StackScheduleTimePublic(BaseModel):
    id: int
    run_at: datetime
    status: StackScheduleTimeStatus

class StackSchedulePublic(BaseModel):
    id: int
    stack_id: int
    name: str
    message: str
    schedule_type: StackScheduleType
    interval_seconds: Optional[int] = None
    run_times: list[StackScheduleTimePublic] = []
    recurrence: Optional[StackScheduleRecurrence] = None
    recurrence_day: Optional[int] = None
    recurrence_hour: int = 0
    recurrence_minute: int = 0
    enabled: bool
    verbose: bool
    last_run_at: Optional[datetime] = None
    next_run_at: datetime
    created: datetime

class StackScheduleRunPublic(BaseModel):
    id: int
    schedule_id: int
    stack_id: int
    run_id: str
    schedule_time_id: Optional[int] = None
    status: StackScheduleRunStatus
    result: Optional[str] = None
    error: Optional[str] = None
    message_start_id: Optional[int] = None
    message_end_id: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

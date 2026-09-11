"""Train-domain grounding contracts. These never confer world authority."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


NPC_IDS = ("lin", "zhou", "chen", "xu")
NPC_NAMES = {"lin": "林岚", "zhou": "周屿", "chen": "陈默", "xu": "许宁"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PerformanceEventRequest(StrictModel):
    line_id: str = Field(min_length=1, max_length=240)
    event_id: str = Field(min_length=1, max_length=180)
    event_type: Literal["ack", "started", "completed", "interrupted", "error"]
    visuals_skipped: StrictBool = False


class TrainStep(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=64)
    helpers: list[str] = Field(default_factory=list, max_length=4)
    depends_on: list[str] = Field(default_factory=list, max_length=12)


class SocialDecision(StrictModel):
    """Only a decision actually voiced by this NPC may be submitted to rules.

    A compact flat contract avoids a large union schema on inexpensive models.
    The bridge strips irrelevant fields before handing a decision to the world.
    """

    kind: Literal[
        "share_fact", "accept_task", "loan", "child_delegation",
        "withdraw_loan", "revoke_task",
    ]
    evidence_quote: str = Field(min_length=1, max_length=800)
    fact_ids: list[str] = Field(default_factory=list, max_length=12)
    audience: list[str] = Field(default_factory=list, max_length=5)
    action_ids: list[str] = Field(default_factory=list, max_length=12)
    role: Literal["actor", "helper"] = "actor"
    conditions: list[str] = Field(default_factory=list, max_length=8)
    purpose: str = Field(default="", max_length=64)
    recipient_id: str = Field(default="", max_length=64)
    deadline_tick: int = Field(default=0, ge=0)
    reserve: int = Field(default=0, ge=0)
    rescuer_id: str = Field(default="", max_length=64)
    checkpoint_tick: int = Field(default=0, ge=0)
    reason: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def required_fields(self):
        if self.kind == "share_fact" and not self.fact_ids:
            raise ValueError("share_fact needs actual known fact IDs")
        if self.kind in {"accept_task", "revoke_task"} and not self.action_ids:
            raise ValueError("a task decision needs action IDs")
        if self.kind == "loan" and (self.purpose != "radio" or not self.recipient_id):
            raise ValueError("loan needs the supported radio purpose and named recipient")
        if self.kind == "child_delegation" and not self.rescuer_id:
            raise ValueError("delegation needs a named rescuer")
        return self

    def world_payload(self, decision_id: str) -> dict:
        keys = {
            "share_fact": ("fact_ids", "audience"),
            "accept_task": ("action_ids", "conditions", "role"),
            "loan": ("purpose", "recipient_id", "deadline_tick", "reserve"),
            "child_delegation": ("rescuer_id", "checkpoint_tick"),
            "withdraw_loan": ("reason",),
            "revoke_task": ("action_ids", "reason"),
        }[self.kind]
        raw = self.model_dump()
        return {"kind": self.kind, "decision_id": decision_id, **{k: raw[k] for k in keys}}


class TrainMeaning(StrictModel):
    """Ground an already generated v2 beat into suggestions and social acts."""

    title: str = Field(default="", max_length=100)
    steps: list[TrainStep] = Field(default_factory=list, max_length=12)
    decisions: list[SocialDecision] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def closed_plan(self):
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step IDs must be unique")
        todo = {s.id: set(s.depends_on) for s in self.steps}
        if any(deps - set(ids) for deps in todo.values()):
            raise ValueError("unknown plan dependency")
        done: set[str] = set()
        while todo:
            ready = {key for key, deps in todo.items() if deps <= done}
            if not ready:
                raise ValueError("cyclic plan")
            done |= ready
            todo = {key: deps for key, deps in todo.items() if key not in ready}
        return self


class PresentedFact(StrictModel):
    fact_id: str = Field(min_length=1, max_length=100)
    player_quote: str = Field(min_length=1, max_length=800)


class PlayerEvidence(StrictModel):
    """Evidence explicitly presented by the player, not their entire inventory."""
    presented: list[PresentedFact] = Field(default_factory=list, max_length=6)

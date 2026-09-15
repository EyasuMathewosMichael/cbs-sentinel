"""Local ASGI entry point for the deterministic simulation console."""

from typing import Any

from fastapi import FastAPI

from sentinel.adapters.cbs.factory import create_cbs_adapter
from sentinel.application.api import create_api
from sentinel.application.api.app import AllowAllAuthentication
from sentinel.application.orchestration.workflow import TransactionOrchestrator
from sentinel.domain.integrity import IntegrityEngine
from sentinel.domain.protection import ProtectiveAction, ProtectiveResponseEngine
from sentinel.domain.risk import RiskEngine


class _SimulationPolicy:
    async def decide(self, request: Any, risk: Any) -> ProtectiveAction:
        return ProtectiveAction.ALLOW


class _SimulationHooks:
    async def publish(self, event_type: Any, transaction: Any) -> None:
        return None

    async def request_reconciliation(self, transaction: Any) -> None:
        return None


def build_simulation_app() -> FastAPI:
    hooks = _SimulationHooks()
    orchestrator = TransactionOrchestrator(
        cbs=create_cbs_adapter("simulation"),
        integrity=IntegrityEngine(),
        risk=RiskEngine(),
        protection=ProtectiveResponseEngine(),
        policy=_SimulationPolicy(),
        reconciliation=hooks,
        events=hooks,
    )
    return create_api(orchestrator, authentication=AllowAllAuthentication())


app = build_simulation_app()

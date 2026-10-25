"""Narrow future orchestrator seam. No DB, identity authority or personal-agent registry."""

from typing import Protocol

from agents.schemas import AvailabilityResult, GatewayRequest


class AvailabilityGateway(Protocol):
    async def check(self, request: GatewayRequest) -> AvailabilityResult: ...


class GroupAgent:
    def __init__(self, gateway: AvailabilityGateway) -> None:
        self._gateway = gateway

    async def check(self, request: GatewayRequest) -> AvailabilityResult:
        return await self._gateway.check(request)

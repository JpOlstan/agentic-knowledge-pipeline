from typing import Any, Protocol, runtime_checkable

from knowledge_agents.domain.contracts import ArtifactRef


@runtime_checkable
class ArtifactStore(Protocol):
    async def write_json(
        self,
        *,
        run_id: str,
        artifact_type: str,
        payload: Any,
        schema_version: str,
    ) -> ArtifactRef: ...

    async def read_json(self, artifact: ArtifactRef) -> Any: ...

    async def exists(self, artifact: ArtifactRef) -> bool: ...

from __future__ import annotations

from pathlib import Path

import pytest
from engine_testkit import person

from pramana_contracts import ParticipantSpec
from pramana_domain import DomainPack, load_pack
from pramana_engine import CompiledModel, compile_pack

HERE = Path(__file__).parent


@pytest.fixture(scope="session")
def campus() -> DomainPack:
    return load_pack("campus_block_c")


@pytest.fixture(scope="session")
def campus_model(campus: DomainPack) -> CompiledModel:
    return compile_pack(campus)


@pytest.fixture(scope="session")
def toy_model() -> CompiledModel:
    return compile_pack(load_pack(HERE / "toy_pack.yaml"))


@pytest.fixture
def s1_people() -> list[ParticipantSpec]:
    return [
        person("p_riya", ["student"], "lay", "F3_R304"),
        person("p_mahesh", ["guard"], "access", "GUARD_DESK"),
        person("p_imran", ["electrician"], "technician", "MAINT_ROOM"),
    ]

"""Enforce layer rules, public module interfaces and acyclic use-case dependencies."""

import importlib

from tests.infra.architecture_analyzer import run_tests

from scripts import dependency_matrix as matrix
from scripts.module_boundaries import MODULE_DEPENDENCIES, PUBLIC_INTERFACES


def test_architecture_layer_rules() -> None:
    forbidden = matrix.summarize(matrix.analyze())["forbidden"]
    assert not forbidden, "\n".join(
        f"[{rule}] {source} -> {target}" for rule, source, target in forbidden
    )


def test_application_module_interfaces() -> None:
    violations = matrix.module_violations(
        matrix.analyze(), PUBLIC_INTERFACES, MODULE_DEPENDENCIES
    )
    assert not violations, "\n".join(violations)


def test_public_interfaces_resolve() -> None:
    analysis = matrix.analyze()
    assert PUBLIC_INTERFACES.keys() == MODULE_DEPENDENCIES.keys()
    features = {matrix.feature_of(name) for name in analysis["modules"]}
    features.discard(None)
    assert features == set(PUBLIC_INTERFACES), (
        "Register each application module explicitly"
    )
    for owner, interfaces in PUBLIC_INTERFACES.items():
        assert MODULE_DEPENDENCIES[owner] <= PUBLIC_INTERFACES.keys()
        for name in interfaces:
            assert matrix.feature_of(name) == owner
            assert name in analysis["modules"], f"Missing interface: {name}"
            exports = analysis["exports"].get(name)
            assert exports, f"Declare {name}.__all__ explicitly"
            module = importlib.import_module(name)
            for exported in exports:
                assert not exported.startswith("_") and hasattr(module, exported), (
                    f"Invalid public export: {name}.{exported}"
                )


def test_announcement_routes_use_application_boundaries() -> None:
    forbidden = [
        target
        for source, target in matrix.analyze()["edges"]
        if source == "app.api.v1.announcements.routes"
        and matrix.layer_of(target) in {"adapters", "domain", "entities", "infra"}
    ]
    assert not forbidden, (
        f"announcement routes bypass application interfaces: {forbidden}"
    )


def main() -> None:
    run_tests()
    test_architecture_layer_rules()
    test_application_module_interfaces()
    test_public_interfaces_resolve()
    test_announcement_routes_use_application_boundaries()
    print("ARCHITECTURE_SUITE_OK")


if __name__ == "__main__":
    main()

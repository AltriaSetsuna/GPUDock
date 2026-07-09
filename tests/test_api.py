from __future__ import annotations

from cmddock.api import build_app
from cmddock.config import build_settings


def test_list_commands_endpoint_treats_app_state_as_dependency(tmp_path):
    settings = build_settings(data_dir=tmp_path / "data")
    app = build_app(settings)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/commands"
        and "GET" in getattr(route, "methods", set())
    )

    query_param_names = {param.name for param in route.dependant.query_params}
    dependency_names = {dependency.name for dependency in route.dependant.dependencies}

    assert query_param_names == {"status", "group_id"}
    assert dependency_names == {"app_state"}


def test_retry_endpoint_does_not_wake_workers(tmp_path):
    settings = build_settings(data_dir=tmp_path / "data")
    app = build_app(settings)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/commands/{command_id}/retry"
        and "POST" in getattr(route, "methods", set())
    )

    assert "wake_workers" not in route.endpoint.__code__.co_names


def test_group_order_endpoint_uses_payload_body_not_query_params(tmp_path):
    settings = build_settings(data_dir=tmp_path / "data")
    app = build_app(settings)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/groups/order"
        and "PATCH" in getattr(route, "methods", set())
    )

    query_param_names = {param.name for param in route.dependant.query_params}
    body_param_name = route.dependant.body_params[0].name

    assert query_param_names == set()
    assert body_param_name == "payload"


def test_gpu_status_endpoints_are_registered(tmp_path):
    settings = build_settings(data_dir=tmp_path / "data")
    app = build_app(settings)
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/gpu/resources" in paths
    assert "/gpu/status" in paths

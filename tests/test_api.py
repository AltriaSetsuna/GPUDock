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

    assert query_param_names == {"status", "queue"}
    assert dependency_names == {"app_state"}

from __future__ import annotations

from eva.prompts.environment import HOME_HOSTS, HomeHost, build_environment_section


def test_default_hosts_are_not_exposed() -> None:
    assert HOME_HOSTS == ()


def test_build_environment_section_lists_default_hosts() -> None:
    section = build_environment_section()

    assert "10.0.0.2" not in section
    assert "10.0.0.187" not in section
    assert "private network addresses" in section


def test_build_environment_section_extends_with_extra_hosts() -> None:
    hosts = (
        HomeHost(name="boston", ip="10.0.0.2"),
        HomeHost(name="seattle", ip="10.0.0.187"),
        HomeHost(name="pi", ip="10.0.0.50", notes="raspberry pi 4"),
    )

    section = build_environment_section(hosts)

    assert "pi" in section
    assert "10.0.0.50" not in section
    assert "pi" in section
    assert "raspberry pi 4" in section


def test_build_environment_section_handles_empty_hosts() -> None:
    section = build_environment_section(())

    assert "private network addresses" in section

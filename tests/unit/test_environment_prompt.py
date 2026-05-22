from __future__ import annotations

from eva.prompts.environment import HOME_HOSTS, HomeHost, build_environment_section


def test_default_hosts_include_boston_and_seattle() -> None:
    names = {host.name for host in HOME_HOSTS}
    assert "boston" in names
    assert "seattle" in names


def test_build_environment_section_lists_default_hosts() -> None:
    section = build_environment_section()

    assert "boston" in section
    assert "10.0.0.2" in section
    assert "seattle" in section
    assert "10.0.0.187" in section
    assert "ping" in section
    assert "curl" in section


def test_build_environment_section_extends_with_extra_hosts() -> None:
    hosts = (
        HomeHost(name="boston", ip="10.0.0.2"),
        HomeHost(name="seattle", ip="10.0.0.187"),
        HomeHost(name="pi", ip="10.0.0.50", notes="raspberry pi 4"),
    )

    section = build_environment_section(hosts)

    assert "pi" in section
    assert "10.0.0.50" in section
    assert "raspberry pi 4" in section


def test_build_environment_section_handles_empty_hosts() -> None:
    section = build_environment_section(())

    assert "No known hosts" in section

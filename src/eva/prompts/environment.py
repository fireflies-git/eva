"""Home network / environment section for the system prompt."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HomeHost:
    name: str
    ip: str
    notes: str = ""


HOME_HOSTS: tuple[HomeHost, ...] = (
    HomeHost(name="boston", ip="10.0.0.2"),
    HomeHost(name="seattle", ip="10.0.0.187"),
)


def build_environment_section(hosts: tuple[HomeHost, ...] = HOME_HOSTS) -> str:
    if not hosts:
        return (
            "## Environment\n"
            "You're in a Docker container on leah's machine. No known hosts are registered."
        )

    lines = [
        "## Environment",
        "You're in a Docker container on leah's machine and can reach her home network "
        "directly. Known hosts:",
        "",
    ]
    for host in hosts:
        if host.notes:
            lines.append(f"- {host.name} — {host.ip} ({host.notes})")
        else:
            lines.append(f"- {host.name} — {host.ip}")
    lines.extend(
        [
            "",
            "You can `ping` or `curl` these by IP. If leah asks about other hosts, just "
            "try them.",
        ]
    )
    return "\n".join(lines)

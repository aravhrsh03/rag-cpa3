"""
Stage 3: Network Diagnostics ADK tools (adk-services/network_diagnostics/agent.py).

These are the three plain async, SQL-backed functions the ADK agent exposes
as tools - testable directly against a seeded database, without the agent
running as an A2A service and without any LLM call.

Skips cleanly if google-adk isn't installed yet.

    pytest tests/test_03_network_diagnostics_tools.py -v
"""
import asyncio


def test_check_tower_status_known_tower(seeded_db, network_diagnostics_module):
    result = asyncio.run(network_diagnostics_module.check_tower_status("TX-512"))
    assert "error" not in result
    assert result["tower"]["city"] == "Austin"
    assert result["latest_performance"]["tower_id"] == "TX-512"


def test_check_tower_status_unknown_tower(seeded_db, network_diagnostics_module):
    result = asyncio.run(network_diagnostics_module.check_tower_status("ZZ-999"))
    assert "error" in result


def test_connectivity_diagnostics_flags_degraded_tx512(seeded_db, network_diagnostics_module):
    # Seed scenario: TX-512 stays OPERATIONAL but its latest sample has
    # climbing packet loss and a falling 5G downlink (sql/02_seed_data.sql).
    result = asyncio.run(
        network_diagnostics_module.run_connectivity_diagnostics("TX-512", "5G sessions keep dropping")
    )
    assert any("Packet loss" in flag for flag in result["health_flags"])
    assert "NOC" in result["recommendation"]


def test_connectivity_diagnostics_flags_offline_fl090(seeded_db, network_diagnostics_module):
    # Seed scenario: FL-090 is OFFLINE with 100% packet loss on the latest
    # sample only - averaging across the week would hide the outage.
    result = asyncio.run(
        network_diagnostics_module.run_connectivity_diagnostics("FL-090", "no service at all")
    )
    assert result["tower"]["status"] == "OFFLINE"
    assert "outage" in result["recommendation"].lower()


def test_regional_summary_counts_by_status(seeded_db, network_diagnostics_module):
    result = asyncio.run(network_diagnostics_module.get_regional_network_summary("Southwest"))
    assert "error" not in result
    assert sum(result["status_counts"].values()) == len(result["towers"])


def test_regional_summary_unknown_region(seeded_db, network_diagnostics_module):
    result = asyncio.run(network_diagnostics_module.get_regional_network_summary("Antarctica"))
    assert "error" in result

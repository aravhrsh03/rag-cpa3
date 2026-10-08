"""
Network Diagnostics ADK service (A2A, port 8001).

Runs standalone:
    python adk-services/network_diagnostics/agent.py

Exposes a Google ADK Agent with three SQL-backed async tools over the A2A
protocol. LangGraph never imports this module directly - it talks to it
over HTTP via orchestration/adk_remote_client.py, once this process is
running. The agent card is published at:
    http://localhost:8001/.well-known/agent-card.json

Every tool opens its own SQLite connection through common/db.py and reads
straight from network_towers / tower_performance / open_incidents. No tower
status, metrics, or incidents are ever kept in a Python dict.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from common.db import fetch_all, fetch_one, DatabaseNotInitializedError
from config import NETWORK_DIAGNOSTICS_PORT, get_adk_model

# ---------------------------------------------------------------------------
# Diagnostic thresholds (mirrored from sql/01_schema.sql and
# data/documents/network_outage_procedures.txt so all three stay consistent)
# ---------------------------------------------------------------------------
SIGNAL_ACCEPTABLE_DBM = -90      # >= this is acceptable
SIGNAL_POOR_DBM = -110           # < this is poor; between the two is marginal
PACKET_LOSS_NORMAL_PCT = 1       # <= this is normal
PACKET_LOSS_SEVERE_PCT = 5       # > this is severe
LATENCY_NORMAL_MS_5G = 40        # <= this is normal on 5G
LATENCY_ELEVATED_MS = 50         # > this is elevated
FIVEG_DOWNLINK_DEGRADED_MBPS = 100  # 5G + OPERATIONAL + downlink below this = degraded
LTE_DOWNLINK_DEGRADED_MBPS = 10     # 4G LTE downlink below this = degraded (lower baseline than 5G)


def _latest_performance_row(tower_id: str) -> dict | None:
    return fetch_one(
        """
        SELECT * FROM tower_performance
        WHERE tower_id = ?
          AND recorded_at = (
              SELECT MAX(recorded_at) FROM tower_performance WHERE tower_id = ?
          )
        """,
        (tower_id, tower_id),
    )


def _open_incidents_for_tower(tower_id: str) -> list[dict]:
    return fetch_all(
        "SELECT * FROM open_incidents WHERE tower_id = ? ORDER BY opened_at DESC",
        (tower_id,),
    )


def _interpret_metrics(tower: dict, perf: dict | None) -> list[str]:
    """Plain-English flags derived from the latest sample, using the same
    thresholds documented in 01_schema.sql / network_outage_procedures.txt."""
    flags: list[str] = []
    if tower["status"] == "OFFLINE":
        flags.append("Site status is OFFLINE - the site itself is down; do not troubleshoot the handset.")
    if perf is None:
        flags.append("No performance samples on file for this tower.")
        return flags

    if perf["packet_loss_pct"] >= 100:
        flags.append("Packet loss is 100% on the latest sample - the site is effectively down.")
    elif perf["packet_loss_pct"] > PACKET_LOSS_SEVERE_PCT:
        flags.append(f"Packet loss is severe ({perf['packet_loss_pct']}%, > {PACKET_LOSS_SEVERE_PCT}%).")
    elif perf["packet_loss_pct"] > PACKET_LOSS_NORMAL_PCT:
        flags.append(f"Packet loss is elevated ({perf['packet_loss_pct']}%, > {PACKET_LOSS_NORMAL_PCT}%).")

    if perf["signal_strength_dbm"] < SIGNAL_POOR_DBM:
        flags.append(f"Signal strength is poor ({perf['signal_strength_dbm']} dBm, < {SIGNAL_POOR_DBM} dBm).")
    elif perf["signal_strength_dbm"] < SIGNAL_ACCEPTABLE_DBM:
        flags.append(f"Signal strength is marginal ({perf['signal_strength_dbm']} dBm).")

    if tower["technology"] == "5G" and perf["latency_ms"] > LATENCY_ELEVATED_MS:
        flags.append(f"Latency is elevated for 5G ({perf['latency_ms']} ms, > {LATENCY_ELEVATED_MS} ms).")

    if (
        tower["technology"] in ("5G", "5G mmWave")
        and tower["status"] == "OPERATIONAL"
        and perf["downlink_throughput_mbps"] < FIVEG_DOWNLINK_DEGRADED_MBPS
    ):
        flags.append(
            f"5G downlink throughput is degraded ({perf['downlink_throughput_mbps']} Mbps, "
            f"< {FIVEG_DOWNLINK_DEGRADED_MBPS} Mbps) even though the site reports OPERATIONAL."
        )
    elif (
        tower["technology"] == "4G LTE"
        and perf["downlink_throughput_mbps"] < LTE_DOWNLINK_DEGRADED_MBPS
    ):
        # 4G LTE has a lower normal baseline than 5G - don't apply the 100 Mbps test to it.
        flags.append(
            f"4G LTE downlink throughput is degraded ({perf['downlink_throughput_mbps']} Mbps, "
            f"< {LTE_DOWNLINK_DEGRADED_MBPS} Mbps)."
        )

    if not flags:
        flags.append("All latest metrics are within normal range.")
    return flags


async def check_tower_status(tower_id: str) -> dict:
    """Look up a tower's current status, technology, latest performance sample,
    and any open incident.

    Args:
        tower_id: Tower identifier, e.g. "TX-512".

    Returns:
        A dict with the tower's inventory row, its latest performance sample
        (or null if none exist), and any open incidents for that tower. Returns
        {"error": ...} if the tower_id does not exist.
    """
    def _run():
        tower = fetch_one("SELECT * FROM network_towers WHERE tower_id = ?", (tower_id,))
        if tower is None:
            return {"error": f"No tower found with tower_id '{tower_id}'."}
        perf = _latest_performance_row(tower_id)
        incidents = _open_incidents_for_tower(tower_id)
        return {
            "tower": tower,
            "latest_performance": perf,
            "open_incidents": incidents,
        }

    try:
        return await asyncio.to_thread(_run)
    except DatabaseNotInitializedError as exc:
        return {"error": str(exc)}


async def run_connectivity_diagnostics(tower_id: str, symptom: str) -> dict:
    """Run a connectivity diagnostic for a tower given a reported symptom
    (e.g. "5G keeps dropping", "slow indoors"), using the latest SQL
    performance sample and applying the documented health thresholds.

    Args:
        tower_id: Tower identifier, e.g. "TX-512".
        symptom: The customer- or NOC-reported symptom in plain text.

    Returns:
        A dict with the tower/performance facts, a list of interpreted
        health flags, and a recommendation string. Returns {"error": ...}
        if the tower_id does not exist.
    """
    def _run():
        tower = fetch_one("SELECT * FROM network_towers WHERE tower_id = ?", (tower_id,))
        if tower is None:
            return {"error": f"No tower found with tower_id '{tower_id}'."}
        perf = _latest_performance_row(tower_id)
        incidents = _open_incidents_for_tower(tower_id)
        flags = _interpret_metrics(tower, perf)

        if tower["status"] == "OFFLINE" or (perf and perf["packet_loss_pct"] >= 100):
            recommendation = (
                "Site outage, not a handset issue. Dispatch/track the open incident "
                "for this tower; advise the customer this is a known site-level problem."
            )
        elif incidents:
            recommendation = (
                "An open NOC incident already covers this symptom. Reference the "
                "incident in the customer response and avoid duplicate ticketing."
            )
        elif len(flags) == 1 and flags[0].startswith("All latest metrics"):
            recommendation = (
                "Latest sample is healthy. If the symptom persists, advise a handset "
                "restart / airplane-mode toggle and confirm the device is 5G-compatible; "
                "otherwise no site-side action is needed."
            )
        else:
            recommendation = (
                "Degraded performance detected on the latest sample. Open or update a "
                "NOC incident for this tower and set customer expectations for a "
                "field/engineering follow-up rather than a handset fix."
            )

        return {
            "tower": tower,
            "latest_performance": perf,
            "open_incidents": incidents,
            "reported_symptom": symptom,
            "health_flags": flags,
            "recommendation": recommendation,
        }

    try:
        return await asyncio.to_thread(_run)
    except DatabaseNotInitializedError as exc:
        return {"error": str(exc)}


async def get_regional_network_summary(region: str) -> dict:
    """Aggregate tower health for a region from SQL.

    Args:
        region: One of "Midwest", "Northeast", "Southeast", "Southwest", "West".

    Returns:
        A dict with the towers in the region (with status), counts of towers
        by status, and the number of open incidents affecting that region's
        towers. Returns {"error": ...} if the region has no towers on file.
    """
    def _run():
        towers = fetch_all(
            "SELECT tower_id, tower_name, city, technology, status FROM network_towers "
            "WHERE region = ? ORDER BY tower_id",
            (region,),
        )
        if not towers:
            return {"error": f"No towers found for region '{region}'."}

        status_counts: dict[str, int] = {}
        for t in towers:
            status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1

        incidents = fetch_all(
            """
            SELECT oi.* FROM open_incidents oi
            JOIN network_towers t ON t.tower_id = oi.tower_id
            WHERE t.region = ?
            ORDER BY oi.opened_at DESC
            """,
            (region,),
        )

        return {
            "region": region,
            "towers": towers,
            "status_counts": status_counts,
            "open_incidents": incidents,
        }

    try:
        return await asyncio.to_thread(_run)
    except DatabaseNotInitializedError as exc:
        return {"error": str(exc)}


root_agent = Agent(
    name="network_diagnostics_agent",
    model=get_adk_model(),
    description=(
        "Network Operations Center (NOC) specialist. Diagnoses live tower and "
        "connectivity issues using SQL-backed tools over network_towers, "
        "tower_performance, and open_incidents."
    ),
    instruction=(
        "You are Prodapt's Network Diagnostics specialist. You support NOC "
        "staff and, indirectly, customer-facing agents by diagnosing live "
        "tower and connectivity problems.\n\n"
        "Rules:\n"
        "- Always call a tool to get real data before answering. Never guess "
        "tower status, signal strength, or incident state.\n"
        "- Use check_tower_status for a quick lookup, run_connectivity_diagnostics "
        "when a symptom is described (e.g. drops, slow speeds), and "
        "get_regional_network_summary for region-wide questions.\n"
        "- Diagnostics must be based on the LATEST recorded_at performance "
        "sample only, never an average of the week's samples.\n"
        "- If a tool returns an error (e.g. unknown tower_id or region), say so "
        "plainly instead of inventing data.\n"
        "- Write your findings as a concise technical summary (tower status, "
        "key metrics, open incidents, recommendation). Do not write a "
        "customer-facing letter - that is handled by a separate communications "
        "specialist downstream."
    ),
    tools=[check_tower_status, run_connectivity_diagnostics, get_regional_network_summary],
)

a2a_app = to_a2a(root_agent, port=NETWORK_DIAGNOSTICS_PORT)

if __name__ == "__main__":
    import uvicorn

    print(f"Starting Network Diagnostics ADK service on port {NETWORK_DIAGNOSTICS_PORT} ...")
    print(f"Agent card: http://localhost:{NETWORK_DIAGNOSTICS_PORT}/.well-known/agent-card.json")
    uvicorn.run(a2a_app, host="0.0.0.0", port=NETWORK_DIAGNOSTICS_PORT)

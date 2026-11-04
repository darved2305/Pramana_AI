"""Golden behaviour of the site physics for each fault category."""

from __future__ import annotations

import pytest

from pramana_domain import DomainPack, World, load_pack, predict


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return load_pack("campus_block_c")


def obs(pack: DomainPack, faults: list[tuple[str, str]], probe: str, loc: str) -> str:
    return World(pack, frozenset(faults)).observe(pack.probe_by_id[probe], loc)


def test_healthy_building_everything_works(pack: DomainPack) -> None:
    table = predict(pack, [])
    for (probe, loc), value in table.items():
        assert value in {"yes", "connected", "on", "green", "up"}, (probe, loc, value)


def test_upstream_power_loss_darkens_floors_2_and_3_only(pack: DomainPack) -> None:
    f = [("FEED_C2", "lost")]
    assert obs(pack, f, "corridor_lights", "F3_R304") == "off"
    assert obs(pack, f, "corridor_lights", "F2_R205") == "off"
    assert obs(pack, f, "corridor_lights", "F1_LOBBY") == "on"
    assert obs(pack, f, "closet_light", "IDF2") == "off"
    assert obs(pack, f, "nvr_screen", "IDF2") == "off"
    assert obs(pack, f, "wifi_status", "F3_R304") == "no_network"
    assert obs(pack, f, "wifi_status", "F1_LOBBY") == "connected"
    # The breaker itself did not trip: power is missing upstream of it.
    assert obs(pack, f, "breaker_c2_7", "DB_C2_PANEL") == "up"


def test_breaker_trip_cuts_only_its_own_circuit(pack: DomainPack) -> None:
    f = [("CB_C2_7", "tripped")]
    assert obs(pack, f, "breaker_c2_7", "DB_C2_PANEL") == "tripped"
    assert obs(pack, f, "nvr_screen", "IDF2") == "off"  # shares the circuit with SW_C2
    assert obs(pack, f, "switch_leds", "IDF2") == "off"
    assert obs(pack, f, "closet_light", "IDF2") == "on"  # lighting is on breaker C2-5
    assert obs(pack, f, "corridor_lights", "F3_R304") == "on"
    assert obs(pack, f, "wifi_status", "F3_R304") == "no_network"
    assert obs(pack, f, "wifi_status", "F1_LOBBY") == "connected"


def test_switch_failure_affects_only_its_dependants(pack: DomainPack) -> None:
    f = [("SW_C2", "dead")]
    assert obs(pack, f, "switch_leds", "IDF2") == "off"
    assert obs(pack, f, "nvr_screen", "IDF2") == "on"  # the closet still has power
    for ap_loc in ("F2_CORRIDOR", "F2_R205", "F3_CORRIDOR", "F3_R310"):
        assert obs(pack, f, "ap_light", ap_loc) == "off"  # PoE comes from SW_C2
    assert obs(pack, f, "ap_light", "F1_LOBBY") == "on"
    assert obs(pack, f, "wifi_status", "F2_R210") == "no_network"
    assert obs(pack, f, "internet_works", "GUARD_DESK") == "yes"


def test_access_point_failure_is_local_and_masked_by_overlapping_coverage(pack: DomainPack) -> None:
    f = [("AP_3B", "dead")]
    assert obs(pack, f, "ap_light", "F3_R310") == "off"
    assert obs(pack, f, "wifi_status", "F3_R310") == "no_network"  # only AP_3B covers 310
    assert obs(pack, f, "wifi_status", "F3_R304") == "connected"  # 304 falls back to AP_3A
    assert obs(pack, f, "internet_works", "F2_R205") == "yes"
    assert obs(pack, f, "corridor_lights", "F3_R310") == "on"


def test_dns_failure_breaks_names_but_not_ip_or_wifi(pack: DomainPack) -> None:
    f = [("DNS", "down")]
    for loc in ("F3_R304", "F1_LOBBY", "F2_R210"):
        assert obs(pack, f, "wifi_status", loc) == "connected"
        assert obs(pack, f, "internet_works", loc) == "no"
        assert obs(pack, f, "web_by_ip", loc) == "yes"
    assert obs(pack, f, "wan_led", "IDF1") == "green"


def test_isp_outage_breaks_ip_too_and_turns_wan_led_red(pack: DomainPack) -> None:
    f = [("ISP_LINK", "down")]
    assert obs(pack, f, "wifi_status", "F3_R304") == "connected"
    assert obs(pack, f, "web_by_ip", "F3_R304") == "no"
    assert obs(pack, f, "internet_works", "F3_R304") == "no"
    assert obs(pack, f, "wan_led", "IDF1") == "red"
    assert obs(pack, f, "switch_leds", "IDF2") == "green"


def test_dhcp_failure_leaves_ssid_visible_but_stuck(pack: DomainPack) -> None:
    f = [("DHCP", "down")]
    for loc in ("F3_R304", "F1_LOBBY"):
        assert obs(pack, f, "wifi_status", loc) == "stuck_connecting"
        assert obs(pack, f, "web_by_ip", loc) == "no"
    assert obs(pack, f, "ap_light", "F3_CORRIDOR") == "on"
    assert obs(pack, f, "wan_led", "IDF1") == "green"


def test_core_failure_makes_floor_switch_amber(pack: DomainPack) -> None:
    f = [("SW_CORE", "dead")]
    assert obs(pack, f, "switch_leds", "IDF2") == "amber"  # alive, but no path upstream
    assert obs(pack, f, "switch_leds", "IDF1") == "off"
    assert obs(pack, f, "wifi_status", "F1_LOBBY") == "no_network"  # AP_1A had PoE from core
    assert obs(pack, f, "wifi_status", "F3_R304") == "stuck_connecting"


def test_every_single_fault_has_a_distinct_signature(pack: DomainPack) -> None:
    """Identifiability check: no two modelled faults predict identical observations."""
    signatures: dict[tuple[tuple[tuple[str, str], str], ...], str] = {}
    for cid, mode, _ in pack.fault_hypotheses():
        sig = tuple(sorted(predict(pack, [(cid, mode)]).items()))
        assert sig not in signatures, f"{cid}.{mode} indistinguishable from {signatures.get(sig)}"
        signatures[sig] = f"{cid}.{mode}"
    assert tuple(sorted(predict(pack, []).items())) not in signatures


def test_multiple_faults_compose(pack: DomainPack) -> None:
    f = [("ISP_LINK", "down"), ("AP_3B", "dead")]
    assert obs(pack, f, "wifi_status", "F3_R310") == "no_network"
    assert obs(pack, f, "web_by_ip", "F3_R304") == "no"


def test_prediction_is_deterministic(pack: DomainPack) -> None:
    assert predict(pack, [("SW_C2", "dead")]) == predict(pack, [("SW_C2", "dead")])


def test_unknown_fault_is_rejected(pack: DomainPack) -> None:
    with pytest.raises(ValueError, match="unknown fault"):
        World(pack, frozenset({("SW_C2", "melted")}))


def test_probe_at_unbound_location_is_rejected(pack: DomainPack) -> None:
    with pytest.raises(ValueError, match="cannot be made"):
        World(pack, frozenset()).observe(pack.probe_by_id["nvr_screen"], "F3_R304")

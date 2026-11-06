"""Deterministic site physics: from a set of active faults to what a person would perceive.

Propagation order (each layer depends only on earlier layers):

1. power: feeds -> breakers -> loads; switches deliver PoE power to access points;
2. device health: a component with any active failure mode does not function;
3. layer-2 reachability: a switch reaches the gateway through its uplink chain;
4. services: DHCP and DNS run on the gateway; the internet needs the gateway and the ISP link;
5. per-location phone experience: SSID visibility, association, IP lease, page loads;
6. indicators: lights, screens, LEDs and breaker positions.

The engine evaluates this on the *documented* pack once per hypothesis to build its prediction
table. The simulator evaluates it on its sealed *true* fault set (which may contain several
faults) to decide what participants perceive. Neither side can see the other's inputs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .pack import DEVICE_KINDS, DomainPack, Probe

FaultSet = frozenset[tuple[str, str]]
"""Active faults as ``(component_id, failure_mode_id)`` pairs."""


@dataclass
class World:
    pack: DomainPack
    faults: FaultSet
    _memo: dict[tuple[str, str], bool] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        comps = self.pack.component_by_id
        for cid, mode in self.faults:
            comp = comps.get(cid)
            if comp is None or mode not in {m.id for m in comp.failure_modes}:
                raise ValueError(f"unknown fault {cid}.{mode}")

    # -- layer 1-2: power and health ---------------------------------------------------------

    def functioning(self, cid: str) -> bool:
        return not any(c == cid for c, _ in self.faults)

    def powered(self, cid: str) -> bool:
        """True when electrical (or PoE) power reaches the component."""
        key = ("powered", cid)
        if key not in self._memo:
            c = self.pack.component_by_id[cid]
            if c.poe_from is not None:
                value = self.alive(c.poe_from)
            elif c.powered_by is not None:
                parent = self.pack.component_by_id[c.powered_by]
                # A feed or breaker passes power only while it functions (not lost/tripped).
                value = self.powered(parent.id) and self.functioning(parent.id)
            elif c.hosted_on is not None:
                value = self.alive(c.hosted_on)
            else:
                value = True  # root feed or external link
            self._memo[key] = value
        return self._memo[key]

    def alive(self, cid: str) -> bool:
        return self.powered(cid) and self.functioning(cid)

    # -- layer 3-4: network --------------------------------------------------------------------

    def reaches_gateway(self, switch_id: str) -> bool:
        key = ("l2", switch_id)
        if key not in self._memo:
            sw = self.pack.component_by_id[switch_id]
            if not self.alive(switch_id) or sw.uplink is None:
                value = False
            else:
                up = self.pack.component_by_id[sw.uplink]
                value = self.alive(up.id) if up.kind == "gateway" else self.reaches_gateway(up.id)
            self._memo[key] = value
        return self._memo[key]

    def _gateway(self) -> str:
        return next(c.id for c in self.pack.components if c.kind == "gateway")

    def _service(self, kind: str) -> str:
        return next(c.id for c in self.pack.components if c.kind == kind)

    def internet_route(self) -> bool:
        gw = self.pack.component_by_id[self._gateway()]
        isp_ok = gw.upstream is None or self.functioning(gw.upstream)
        return self.alive(gw.id) and isp_ok

    def dhcp_ok(self) -> bool:
        return self.alive(self._service("dhcp"))

    def dns_ok(self) -> bool:
        # Names on the public internet need both the resolver and an upstream route.
        return self.alive(self._service("dns")) and self.internet_route()

    def broadcasting(self, ap_id: str) -> bool:
        return self.alive(ap_id)

    # -- layer 5: phone at a location --------------------------------------------------------

    def associated_ap(self, location_id: str) -> str | None:
        """Phones join the strongest access point that is broadcasting (coverage order)."""
        loc = self.pack.location_by_id[location_id]
        return next((ap for ap in loc.wifi_coverage if self.broadcasting(ap)), None)

    def phone_connected(self, location_id: str) -> bool:
        ap = self.associated_ap(location_id)
        if ap is None:
            return False
        poe_switch = self.pack.component_by_id[ap].poe_from
        assert poe_switch is not None
        return self.reaches_gateway(poe_switch) and self.dhcp_ok()

    # -- layer 6: observables ----------------------------------------------------------------

    def observe(self, probe: Probe, location_id: str) -> str:
        """The true outcome of ``probe`` at ``location_id`` in this world (noise-free)."""
        binding = probe.binding_at(location_id)
        if binding is None:
            raise ValueError(f"probe {probe.id} cannot be made at {location_id}")
        kind = probe.kind
        if kind in DEVICE_KINDS:
            if kind == "wifi_access_point":
                return self.associated_ap(location_id) or "not_connected"
            if kind == "wifi_status":
                if self.associated_ap(location_id) is None:
                    return "no_network"
                return "connected" if self.phone_connected(location_id) else "stuck_connecting"
            connected = self.phone_connected(location_id)
            if kind == "web_by_ip":
                return "yes" if connected and self.internet_route() else "no"
            return "yes" if connected and self.dns_ok() else "no"  # internet_works
        target = binding.target
        assert target is not None
        if kind == "powered":
            return "on" if self.alive(target) else "off"
        if kind == "ap_light":
            return "on" if self.broadcasting(target) else "off"
        if kind == "switch_leds":
            if not self.alive(target):
                return "off"
            return "green" if self.reaches_gateway(target) else "amber"
        if kind == "wan_led":
            if not self.alive(target):
                return "off"
            upstream = self.pack.component_by_id[target].upstream
            return "green" if upstream is None or self.functioning(upstream) else "red"
        if kind == "fibre_led":
            # The fibre terminal's optical light: dark without power, red on loss of signal
            # from the provider, green when the link is up.
            if not self.alive(target):
                return "off"
            upstream = self.pack.component_by_id[target].upstream
            return "green" if upstream is None or self.functioning(upstream) else "red"
        if kind == "breaker":
            return "tripped" if (target, "tripped") in self.faults else "up"
        raise AssertionError(f"unhandled observable kind {kind}")


def observation_sites(pack: DomainPack) -> list[tuple[str, str]]:
    """Every (probe_id, location_id) pair the pack allows, in a stable order."""
    return [(p.id, b.at) for p in pack.probes for b in p.observes]


def predict(pack: DomainPack, faults: Iterable[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Noise-free outcome of every observation site under a fault set."""
    world = World(pack, frozenset(faults))
    return {
        (pid, loc): world.observe(pack.probe_by_id[pid], loc)
        for pid, loc in observation_sites(pack)
    }

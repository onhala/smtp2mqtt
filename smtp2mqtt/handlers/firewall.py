import ipaddress
import logging
from typing import List, Union

log = logging.getLogger("smtp2mqtt.firewall")


class IPFirewall:
    """Manages IP Whitelisting and CIDR range validation for incoming camera SMTP connections."""

    def __init__(self, allowed_ips_str: str = "*"):
        self.allowed_networks: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
        self.allow_all = False
        self.update_rules(allowed_ips_str)

    def update_rules(self, allowed_ips_str: str) -> None:
        """Parses and updates the active IP firewall whitelist rules."""
        self.allowed_networks.clear()
        raw = (allowed_ips_str or "").strip()

        if not raw or raw == "*":
            self.allow_all = True
            log.info("IP Firewall initialized in ALLOW-ALL mode (*)")
            return

        self.allow_all = False
        tokens = [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]

        for token in tokens:
            if token == "*":
                self.allow_all = True
                break
            try:
                if "/" not in token:
                    token += "/32"
                net = ipaddress.ip_network(token, strict=False)
                self.allowed_networks.append(net)
            except ValueError as err:
                log.warning("Invalid IP firewall rule '%s' ignored: %s", token, err)

    def is_allowed(self, client_ip: str) -> bool:
        """Checks if a client IP address is allowed to connect."""
        if self.allow_all:
            return True
        if not client_ip:
            return False

        try:
            ip_obj = ipaddress.ip_address(client_ip)
            for net in self.allowed_networks:
                if ip_obj in net:
                    return True
        except ValueError:
            pass

        return False

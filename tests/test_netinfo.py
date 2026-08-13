"""Adrese za telefon.

Ovo je ekran koji korisnik gleda kad mu telefon nece da otvori aplikaciju, pa
mora da bude tacan: bez loopback-a, bez link-local-a, i sa naznakom kad adresa
skoro sigurno nije njegov Wi-Fi.
"""

from app import netinfo

from .base import AppTestCase


class AddressHintTests(AppTestCase):
    def test_virtualbox_range_is_marked(self):
        self.assertIn("VirtualBox", netinfo.address_hint("192.168.56.1"))

    def test_docker_and_wsl_range_is_marked(self):
        self.assertIn("WSL", netinfo.address_hint("172.17.0.1"))
        self.assertIn("WSL", netinfo.address_hint("172.31.255.1"))

    def test_ordinary_home_network_is_not_marked(self):
        for address in ("192.168.1.12", "192.168.0.100", "10.0.0.5", "172.32.0.1"):
            self.assertEqual(netinfo.address_hint(address), "", address)

    def test_malformed_address_does_not_raise(self):
        self.assertEqual(netinfo.address_hint("172."), "")
        self.assertEqual(netinfo.address_hint("172.abc.0.1"), "")


class AddressListTests(AppTestCase):
    def test_loopback_and_link_local_are_excluded(self):
        for item in netinfo.lan_addresses():
            self.assertFalse(item["ip"].startswith("127."), item["ip"])
            self.assertFalse(item["ip"].startswith("169.254."), item["ip"])

    def test_addresses_are_unique(self):
        found = [item["ip"] for item in netinfo.lan_addresses()]
        self.assertEqual(len(found), len(set(found)))

    def test_at_most_one_primary(self):
        primaries = [item for item in netinfo.lan_addresses() if item["primary"]]
        self.assertLessEqual(len(primaries), 1)


class InfoTests(AppTestCase):
    def test_without_running_port_it_says_so(self):
        original = netinfo.RUNNING_PORT
        netinfo.RUNNING_PORT = None
        try:
            payload = netinfo.info()
            self.assertFalse(payload["ready"])
            self.assertEqual(payload["addresses"], [])
        finally:
            netinfo.RUNNING_PORT = original

    def test_with_port_every_address_carries_a_url(self):
        payload = netinfo.info(8077)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["local_url"], "http://localhost:8077")
        for item in payload["addresses"]:
            self.assertEqual(item["url"], f"http://{item['ip']}:8077")
        if payload["addresses"]:
            self.assertTrue(payload["phone_url"].endswith(":8077"))
            self.assertNotIn("localhost", payload["phone_url"])

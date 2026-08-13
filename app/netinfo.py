"""Pod kojim adresama je aplikacija dostupna.

Zaseban modul, bez ijedne zavisnosti unutar projekta, jer ga koriste i server i
API rute. Da stoji u server.py, uvoz bi isao u krug: server -> api -> meta ->
server.
"""

import socket

# Port na kom server stvarno slusa. Postavlja ga `server.build()`; do tada je
# None, pa UI zna da prikaze "server jos nije podignut" umesto pogresnog broja.
RUNNING_PORT: int | None = None


def lan_address() -> str:
    """Najverovatniji IP koji telefon na istom Wi-Fi-ju moze da otvori."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Ne salje nijedan bajt - samo tera kernel da izabere izlazni interfejs.
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def lan_addresses() -> list[dict]:
    """Sve adrese pod kojima je aplikacija dostupna, najverovatnija prva.

    Jedna adresa nije dovoljna: masina obicno ima i Wi-Fi i Ethernet, a
    VirtualBox, WSL i VPN dodaju svoje. Trik sa UDP soketom vrati samo jednu i
    ume da promasi, pa se ovde nudi ceo spisak sa naznakom sta je sta.
    """
    primary = lan_address()
    found: dict[str, dict] = {}

    def add(address: str) -> None:
        if not address or address in found:
            return
        if address.startswith(("127.", "169.254.")):
            return
        found[address] = {
            "ip": address,
            "primary": address == primary,
            "hint": address_hint(address),
        }

    add(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass

    return sorted(
        found.values(),
        key=lambda item: (not item["primary"], item["hint"] != "", item["ip"]),
    )


def address_hint(address: str) -> str:
    """Adrese koje skoro sigurno NISU tvoj Wi-Fi - da se ne kuca pogresna."""
    if address.startswith("192.168.56."):
        return "verovatno VirtualBox"
    if address.startswith("172."):
        try:
            second = int(address.split(".")[1])
        except (IndexError, ValueError):
            return ""
        if 16 <= second <= 31:
            return "verovatno WSL ili Docker"
        return ""
    if address.startswith("10.") and not address.startswith("10.0.0."):
        return "verovatno VPN ili poslovna mreža"
    return ""


def info(port: int | None = None) -> dict:
    """Sve sto UI treba da prikaze za 'otvori na telefonu'."""
    port = port or RUNNING_PORT
    addresses = lan_addresses()
    if not port:
        return {"ready": False, "port": None, "addresses": [], "local_url": "", "phone_url": ""}

    return {
        "ready": True,
        "port": port,
        "hostname": socket.gethostname(),
        "local_url": f"http://localhost:{port}",
        "phone_url": f"http://{addresses[0]['ip']}:{port}" if addresses else "",
        "addresses": [{**item, "url": f"http://{item['ip']}:{port}"} for item in addresses],
    }

from ipaddress import ip_address, ip_network

from fastapi import Request

from app.config import Settings, get_settings

def _parse_ip_candidate(value: str | None) -> str | None:
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    try:
        ip_address(candidate)
    except ValueError:
        return None

    return candidate

def _parse_forwarded_for(value: str | None) -> str | None:
    if not value:
        return None

    first_hop = value.split(",")[0].strip()

    return _parse_ip_candidate(first_hop)

def _is_trusted_proxy(client_host: str | None, settings: Settings) -> bool:
    if not settings.trust_proxy_headers or not client_host:
        return False

    try:
        client_ip = ip_address(client_host)
    except ValueError:
        return False

    for entry in settings.trusted_proxy_ips:
        try:
            if "/" in entry and client_ip in ip_network(entry, strict=False):
                return True
        except ValueError:
            continue

        if entry == client_host:
            return True

    return False

def get_client_ip(request: Request, settings: Settings | None = None) -> str:
    current_settings = settings or get_settings()
    direct_client_host = request.client.host if request.client else None

    if _is_trusted_proxy(direct_client_host, current_settings):
        forwarded_ip = _parse_forwarded_for(request.headers.get("x-forwarded-for"))
        if forwarded_ip:
            return forwarded_ip

        real_ip = _parse_ip_candidate(request.headers.get("x-real-ip"))
        if real_ip:
            return real_ip

    if direct_client_host:
        return direct_client_host

    return "unknown"


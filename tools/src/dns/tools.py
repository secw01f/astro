from __future__ import annotations

from collections import Counter
from typing import Any

import dns.exception
import dns.name
import dns.query
import dns.rdatatype
import dns.resolver
import dns.zone
from pydantic import BaseModel, Field

from lib.tool import create_tool_registry

Registry, tool = create_tool_registry("dns")

def _resolver(nameservers: list[str] | None, lifetime: float) -> dns.resolver.Resolver:
    r = dns.resolver.Resolver()
    r.lifetime = lifetime
    if nameservers:
        r.nameservers = nameservers
    return r

def _answer_to_records(answer: dns.resolver.Answer) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rrset = answer.rrset
    if rrset is None:
        return out
    name = answer.qname.to_text(omit_final_dot=True)
    ttl = rrset.ttl
    rdtype = dns.rdatatype.to_text(rrset.rdtype)
    for rdata in rrset:
        out.append(
            {
                "name": name,
                "ttl": ttl,
                "type": rdtype,
                "data": rdata.to_text(),
            }
        )
    return out

def _safe_resolve(
    resolver: dns.resolver.Resolver,
    qname: str,
    rdtype: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        rdt = dns.rdatatype.from_text(rdtype)
    except dns.rdatatype.UnknownRdatatype as e:
        return None, f"Unknown record type: {e}"
    try:
        ans = resolver.resolve(qname, rdt)
        return _answer_to_records(ans), None
    except dns.resolver.NXDOMAIN:
        return [], "NXDOMAIN"
    except dns.resolver.NoAnswer:
        return [], "NoAnswer"
    except dns.resolver.NoNameservers as e:
        return None, f"NoNameservers: {e}"
    except dns.exception.Timeout:
        return None, "Timeout"
    except Exception as e:
        return None, str(e)

class DNSLookupInput(BaseModel):
    domain: str = Field(description="Query name (FQDN or zone apex)")
    record_type: str = Field(default="A", description="RR type, e.g. A, AAAA, MX, NS, TXT, SOA, CNAME, CAA, DNSKEY, DS")
    nameservers: list[str] | None = Field(default=None, description="Optional resolver IPs; default is system resolver")
    lifetime: float = Field(default=10.0, ge=1.0, le=60.0)

@tool(name="dns_lookup", description="Resolve a DNS record type for a name (A, MX, TXT, CAA, DNSKEY, etc.)", capabilities=["dns_lookup"], version="1.0")
async def dns_lookup(input: DNSLookupInput) -> dict:
    r = _resolver(input.nameservers, input.lifetime)
    records, err = _safe_resolve(r, input.domain, input.record_type.upper())
    return {
        "domain": input.domain,
        "record_type": input.record_type.upper(),
        "records": records if records is not None else [],
        "error": err,
    }

class DNSEmailAuthInput(BaseModel):
    domain: str = Field(description="Mail domain / organizational domain (apex)")
    dkim_selector: str | None = Field(
        default=None,
        description="If set, query {selector}._domainkey.{domain} TXT for DKIM",
    )
    nameservers: list[str] | None = None
    lifetime: float = Field(default=10.0, ge=1.0, le=60.0)

def _txt_join(records: list[dict[str, Any]]) -> list[str]:
    """Flatten TXT rdata strings for policy parsing."""
    texts: list[str] = []
    for rec in records:
        texts.append(rec["data"].strip('"').replace('" "', ""))
    return texts

@tool(name="dns_email_auth", description="Fetch SPF, DMARC, and optional DKIM TXT for email authentication posture", capabilities=["dns_lookup", "email_security"], version="1.0")
async def dns_email_auth(input: DNSEmailAuthInput) -> dict:
    r = _resolver(input.nameservers, input.lifetime)
    apex = input.domain.strip().rstrip(".")

    spf_records, spf_err = _safe_resolve(r, apex, "TXT")
    spf_txt: list[str] = []
    spf_found: list[str] = []
    if spf_records is not None:
        for t in _txt_join(spf_records):
            if t.lower().startswith("v=spf1"):
                spf_found.append(t)

    dmarc_name = f"_dmarc.{apex}"
    dmarc_records, dmarc_err = _safe_resolve(r, dmarc_name, "TXT")
    dmarc_found: list[str] = []
    if dmarc_records is not None:
        for t in _txt_join(dmarc_records):
            if t.lower().startswith("v=dmarc1"):
                dmarc_found.append(t)

    dkim: dict[str, Any] | None = None
    if input.dkim_selector:
        dkim_name = f"{input.dkim_selector}._domainkey.{apex}"
        dkim_rr, dkim_err = _safe_resolve(r, dkim_name, "TXT")
        dkim_txt = _txt_join(dkim_rr or [])
        dkim = {
            "name": dkim_name,
            "records": dkim_rr or [],
            "dkim_txt": dkim_txt,
            "error": dkim_err,
        }

    return {
        "domain": apex,
        "spf": {
            "present": bool(spf_found),
            "records": spf_found,
            "error": spf_err,
            "note": "Multiple SPF TXT at apex is invalid per RFC 7208.",
        },
        "dmarc": {
            "name": dmarc_name,
            "present": bool(dmarc_found),
            "records": dmarc_found,
            "error": dmarc_err,
        },
        "dkim": dkim,
    }

class DNSTlsPolicyInput(BaseModel):
    domain: str
    nameservers: list[str] | None = None
    lifetime: float = Field(default=10.0, ge=1.0, le=60.0)

@tool(name="dns_tls_policy", description="CAA records: which CAs may issue certificates for this hostname/zone", capabilities=["dns_lookup", "tls_policy"], version="1.0")
async def dns_tls_policy(input: DNSTlsPolicyInput) -> dict:
    r = _resolver(input.nameservers, input.lifetime)
    apex = input.domain.strip().rstrip(".")
    records, err = _safe_resolve(r, apex, "CAA")
    parsed: list[dict[str, str]] = []
    if records:
        for rec in records:
            parts = rec["data"].split(None, 3)
            if len(parts) >= 3 and parts[0] in ("0", "128"):
                flag, tag, value = parts[0], parts[1], parts[2]
                if len(parts) > 3:
                    value = parts[2] + " " + parts[3]
                parsed.append({"flags": flag, "tag": tag, "value": value.strip('"')})
    return {"domain": apex, "caa": records or [], "parsed": parsed, "error": err}

class DNSDnssecProbeInput(BaseModel):
    domain: str = Field(description="Zone apex to probe (e.g. example.com)")
    nameservers: list[str] | None = None
    lifetime: float = Field(default=15.0, ge=1.0, le=60.0)

@tool(name="dns_dnssec_probe", description="Surface DNSKEY, DS, and RRSIG presence for DNSSEC visibility (not full chain validation)", capabilities=["dns_lookup", "dnssec"], version="1.0")
async def dns_dnssec_probe(input: DNSDnssecProbeInput) -> dict:
    r = _resolver(input.nameservers, input.lifetime)
    apex = input.domain.strip().rstrip(".")

    dnskey, dnskey_err = _safe_resolve(r, apex, "DNSKEY")
    ds, ds_err = _safe_resolve(r, apex, "DS")

    rrsig_on_a: list[dict[str, Any]] | None = None
    rrsig_err: str | None = None
    try:
        ans = r.resolve(apex, dns.rdatatype.A, raise_on_no_answer=False)
        if ans.rrset and ans.response:
            for rrset in ans.response.answer:
                if rrset.rdtype != dns.rdatatype.RRSIG:
                    continue
                rrsig_on_a = [
                    {
                        "name": rrset.name.to_text(omit_final_dot=True),
                        "ttl": rrset.ttl,
                        "type": "RRSIG",
                        "data": rdata.to_text(),
                    }
                    for rdata in rrset
                ]
                break
    except Exception as e:
        rrsig_err = str(e)

    return {
        "domain": apex,
        "dnskey": {"records": dnskey or [], "error": dnskey_err},
        "ds": {"records": ds or [], "error": ds_err},
        "rrsig_sample": rrsig_on_a or [],
        "rrsig_note": rrsig_err or "RRSIGs may be absent in stub resolver answers; use validating resolver for AD flag checks.",
        "summary": {
            "has_dnskey": bool(dnskey),
            "has_ds": bool(ds),
            "likely_signed_zone": bool(dnskey) or bool(ds),
        },
    }

class DNSAxfrProbeInput(BaseModel):
    zone: str = Field(description="Zone name (apex), e.g. example.com")
    nameserver: str = Field(description="Authoritative server host or IP to query")
    max_names: int = Field(default=200, ge=1, le=5000, description="Cap enumerated names returned")
    lifetime: float = Field(default=30.0, ge=5.0, le=120.0)

@tool(name="dns_axfr_probe", description="Attempt a zone transfer (AXFR) against a nameserver — common misconfiguration check; only use on assets you are authorized to test", capabilities=["dns_zone_transfer", "dns_recon"], version="1.0")
async def dns_axfr_probe(input: DNSAxfrProbeInput) -> dict:
    origin = dns.name.from_text(input.zone)
    try:
        xfr = dns.query.xfr(input.nameserver, origin, lifetime=input.lifetime)
        z = dns.zone.from_xfr(xfr, origin=origin, relativize=False)
    except dns.exception.FormError as e:
        return {"zone": input.zone, "nameserver": input.nameserver, "axfr_allowed": False, "error": f"FormError: {e}"}
    except OSError as e:
        return {"zone": input.zone, "nameserver": input.nameserver, "axfr_allowed": False, "error": str(e)}
    except Exception as e:
        return {"zone": input.zone, "nameserver": input.nameserver, "axfr_allowed": False, "error": str(e)}

    names = list(z.nodes.keys())
    type_counts: Counter[str] = Counter()
    sample_names: list[str] = []
    for i, node in enumerate(sorted(names, key=lambda n: str(n))):
        if i >= input.max_names:
            break
        sample_names.append(node.to_text(omit_final_dot=True))
    for node in z.nodes.values():
        rdatasets = getattr(node, "rdatasets", None)
        if not rdatasets:
            continue
        for rds in rdatasets:
            type_counts[dns.rdatatype.to_text(rds.rdtype)] += len(rds)

    return {
        "zone": input.zone,
        "nameserver": input.nameserver,
        "axfr_allowed": True,
        "node_count": len(names),
        "rdtype_counts": dict(type_counts),
        "sample_names": sample_names,
        "truncated": len(names) > input.max_names,
    }

class DNSDelegationInput(BaseModel):
    domain: str = Field(description="Child zone / hostname whose delegation you want to inspect")
    nameservers: list[str] | None = None
    lifetime: float = Field(default=10.0, ge=1.0, le=60.0)
    
@tool(name="dns_delegation", description="NS and glue-style A/AAAA for the zone apex — delegation and lame-NS hints", capabilities=["dns_lookup", "dns_delegation"], version="1.0")
async def dns_delegation(input: DNSDelegationInput) -> dict:
    r = _resolver(input.nameservers, input.lifetime)
    apex = input.domain.strip().rstrip(".")
    ns_records, ns_err = _safe_resolve(r, apex, "NS")
    ns_targets: list[str] = []
    if ns_records:
        for rec in ns_records:
            host = rec["data"].rstrip(".").lower()
            ns_targets.append(host)

    glue: dict[str, dict[str, Any]] = {}
    for host in ns_targets:
        a, ae = _safe_resolve(r, host, "A")
        aaaa, aaae = _safe_resolve(r, host, "AAAA")
        glue[host] = {
            "A": a or [],
            "A_error": ae,
            "AAAA": aaaa or [],
            "AAAA_error": aaae,
        }

    return {
        "domain": apex,
        "ns": {"records": ns_records or [], "error": ns_err},
        "glue_summary": glue,
    }

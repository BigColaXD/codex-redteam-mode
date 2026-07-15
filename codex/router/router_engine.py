from __future__ import annotations
import re
from .mappings import PHASE_DEFAULT_ROUTER

FILE_PATTERNS = "\\b(upload|download|file|filepath|lfi|traversal|source exposure|write)\\b|\u4e0a\u4f20|\u4e0b\u8f7d|\u6587\u4ef6|\u6587\u4ef6\u8def\u5f84|\u8def\u5f84\u904d\u5386|\u672c\u5730\u6587\u4ef6|\u4efb\u610f\u5199\u5165"
AUTH_PATTERNS = "\\b(jwt|oauth|oidc|saml|session|login|auth|token|bola|idor)\\b|\u767b\u5f55|\u9274\u6743|\u8ba4\u8bc1|\u6388\u6743|\u4f1a\u8bdd|\u4ee4\u724c|\u8d8a\u6743"
API_PATTERNS = "\\b(api|graphql|swagger|openapi|json)\\b|\u63a5\u53e3|\u6587\u6863|schema|graphql"
INJECTION_PATTERNS = "\\b(ssrf|sqli|sql injection|xss|ssti|cmdi|xxe|deserialization|jndi|xslt|expression language|crlf)\\b|\u6ce8\u5165|\u53cd\u5e8f\u5217\u5316|\u6a21\u677f|\u547d\u4ee4\u6267\u884c"
LOGIC_PATTERNS = "\\b(race|logic|workflow|state machine|business)\\b|\u4e1a\u52a1\u903b\u8f91|\u7ade\u6001|\u6d41\u7a0b\u7f3a\u9677"

def select_router(prompt: str, phase: str) -> str:
    p = prompt
    if phase == "web":
        if re.search(AUTH_PATTERNS, p, re.I): return "auth-sec"
        if re.search(API_PATTERNS, p, re.I): return "api-sec"
        if re.search(FILE_PATTERNS, p, re.I): return "file-access-vuln"
        if re.search(LOGIC_PATTERNS, p, re.I): return "business-logic-vuln"
        if re.search(INJECTION_PATTERNS, p, re.I): return "injection-checking"
        return "recon-for-sec"
    if phase == "ad":
        if re.search("\\b(adcs|cert|certificate)\\b|\u8bc1\u4e66\u670d\u52a1|\u8bc1\u4e66\u6a21\u677f", p, re.I): return "active-directory-certificate-services"
        if re.search("\\b(acl|genericall|writeowner|writedacl)\\b|ACL|\u59d4\u6d3e\u6743\u9650|writeowner|writedacl", p, re.I): return "active-directory-acl-abuse"
        if re.search("\\b(ntlm|relay|responder)\\b|NTLM|\u4e2d\u7ee7|\u5f3a\u5236\u8ba4\u8bc1", p, re.I): return "ntlm-relay-coercion"
        return "active-directory-kerberos-attacks"
    if phase == "postex": return "post-exploitation-playbook"
    if phase == "reverse": return "malware-loader-analysis"
    if phase == "code-audit":
        if re.search(AUTH_PATTERNS, p, re.I): return "auth-sec"
        if re.search(API_PATTERNS, p, re.I): return "api-sec"
        if re.search(FILE_PATTERNS, p, re.I): return "file-access-vuln"
        if re.search(LOGIC_PATTERNS, p, re.I): return "business-logic-vuln"
        if re.search(INJECTION_PATTERNS, p, re.I): return "injection-checking"
        return "hack"
    if phase == "payload": return "weaponization-and-payloads"
    if phase == "evasion": return "windows-av-evasion"
    if phase == "cloud": return "cloud-iam-abuse"
    if phase == "container":
        if re.search("\\b(hostpath|privileged|escape|breakout|cap_sys_admin)\\b|hostPath|\u7279\u6743\u5bb9\u5668|\u9003\u9038", p, re.I): return "container-escape-techniques"
        return "kubernetes-pentesting"
    if phase == "network":
        if re.search(r"\bwebsocket|ws\b|WebSocket", p, re.I): return "websocket-security"
        if re.search(r"http/2|h2\b|HTTP/2", p, re.I): return "http2-specific-attacks"
        if re.search("\\b(smuggling|desync)\\b|\u8bf7\u6c42\u8d70\u79c1", p, re.I): return "request-smuggling"
        if re.search("\\bdns rebinding\\b|DNS\u91cd\u7ed1\u5b9a", p, re.I): return "dns-rebinding-attacks"
        return "network-protocol-attacks"
    if phase == "crypto":
        if re.search("\\b(md5|sha1|sha256|hash|length extension)\\b|\u54c8\u5e0c|\u957f\u5ea6\u6269\u5c55", p, re.I): return "hash-attack-techniques"
        if re.search("\\b(padding oracle)\\b|\u586b\u5145\u9884\u8a00\u673a", p, re.I): return "rsa-attack-techniques"
        if re.search("\\b(aes|des|cbc|gcm|ctr)\\b|\u5bf9\u79f0\u52a0\u5bc6", p, re.I): return "symmetric-cipher-attacks"
        if re.search("\\b(lattice|lwe|ntru)\\b|\u683c\u5bc6\u7801", p, re.I): return "lattice-crypto-attacks"
        if re.search("\\b(stego|steganography)\\b|\u9690\u5199", p, re.I): return "steganography-techniques"
        if re.search("\\b(caesar|vigenere|classical cipher)\\b|\u53e4\u5178\u5bc6\u7801", p, re.I): return "classical-cipher-analysis"
        return "rsa-attack-techniques"
    if phase == "mobile":
        if re.search("\\b(ssl pinning|certificate pinning|frida|objection)\\b|\u8bc1\u4e66\u9501\u5b9a|SSL Pinning", p, re.I): return "mobile-ssl-pinning-bypass"
        if re.search("\\b(ios|ipa|swift|xcode)\\b|iOS|\u82f9\u679c", p, re.I): return "ios-pentesting-tricks"
        return "android-pentesting-tricks"
    if phase == "jailbreak": return "llm-prompt-injection"
    return PHASE_DEFAULT_ROUTER.get(phase, "hack")

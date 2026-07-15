from __future__ import annotations
import re

def select_subphase(prompt: str, phase: str) -> str:
    if phase == "reverse":
        if re.search("\\b(loader|stager|dropper|callback|payload)\\b|loader|\u6837\u672c|\u9636\u6bb5|\u56de\u8c03|\u91ca\u653e\u8d44\u6e90|\u6267\u884c\u94fe", prompt, re.I): return "loader"
        if re.search("\\b(heap|rop|overflow|format string|primitive)\\b|heap|rop|\u6ea2\u51fa|\u539f\u8bed", prompt, re.I): return "exploitability"
        return "binary"
    if phase == "code-audit":
        if re.search("\\b(entry|entrypoint|controller|handler|middleware)\\b|\u5165\u53e3|\u63a7\u5236\u5668|\u5904\u7406\u5668|\u4e2d\u95f4\u4ef6", prompt, re.I): return "entrypoint"
        if re.search("\\b(sink|dangerous function|query|exec|template)\\b|sink|\u5371\u9669\u51fd\u6570|\u5371\u9669\u8c03\u7528", prompt, re.I): return "leaf"
        return "route"
    if phase == "evasion":
        if re.search("\\b(waf|cdn|header|smuggling|403|csp)\\b|WAF|403|CSP|\u8bf7\u6c42\u8d70\u79c1", prompt, re.I): return "network"
        if re.search("\\b(av|edr|defender|sandbox)\\b|\u514d\u6740|\u6740\u8f6f|\u6c99\u7bb1|EDR", prompt, re.I): return "host"
    return ""

def select_leaf_skill(prompt: str, phase: str, router: str) -> str:
    p = prompt
    if router == "llm-prompt-injection": return "llm-prompt-injection"
    if router == "auth-sec":
        if re.search("\\b(jwt|token)\\b|\u4ee4\u724c|JWT", p, re.I): return "jwt-oauth-token-attacks"
        if re.search(r"\b(oauth|oidc)\b|OAuth|OIDC", p, re.I): return "oauth-oidc-misconfiguration"
        if re.search(r"\b(saml)\b|SAML", p, re.I): return "saml-sso-assertion-attacks"
        if re.search("\\b(idor|bola)\\b|\u8d8a\u6743|BOLA|IDOR", p, re.I): return "idor-broken-object-authorization"
        return "authbypass-authentication-flaws"
    if router == "api-sec":
        if re.search(r"\b(graphql)\b|GraphQL", p, re.I): return "graphql-and-hidden-parameters"
        if re.search("\\b(jwt|token|auth)\\b|\u9274\u6743|\u4ee4\u724c", p, re.I): return "api-auth-and-jwt-abuse"
        if re.search("\\b(hpp|parameter pollution)\\b|\u53c2\u6570\u6c61\u67d3", p, re.I): return "http-parameter-pollution"
        return "api-authorization-and-bola"
    if router == "injection-checking":
        if re.search(r"\bssrf\b|SSRF", p, re.I): return "ssrf-server-side-request-forgery"
        if re.search("\\bsqli?\\b|SQL\u6ce8\u5165", p, re.I): return "sqli-sql-injection"
        if re.search(r"\bxss\b|XSS", p, re.I): return "xss-cross-site-scripting"
        if re.search(r"\bssti\b|SSTI", p, re.I): return "ssti-server-side-template-injection"
        if re.search("\\b(cmdi|command injection)\\b|\u547d\u4ee4\u6ce8\u5165", p, re.I): return "cmdi-command-injection"
        if re.search("\\bxxe\\b|XXE|XML\u5916\u90e8\u5b9e\u4f53", p, re.I): return "xxe-xml-external-entity"
        if re.search(r"\bjndi\b|JNDI", p, re.I): return "jndi-injection"
        if re.search(r"\bxslt\b|XSLT", p, re.I): return "xslt-injection"
        if re.search("\\bexpression language\\b|EL\u6ce8\u5165", p, re.I): return "expression-language-injection"
        if re.search(r"\bcrlf\b|CRLF", p, re.I): return "crlf-injection"
        return "deserialization-insecure"
    if router == "file-access-vuln":
        if re.search("\\blfi\\b|\\btraversal\\b|LFI|\u8def\u5f84\u904d\u5386", p, re.I): return "path-traversal-lfi"
        if re.search("\\b(upload|write)\\b|\u4e0a\u4f20|\u4efb\u610f\u5199\u5165", p, re.I): return "arbitrary-write-to-rce"
        return "insecure-source-code-management"
    if router == "business-logic-vuln":
        if re.search("\\brace\\b|\u7ade\u6001", p, re.I): return "race-condition"
        if re.search("\\bprototype pollution\\b|\u539f\u578b\u6c61\u67d3", p, re.I): return "prototype-pollution"
        if re.search("\\btype juggling\\b|\u5f31\u6bd4\u8f83", p, re.I): return "type-juggling"
        return "business-logic-vulnerabilities"
    if router in {"active-directory-kerberos-attacks","active-directory-acl-abuse","active-directory-certificate-services","ntlm-relay-coercion","malware-loader-analysis","cloud-iam-abuse","kubernetes-pentesting","container-escape-techniques","network-protocol-attacks","websocket-security","http2-specific-attacks","request-smuggling","dns-rebinding-attacks","rsa-attack-techniques","hash-attack-techniques","symmetric-cipher-attacks","lattice-crypto-attacks","steganography-techniques","classical-cipher-analysis","android-pentesting-tricks","ios-pentesting-tricks","mobile-ssl-pinning-bypass"}: return router
    if router == "post-exploitation-playbook":
        if re.search("\\b(credential|token|cookie|ssh key|kubeconfig)\\b|\u51ed\u8bc1|cookie|\u4ee4\u724c|ssh key", p, re.I): return "credential-access-operations"
        if re.search(r"\blinux\b|Linux", p, re.I): return "linux-privilege-escalation"
        if re.search("\\b(pivot|tunnel|socks|chisel)\\b|\u96a7\u9053|\u4ee3\u7406", p, re.I): return "tunneling-and-pivoting"
        return "windows-privilege-escalation"
    if router == "windows-av-evasion":
        if re.search(r"\bwaf\b|WAF|403", p, re.I): return "waf-bypass-techniques"
        if re.search(r"\bcsp\b|CSP", p, re.I): return "csp-bypass-advanced"
        if re.search("\\bsandbox\\b|\u6c99\u7bb1", p, re.I): return "sandbox-escape-techniques"
        if re.search("\\b(defender|av|edr)\\b|\u6740\u8f6f|\u514d\u6740|EDR", p, re.I): return "windows-av-evasion"
        return "401-403-bypass-techniques"
    if router == "weaponization-and-payloads":
        if re.search("\\b(persistence|beacon|c2)\\b|\u6301\u4e45\u5316|\u56de\u8fde|\u4fe1\u6807", p, re.I): return "persistence-and-c2"
        if re.search("\\b(delivery|phish|initial access)\\b|\u6295\u9012|\u5165\u53e3", p, re.I): return "initial-access-delivery"
        return "weaponization-and-payloads"
    if phase == "web":
        if re.search(r"\bcsrf\b|CSRF|跨站请求伪造", p, re.I): return "redteam-csrf-detail-pack"
        if re.search(r"\bclickjack", p, re.I): return "redteam-clickjacking-detail-pack"
        if re.search(r"\bcors\b|CORS", p, re.I): return "redteam-cors-miscfg-detail-pack"
        if re.search("\\b(open redirect|url redirect)\\b|开放重定向|URL跳转", p, re.I): return "redteam-open-redirect-detail-pack"
        if re.search("\\b(cache poison|web cache)\\b|缓存投毒", p, re.I): return "redteam-cache-poison-detail-pack"
        if re.search("\\b(subdomain takeover|子域名接管)\\b", p, re.I): return "redteam-subdomain-takeover-detail-pack"
        return "recon-for-sec"
    return "hack"

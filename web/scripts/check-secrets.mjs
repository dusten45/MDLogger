// 빌드 산출물(dist/)에 service-role key·서버 secret이 포함되지 않았는지 검사한다.
// 데스크톱 `src/mdlogger/secret_scan.py`와 동일한 판별 규칙을 따른다:
// - 신형 service-role key: `sb_secret_` 접두사
// - 구형 service-role key: JWT payload의 `role` claim이 `service_role`
// - URL authority부의 user:pass 임베드 자격 증명
// publishable(anon) key(`sb_publishable_` / role=anon JWT)는 허용된다.
//
// 사용: node scripts/check-secrets.mjs [dist]

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const SERVICE_ROLE_KEY_RE = /\bsb_secret_[A-Za-z0-9_-]{8,}\b/gi;
const JWT_RE = /[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}/g;
const URL_RE = /https?:\/\/[^\s"']+/g;

function b64urlDecode(segment) {
    try {
        const padded = segment + "=".repeat((4 - (segment.length % 4)) % 4);
        return Buffer.from(padded, "base64url").toString("utf8");
    } catch {
        return null;
    }
}

function jwtRole(token) {
    const parts = token.split(".");
    if (parts.length !== 3) {
        return null;
    }
    const payload = b64urlDecode(parts[1]);
    if (payload === null) {
        return null;
    }
    try {
        const data = JSON.parse(payload);
        return typeof data.role === "string" ? data.role : null;
    } catch {
        return null;
    }
}

function scanText(text) {
    const issues = [];
    if (text.match(SERVICE_ROLE_KEY_RE)) {
        issues.push("service-role key 접두사와 값 발견");
    }
    for (const token of text.matchAll(JWT_RE)) {
        if (jwtRole(token[0]) === "service_role") {
            issues.push("role='service_role' JWT(service-role key) 발견");
        }
    }
    for (const match of text.matchAll(URL_RE)) {
        const rest = match[0].split("://", 2)[1].split("/", 1)[0];
        if (rest.includes("@")) {
            issues.push("URL에 임베드된 자격 증명 발견");
        }
    }
    return issues;
}

function walk(dir) {
    const files = [];
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) {
            files.push(...walk(full));
        } else {
            files.push(full);
        }
    }
    return files;
}

const target = resolve(process.argv[2] ?? "dist");
const files = statSync(target).isDirectory() ? walk(target) : [target];

let failed = false;
for (const file of files) {
    const text = readFileSync(file, "utf8");
    for (const issue of scanText(text)) {
        failed = true;
        console.error(`FAIL: ${relative(process.cwd(), file)}: ${issue}`);
    }
}

if (failed) {
    process.exit(1);
}
console.log(`OK: ${relative(process.cwd(), target)}`);

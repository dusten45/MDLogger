import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const scanner = new URL("./check-secrets.mjs", import.meta.url);
const deployEnvChecker = new URL("./check-deploy-env.mjs", import.meta.url);

function scan(content) {
    const directory = mkdtempSync(join(tmpdir(), "mdlogger-secret-scan-"));
    const bundle = join(directory, "app.js");
    writeFileSync(bundle, content);
    try {
        return spawnSync(process.execPath, [scanner.pathname, directory], {
            encoding: "utf8",
        });
    } finally {
        rmSync(directory, { force: true, recursive: true });
    }
}

function checkDeployEnvironment(overrides) {
    const { VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, ...baseEnv } =
        process.env;
    return spawnSync(process.execPath, [deployEnvChecker.pathname], {
        encoding: "utf8",
        env: { ...baseEnv, ...overrides },
    });
}

test("publishable key는 웹 번들에 허용한다", () => {
    const result = scan("const key = 'sb_publishable_fixture';");

    assert.equal(result.status, 0);
    assert.match(result.stdout, /OK:/);
});

test("service-role key를 웹 번들에서 거부한다", () => {
    const result = scan("const key = 'sb_secret_fixture_value_12345678';");

    assert.equal(result.status, 1);
    assert.match(result.stderr, /service-role key/);
});

test("SDK의 service-role key prefix 상수는 secret으로 처리하지 않는다", () => {
    const result = scan("const isSecret = key.startsWith('sb_secret_');");

    assert.equal(result.status, 0);
});

test("HTTPS Supabase 배포 환경을 허용한다", () => {
    const result = checkDeployEnvironment({
        VITE_SUPABASE_URL: "https://example.supabase.co",
        VITE_SUPABASE_ANON_KEY: "sb_publishable_fixture",
    });

    assert.equal(result.status, 0);
    assert.match(result.stdout, /OK:/);
});

test("누락되거나 안전하지 않은 배포 환경을 거부한다", () => {
    const missing = checkDeployEnvironment({});
    const insecureUrl = checkDeployEnvironment({
        VITE_SUPABASE_URL: "http://example.supabase.co",
        VITE_SUPABASE_ANON_KEY: "sb_publishable_fixture",
    });

    assert.equal(missing.status, 1);
    assert.match(missing.stderr, /필요한 환경 변수/);
    assert.equal(insecureUrl.status, 1);
    assert.match(insecureUrl.stderr, /HTTPS/);
});

test("service_role JWT와 URL 임베드 자격 증명을 거부한다", () => {
    const payload = Buffer.from(
        JSON.stringify({ role: "service_role" }),
    ).toString("base64url");
    const result = scan(
        `const key = 'header.${payload}.signature'; const url = 'https://user:pass@example.com';`,
    );

    assert.equal(result.status, 1);
    assert.match(result.stderr, /service_role/);
    assert.match(result.stderr, /임베드된 자격 증명/);
});

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

test("웹 배포 워크플로는 전체 의존성 감사를 통과해야 빌드하고 배포한다", () => {
    const workflow = readFileSync(
        new URL("../../.github/workflows/web-deploy.yml", import.meta.url),
        "utf8",
    );
    const steps = workflow.split(/\n\s*- name: /).slice(1);
    const install = steps.findIndex((step) =>
        /^\s+run: npm ci --no-audit\s*$/m.test(step),
    );
    const audit = steps.findIndex((step) =>
        /^\s+run: npm audit\s*$/m.test(step),
    );
    const build = steps.findIndex((step) =>
        /^\s+run: npm run build\s*$/m.test(step),
    );
    const deploy = steps.findIndex((step) =>
        /^\s+run: npx wrangler deploy\b/m.test(step),
    );

    assert.ok(install >= 0);
    assert.ok(audit > install);
    assert.ok(build > audit);
    assert.ok(deploy > build);
    assert.doesNotMatch(workflow, /continue-on-error:/);
    for (const index of [audit, build, deploy]) {
        assert.doesNotMatch(steps[index], /^\s+if:/m);
    }
});

import assert from "node:assert/strict";
import {
    existsSync,
    mkdirSync,
    mkdtempSync,
    readFileSync,
    rmSync,
    writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
    buildArtifacts,
    checkArtifacts,
    checkDistLicenses,
    extractBundleEvidence,
    validateLicenseExpression,
    writeArtifacts,
} from "./generate-third-party-notices.mjs";
import { assertGeneratedLicenseArtifactsCommitted } from "./check-generated-license-artifacts.mjs";
import { removeSourceMaps } from "./remove-source-maps.mjs";

const WEB_ROOT = process.cwd();

const VALID_LICENSE = `MIT License

Copyright (c) Fixture Author

Permission is hereby granted, free of charge, to any person obtaining a copy.
`;

function createFixture() {
    const root = mkdtempSync(path.join(tmpdir(), "mdlogger-license-test-"));
    const packageDirectory = path.join(root, "node_modules", "runtime-package");
    const devDirectory = path.join(root, "node_modules", "dev-package");
    mkdirSync(packageDirectory, { recursive: true });
    mkdirSync(devDirectory, { recursive: true });
    writeFileSync(
        path.join(root, "package-lock.json"),
        JSON.stringify({
            lockfileVersion: 3,
            packages: {
                "": {
                    dependencies: { "runtime-package": "1.0.0" },
                    devDependencies: { "dev-package": "2.0.0" },
                },
                "node_modules/runtime-package": {
                    version: "1.0.0",
                    license: "MIT",
                },
                "node_modules/dev-package": {
                    version: "2.0.0",
                    dev: true,
                    license: "ISC",
                },
            },
        }),
    );
    writeFileSync(
        path.join(packageDirectory, "package.json"),
        JSON.stringify({
            name: "runtime-package",
            version: "1.0.0",
            license: "MIT",
            author: "Fixture Author",
            homepage: "https://example.test/runtime-package",
            repository: "https://example.test/runtime-package.git",
        }),
    );
    writeFileSync(path.join(packageDirectory, "LICENSE"), VALID_LICENSE);
    writeFileSync(
        path.join(devDirectory, "package.json"),
        JSON.stringify({
            name: "dev-package",
            version: "2.0.0",
            license: "ISC",
        }),
    );
    writeFileSync(path.join(devDirectory, "LICENSE"), "ISC fixture license\n");
    return root;
}

const FIXTURE_POLICY = [
    {
        name: "runtime-package",
        version: "1.0.0",
        license: "MIT",
        evidence: "main-sourcemap",
        requiredLicenseFiles: ["LICENSE"],
    },
];

test("production package metadata와 license 원문만 결정론적으로 생성한다", () => {
    const root = createFixture();
    try {
        const first = buildArtifacts({ root, policy: FIXTURE_POLICY });
        const second = buildArtifacts({ root, policy: FIXTURE_POLICY });
        assert.deepEqual([...first], [...second]);

        const notices = first.get("public/third-party-notices.txt");
        assert.match(notices, /runtime-package 1\.0\.0/);
        assert.match(notices, /Fixture Author/);
        assert.doesNotMatch(notices, /dev-package/);
        assert.equal(
            first.get("public/licenses/runtime-package/LICENSE"),
            VALID_LICENSE,
        );
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("생성 결과가 누락되거나 바뀌면 검사를 실패한다", () => {
    const root = createFixture();
    try {
        writeArtifacts({ root, policy: FIXTURE_POLICY });
        checkArtifacts({ root, policy: FIXTURE_POLICY });
        writeFileSync(
            path.join(root, "public", "third-party-notices.txt"),
            "stale\n",
        );
        assert.throws(
            () => checkArtifacts({ root, policy: FIXTURE_POLICY }),
            /artifact is stale/,
        );
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("누락·UNKNOWN·미검토 license expression을 거부한다", () => {
    const root = createFixture();
    const packageDir = path.join(root, "node_modules", "runtime-package");
    try {
        for (const expression of [
            undefined,
            "",
            "UNKNOWN",
            "Apache-2.0 OR MIT",
        ]) {
            assert.throws(() =>
                validateLicenseExpression({
                    expression,
                    expectedExpression: "MIT",
                    packageDir,
                    packageName: "runtime-package",
                }),
            );
        }
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("SEE LICENSE IN이 가리키는 파일이 없으면 거부한다", () => {
    const root = createFixture();
    try {
        assert.throws(
            () =>
                validateLicenseExpression({
                    expression: "SEE LICENSE IN MISSING.txt",
                    expectedExpression: "SEE LICENSE IN MISSING.txt",
                    packageDir: path.join(
                        root,
                        "node_modules",
                        "runtime-package",
                    ),
                    packageName: "runtime-package",
                }),
            /referenced license file is missing/,
        );
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("sourcemap에서 scoped package와 PWA virtual module을 식별한다", () => {
    const root = mkdtempSync(path.join(tmpdir(), "mdlogger-license-map-test-"));
    try {
        mkdirSync(path.join(root, "assets"), { recursive: true });
        writeFileSync(
            path.join(root, "assets", "index.js.map"),
            JSON.stringify({
                version: 3,
                sources: [
                    "../../node_modules/react/index.js",
                    "../../node_modules/@supabase/auth-js/dist/module/index.js",
                    "../../../../@vite-plugin-pwa/virtual:pwa-register/react",
                ],
            }),
        );
        const { observed } = extractBundleEvidence(root);
        assert.deepEqual([...observed.keys()].sort(), [
            "@supabase/auth-js",
            "react",
            "vite-plugin-pwa",
        ]);
        assert.deepEqual(
            [...observed.get("vite-plugin-pwa")],
            ["pwa-virtual-module"],
        );
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("Vite public copy 결과의 notices와 package별 license를 검증한다", () => {
    const root = createFixture();
    const distDirectory = path.join(root, "dist");
    try {
        const artifacts = buildArtifacts({ root, policy: FIXTURE_POLICY });
        for (const [relativePath, content] of artifacts) {
            if (!relativePath.startsWith("public/")) {
                continue;
            }
            const outputPath = path.join(
                distDirectory,
                relativePath.slice("public/".length),
            );
            mkdirSync(path.dirname(outputPath), { recursive: true });
            writeFileSync(outputPath, content);
        }
        checkDistLicenses({ root, distDirectory, artifacts });
        assert.equal(
            readFileSync(
                path.join(distDirectory, "third-party-notices.txt"),
                "utf8",
            ),
            artifacts.get("public/third-party-notices.txt"),
        );
        rmSync(path.join(distDirectory, "licenses"), { recursive: true });
        assert.throws(
            () => checkDistLicenses({ root, distDirectory, artifacts }),
            /public copy is missing/,
        );
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("Vite bundled dependency의 별도 라이선스 표현을 고지한다", () => {
    const inventory = JSON.parse(
        readFileSync(path.join(WEB_ROOT, "licenses", "inventory.json"), "utf8"),
    );
    const notices = readFileSync(
        path.join(WEB_ROOT, "public", "third-party-notices.txt"),
        "utf8",
    );

    assert.deepEqual(
        inventory.reviewPolicy.retainedBundledDependencyLicenseExpressions,
        ["Apache-2.0", "BSD-2-Clause", "CC0-1.0", "ISC", "MIT"],
    );
    assert.match(notices, /Vite's retained bundled-dependency notice/);
});

test("PWA가 라이선스 문서를 precache하고 SPA fallback에서 제외한다", () => {
    const config = readFileSync(path.join(WEB_ROOT, "vite.config.ts"), "utf8");

    assert.match(config, /"third-party-notices\.txt"/);
    assert.match(config, /"licenses\/\*\*\/\*"/);
    assert.match(
        config,
        /navigateFallbackDenylist:[\s\S]*third-party-notices[\s\S]*licenses/,
    );
});

test("source-map 제거는 map과 참조 지시문을 모두 삭제한다", () => {
    const root = mkdtempSync(path.join(tmpdir(), "mdlogger-source-map-test-"));
    try {
        const assets = path.join(root, "assets");
        mkdirSync(assets);
        const script = path.join(assets, "main.js");
        const stylesheet = path.join(assets, "main.css");
        const map = path.join(assets, "main.js.map");
        writeFileSync(
            script,
            "console.log('ok');\n//# sourceMappingURL=main.js.map\n",
        );
        writeFileSync(
            stylesheet,
            "body {}\n/*# sourceMappingURL=main.css.map */\n",
        );
        writeFileSync(map, "{}");

        const result = removeSourceMaps(root);

        assert.equal(result.mapsRemoved, 1);
        assert.equal(result.directivesRemoved, 2);
        assert.equal(existsSync(map), false);
        assert.doesNotMatch(readFileSync(script, "utf8"), /sourceMappingURL/);
        assert.doesNotMatch(
            readFileSync(stylesheet, "utf8"),
            /sourceMappingURL/,
        );
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("생성 라이선스 산출물이 Git에 없으면 직접 deploy를 차단한다", () => {
    assert.doesNotThrow(() =>
        assertGeneratedLicenseArtifactsCommitted({ status: () => "" }),
    );
    assert.throws(
        () =>
            assertGeneratedLicenseArtifactsCommitted({
                status: () => "?? public/licenses/vite/LICENSE.md\n",
            }),
        /modified, deleted, or untracked/,
    );
});

test("직접 deploy도 생성물과 production bundle 라이선스를 검사한다", () => {
    const packageJson = JSON.parse(
        readFileSync(path.join(WEB_ROOT, "package.json"), "utf8"),
    );
    const deploy = packageJson.scripts.deploy;

    assert.ok(deploy.indexOf("check:licenses") < deploy.indexOf("build"));
    assert.ok(
        deploy.indexOf("check:license-artifacts") >
            deploy.indexOf("check:licenses"),
    );
    assert.ok(
        deploy.indexOf("check:license-artifacts") < deploy.indexOf("build"),
    );
    assert.ok(deploy.indexOf("check:license-bundle") > deploy.indexOf("build"));
    assert.ok(
        deploy.indexOf("check:license-bundle") <
            deploy.indexOf("strip:source-maps"),
    );
    assert.ok(
        deploy.indexOf("strip:source-maps") < deploy.indexOf("check:secrets"),
    );
    assert.ok(
        deploy.indexOf("check:license-bundle") < deploy.indexOf("wrangler"),
    );
});

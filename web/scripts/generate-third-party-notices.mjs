import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
    existsSync,
    mkdirSync,
    readFileSync,
    readdirSync,
    rmSync,
    statSync,
    writeFileSync,
} from "node:fs";

import path from "node:path";

import { fileURLToPath, pathToFileURL } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(SCRIPT_DIR, "..");

export const REVIEWED_PACKAGES = Object.freeze([
    reviewed(
        "@supabase/auth-js",
        "2.112.3",
        "MIT",
        "main-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "@supabase/functions-js",
        "2.112.3",
        "MIT",
        "main-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "@supabase/phoenix",
        "0.4.5",
        "MIT",
        "main-sourcemap",
        "LICENSE.md",
    ),
    reviewed(
        "@supabase/postgrest-js",
        "2.112.3",
        "MIT",
        "main-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "@supabase/realtime-js",
        "2.112.3",
        "MIT",
        "main-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "@supabase/storage-js",
        "2.112.3",
        "MIT",
        "main-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "@supabase/supabase-js",
        "2.112.3",
        "MIT",
        "main-sourcemap",
        "LICENSE",
    ),
    reviewed("iceberg-js", "0.8.1", "MIT", "main-sourcemap", "LICENSE"),
    reviewed("react", "18.3.1", "MIT", "main-sourcemap", "LICENSE"),
    reviewed("react-dom", "18.3.1", "MIT", "main-sourcemap", "LICENSE"),
    reviewed("react-router", "7.18.2", "MIT", "main-sourcemap", "LICENSE.md"),
    reviewed(
        "react-router-dom",
        "7.18.2",
        "MIT",
        "tree-shaken-facade",
        "LICENSE.md",
    ),
    reviewed("scheduler", "0.23.2", "MIT", "main-sourcemap", "LICENSE"),
    reviewed("tslib", "2.8.1", "0BSD", "main-sourcemap", "LICENSE.txt"),
    reviewed(
        "vite-plugin-pwa",
        "1.3.0",
        "MIT",
        "pwa-virtual-module",
        "LICENSE",
    ),
    reviewed(
        "workbox-core",
        "7.4.1",
        "MIT",
        "service-worker-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "workbox-precaching",
        "7.4.1",
        "MIT",
        "service-worker-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "workbox-routing",
        "7.4.1",
        "MIT",
        "service-worker-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "workbox-strategies",
        "7.4.1",
        "MIT",
        "service-worker-sourcemap",
        "LICENSE",
    ),
    reviewed(
        "workbox-window",
        "7.4.1",
        "MIT",
        "pwa-window-sourcemap",
        "LICENSE",
    ),
    reviewed("vite", "6.4.3", "MIT", "vite-generated-helper", "LICENSE.md"),
]);

const VITE_BUNDLED_DEPENDENCY_LICENSE_EXPRESSIONS = Object.freeze([
    "Apache-2.0",
    "BSD-2-Clause",
    "CC0-1.0",
    "ISC",
    "MIT",
]);

const EXPECTED_BUILD_INPUTS = Object.freeze([
    {
        name: "workbox-build",
        version: "7.4.1",
        reason: "Build-time service worker generator. Its generated runtime is represented by the Workbox runtime packages found in service worker sourcemaps.",
    },
    {
        name: "sharp",
        version: "0.35.3",
        reason: "Development-only PWA icon generator, including its optional @img/sharp-* and libvips binaries; absent from production sourcemaps.",
    },
    {
        name: "@img/sharp-wasm32",
        version: "0.35.3",
        reason: "Optional development-only Sharp backend used for icon generation; absent from production sourcemaps.",
    },
    {
        name: "@emnapi/runtime",
        version: "1.11.3",
        reason: "Optional transitive dependency of the development-only Sharp WASM backend; absent from production sourcemaps.",
    },
]);

function reviewed(name, version, license, evidence, requiredLicenseFile) {
    return Object.freeze({
        name,
        version,
        license,
        evidence,
        requiredLicenseFiles: Object.freeze([requiredLicenseFile]),
    });
}

function readJson(filePath) {
    return JSON.parse(readFileSync(filePath, "utf8"));
}

function stableJson(value) {
    return `${JSON.stringify(value, null, 2)}\n`;
}

function normalizeAuthor(author) {
    if (typeof author === "string") {
        return author;
    }
    if (!author || typeof author !== "object") {
        return null;
    }
    const name = typeof author.name === "string" ? author.name : "";
    const email = typeof author.email === "string" ? ` <${author.email}>` : "";
    const url = typeof author.url === "string" ? ` (${author.url})` : "";
    return `${name}${email}${url}`.trim() || null;
}

function normalizeRepository(repository) {
    if (typeof repository === "string") {
        return { url: repository, directory: null };
    }
    if (!repository || typeof repository !== "object") {
        return null;
    }
    return {
        url: typeof repository.url === "string" ? repository.url : null,
        directory:
            typeof repository.directory === "string"
                ? repository.directory
                : null,
    };
}

export function safePackagePath(packageName) {
    const parts = packageName.split("/");
    assert(
        parts.every(
            (part) =>
                part.length > 0 &&
                part !== "." &&
                part !== ".." &&
                /^@?[A-Za-z0-9._-]+$/.test(part),
        ),
        `Unsafe package name: ${packageName}`,
    );
    return parts.join("/");
}

function licenseLikeFiles(packageDir) {
    return readdirSync(packageDir)
        .filter((name) => /^(license|notice|copying)(\..*)?$/i.test(name))
        .filter((name) => statSync(path.join(packageDir, name)).isFile())
        .sort((left, right) => left.localeCompare(right, "en"));
}

export function validateLicenseExpression({
    expression,
    expectedExpression,
    packageDir,
    packageName,
}) {
    if (typeof expression !== "string" || expression.trim() === "") {
        throw new Error(`${packageName}: missing license expression`);
    }
    const normalized = expression.trim();
    if (normalized.toUpperCase() === "UNKNOWN") {
        throw new Error(`${packageName}: UNKNOWN license expression`);
    }
    const seeLicense = /^SEE LICENSE IN\s+(.+)$/i.exec(normalized);
    if (seeLicense) {
        const referenced = seeLicense[1].trim();
        const resolved = path.resolve(packageDir, referenced);
        if (
            !resolved.startsWith(`${path.resolve(packageDir)}${path.sep}`) ||
            !existsSync(resolved)
        ) {
            throw new Error(
                `${packageName}: referenced license file is missing: ${referenced}`,
            );
        }
    }
    if (normalized !== expectedExpression) {
        throw new Error(
            `${packageName}: unreviewed license expression ${JSON.stringify(normalized)}; expected ${JSON.stringify(expectedExpression)}`,
        );
    }
    return normalized;
}

function extractCopyrightNotices(contents) {
    const notices = new Set();
    for (const content of contents) {
        for (const rawLine of content.split(/\r?\n/)) {
            const line = rawLine.trim().replace(/^>\s*/, "");
            if (
                /^Copyright(?:\s|\()/i.test(line) &&
                !/copyright (?:license|notice|owner|holder)/i.test(line) &&
                !/\[yyyy\]|\[name of copyright owner\]/i.test(line)
            ) {
                notices.add(line);
            }
        }
    }
    return [...notices].sort((left, right) => left.localeCompare(right, "en"));
}

function collectPackage(root, lockfile, policy) {
    const lockPath = `node_modules/${policy.name}`;
    const lockEntry = lockfile.packages?.[lockPath];
    if (!lockEntry) {
        throw new Error(`${policy.name}: missing from package-lock.json`);
    }
    if (lockEntry.version !== policy.version) {
        throw new Error(
            `${policy.name}: unreviewed lockfile version ${lockEntry.version}; expected ${policy.version}`,
        );
    }

    const packageDir = path.join(root, "node_modules", policy.name);
    const metadataPath = path.join(packageDir, "package.json");
    if (!existsSync(metadataPath)) {
        throw new Error(
            `${policy.name}: installed package metadata is missing`,
        );
    }
    const metadata = readJson(metadataPath);
    if (metadata.name !== policy.name || metadata.version !== policy.version) {
        throw new Error(
            `${policy.name}: installed metadata does not match reviewed name/version`,
        );
    }
    if (
        typeof lockEntry.license === "string" &&
        lockEntry.license.trim() !== String(metadata.license ?? "").trim()
    ) {
        throw new Error(
            `${policy.name}: lockfile and installed license expressions differ`,
        );
    }

    const license = validateLicenseExpression({
        expression: metadata.license,
        expectedExpression: policy.license,
        packageDir,
        packageName: policy.name,
    });
    const discoveredFiles = licenseLikeFiles(packageDir);
    for (const requiredFile of policy.requiredLicenseFiles) {
        if (!discoveredFiles.includes(requiredFile)) {
            throw new Error(
                `${policy.name}: required license file is missing: ${requiredFile}`,
            );
        }
    }
    if (discoveredFiles.length === 0) {
        throw new Error(`${policy.name}: no license or notice files found`);
    }

    const files = discoveredFiles.map((fileName) => {
        const content = readFileSync(path.join(packageDir, fileName), "utf8");
        return {
            name: fileName,
            content,
            sha256: createHash("sha256").update(content).digest("hex"),
        };
    });

    return {
        name: policy.name,
        version: policy.version,
        license,
        author: normalizeAuthor(metadata.author),
        homepage:
            typeof metadata.homepage === "string" ? metadata.homepage : null,
        repository: normalizeRepository(metadata.repository),
        copyrightNotices: extractCopyrightNotices(
            files.map((file) => file.content),
        ),
        bundleEvidence: policy.evidence,
        licenseFiles: files.map((file) => ({
            path: `licenses/${safePackagePath(policy.name)}/${file.name}`,
            sha256: file.sha256,
        })),
        _files: files,
    };
}

function collectExcludedBuildInputs(lockfile) {
    return EXPECTED_BUILD_INPUTS.map((entry) => {
        const lockEntry = lockfile.packages?.[`node_modules/${entry.name}`];
        if (!lockEntry || lockEntry.version !== entry.version) {
            throw new Error(
                `${entry.name}: build-input version changed; review the exclusion policy`,
            );
        }
        return entry;
    });
}

export function collectInventory({
    root = WEB_ROOT,
    policy = REVIEWED_PACKAGES,
} = {}) {
    const lockfile = readJson(path.join(root, "package-lock.json"));
    if (lockfile.lockfileVersion !== 3) {
        throw new Error(
            `Unsupported package-lock version: ${lockfile.lockfileVersion}`,
        );
    }
    const packages = [...policy]
        .sort((left, right) => left.name.localeCompare(right.name, "en"))
        .map((entry) => collectPackage(root, lockfile, entry));
    const excludedBuildInputs =
        policy === REVIEWED_PACKAGES
            ? collectExcludedBuildInputs(lockfile)
            : [];
    return { lockfile, packages, excludedBuildInputs };
}

function repositoryDisplay(repository) {
    if (!repository?.url) {
        return "Not declared";
    }
    return repository.directory
        ? `${repository.url} (${repository.directory})`
        : repository.url;
}

function renderNotices(packages, excludedBuildInputs) {
    const lines = [
        "MDLogger Web Third-Party Notices",
        "================================",
        "",
        "This file is generated deterministically from package-lock.json and installed package metadata/license files.",
        "It covers code present in the production browser bundle, PWA registration helper, generated service worker runtime, and Vite-generated runtime helper evidence.",
        "Build-, test-, lint-, and icon-generation-only packages are excluded from runtime notices.",
        "",
        `Runtime package count: ${packages.length}`,
        "Reviewed top-level runtime package license expressions: 0BSD, MIT",
        "Vite's retained bundled-dependency notice additionally contains: Apache-2.0, BSD-2-Clause, CC0-1.0, ISC, MIT.",
        "The full bundled-dependency notice is copied at /licenses/vite/LICENSE.md.",
        "",
        "Build-time evidence (not runtime packages):",
        ...excludedBuildInputs.map(
            (entry) => `- ${entry.name} ${entry.version}: ${entry.reason}`,
        ),
        "",
    ];

    for (const packageRecord of packages) {
        lines.push(
            "================================================================================",
            `${packageRecord.name} ${packageRecord.version}`,
            `License: ${packageRecord.license}`,
            `Author: ${packageRecord.author ?? "Not declared"}`,
            `Homepage: ${packageRecord.homepage ?? "Not declared"}`,
            `Repository: ${repositoryDisplay(packageRecord.repository)}`,
            `Production bundle evidence: ${packageRecord.bundleEvidence}`,
            `Copied files: ${packageRecord.licenseFiles.map((file) => `/${file.path}`).join(", ")}`,
            "",
        );
        for (const file of packageRecord._files) {
            lines.push(`--- ${file.name} ---`, "", file.content.trimEnd(), "");
        }
    }
    return `${lines.join("\n").trimEnd()}\n`;
}

function inventoryForJson(packages, excludedBuildInputs) {
    return {
        schemaVersion: 1,
        source: {
            lockfile: "package-lock.json",
            installedMetadata: "node_modules/<package>/package.json",
            bundleEvidence:
                "Temporary Vite production build with sourcemaps; main, PWA registration, Workbox window, and generated service worker closures are checked separately.",
        },
        reviewPolicy: {
            allowedTopLevelPackageLicenseExpressions: ["0BSD", "MIT"],
            retainedBundledDependencyLicenseExpressions:
                VITE_BUNDLED_DEPENDENCY_LICENSE_EXPRESSIONS,
            exactPackageVersionReview: true,
            rejectMissingLicense: true,
            rejectUnknownLicense: true,
            rejectMissingSeeLicenseFile: true,
            rejectUnreviewedExpressions: true,
            includeViteBundledThirdPartyNotices: true,
        },
        runtimePackageCount: packages.length,
        packages: packages.map(({ _files, ...packageRecord }) => packageRecord),
        excludedBuildInputs,
    };
}

export function buildArtifacts({
    root = WEB_ROOT,
    policy = REVIEWED_PACKAGES,
} = {}) {
    const { packages, excludedBuildInputs } = collectInventory({
        root,
        policy,
    });
    const artifacts = new Map();
    artifacts.set(
        "public/third-party-notices.txt",
        renderNotices(packages, excludedBuildInputs),
    );
    artifacts.set(
        "licenses/inventory.json",
        stableJson(inventoryForJson(packages, excludedBuildInputs)),
    );
    for (const packageRecord of packages) {
        for (const file of packageRecord._files) {
            artifacts.set(
                `public/licenses/${safePackagePath(packageRecord.name)}/${file.name}`,
                file.content,
            );
        }
    }
    return artifacts;
}

function listFilesRecursively(directory) {
    if (!existsSync(directory)) {
        return [];
    }
    const results = [];
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const child = path.join(directory, entry.name);
        if (entry.isDirectory()) {
            results.push(...listFilesRecursively(child));
        } else if (entry.isFile()) {
            results.push(child);
        }
    }
    return results.sort((left, right) => left.localeCompare(right, "en"));
}

export function writeArtifacts({
    root = WEB_ROOT,
    policy = REVIEWED_PACKAGES,
} = {}) {
    const artifacts = buildArtifacts({ root, policy });
    rmSync(path.join(root, "public", "licenses"), {
        recursive: true,
        force: true,
    });
    for (const [relativePath, content] of artifacts) {
        const outputPath = path.join(root, relativePath);
        mkdirSync(path.dirname(outputPath), { recursive: true });
        writeFileSync(outputPath, content, "utf8");
    }
    return artifacts;
}

export function checkArtifacts({
    root = WEB_ROOT,
    policy = REVIEWED_PACKAGES,
} = {}) {
    const artifacts = buildArtifacts({ root, policy });
    const expectedLicenseFiles = [];
    for (const [relativePath, content] of artifacts) {
        const outputPath = path.join(root, relativePath);
        if (!existsSync(outputPath)) {
            throw new Error(`Generated artifact is missing: ${relativePath}`);
        }
        if (readFileSync(outputPath, "utf8") !== content) {
            throw new Error(`Generated artifact is stale: ${relativePath}`);
        }
        if (relativePath.startsWith("public/licenses/")) {
            expectedLicenseFiles.push(path.resolve(outputPath));
        }
    }
    const actualLicenseFiles = listFilesRecursively(
        path.join(root, "public", "licenses"),
    ).map((file) => path.resolve(file));
    assert.deepEqual(
        actualLicenseFiles,
        expectedLicenseFiles.sort((left, right) =>
            left.localeCompare(right, "en"),
        ),
        "public/licenses contains stale or unexpected files",
    );
    return artifacts;
}

function packageNameFromSource(source) {
    const normalized = source.replaceAll("\\", "/");
    const match = /(?:^|\/)node_modules\/((?:@[^/]+\/)?[^/]+)(?:\/|$)/.exec(
        normalized,
    );
    return match?.[1] ?? null;
}

function evidenceCategory(packageName, source) {
    if (packageName === "workbox-window") {
        return "pwa-window-sourcemap";
    }
    if (packageName.startsWith("workbox-")) {
        return "service-worker-sourcemap";
    }
    if (source.includes("@vite-plugin-pwa/virtual:")) {
        return "pwa-virtual-module";
    }
    return "main-sourcemap";
}

export function extractBundleEvidence(distDirectory) {
    const mapFiles = listFilesRecursively(distDirectory).filter((file) =>
        file.endsWith(".map"),
    );
    if (mapFiles.length === 0) {
        throw new Error(`No production sourcemaps found in ${distDirectory}`);
    }

    const observed = new Map();
    for (const mapFile of mapFiles) {
        const sourceMap = readJson(mapFile);
        if (!Array.isArray(sourceMap.sources)) {
            throw new Error(`Invalid sourcemap sources: ${mapFile}`);
        }
        for (const source of sourceMap.sources) {
            if (typeof source !== "string") {
                continue;
            }
            let packageName = packageNameFromSource(source);
            if (!packageName && source.includes("@vite-plugin-pwa/virtual:")) {
                packageName = "vite-plugin-pwa";
            }
            if (!packageName) {
                continue;
            }
            const category = evidenceCategory(packageName, source);
            const categories = observed.get(packageName) ?? new Set();
            categories.add(category);
            observed.set(packageName, categories);
        }
    }
    return { mapFiles, observed };
}

function expectedByEvidence(policy, evidence) {
    return policy
        .filter((entry) => entry.evidence === evidence)
        .map((entry) => entry.name)
        .sort((left, right) => left.localeCompare(right, "en"));
}

function observedByEvidence(observed, evidence) {
    return [...observed]
        .filter(([, categories]) => categories.has(evidence))
        .map(([name]) => name)
        .sort((left, right) => left.localeCompare(right, "en"));
}

export function checkDistLicenses({
    root = WEB_ROOT,
    distDirectory,
    artifacts,
}) {
    const expectedArtifacts = artifacts ?? checkArtifacts({ root });
    for (const relativePath of expectedArtifacts.keys()) {
        if (!relativePath.startsWith("public/")) {
            continue;
        }
        const publicRelativePath = relativePath.slice("public/".length);
        const distPath = path.join(distDirectory, publicRelativePath);
        if (!existsSync(distPath)) {
            throw new Error(
                `Vite public copy is missing: ${publicRelativePath}`,
            );
        }
        const sourceContent = expectedArtifacts.get(relativePath);
        if (readFileSync(distPath, "utf8") !== sourceContent) {
            throw new Error(`Vite public copy differs: ${publicRelativePath}`);
        }
    }
}

export function checkBundleEvidence({
    root = WEB_ROOT,
    distDirectory,
    policy = REVIEWED_PACKAGES,
} = {}) {
    const artifacts = checkArtifacts({ root, policy });
    const { mapFiles, observed } = extractBundleEvidence(distDirectory);

    for (const evidence of [
        "main-sourcemap",
        "pwa-virtual-module",
        "pwa-window-sourcemap",
        "service-worker-sourcemap",
    ]) {
        assert.deepEqual(
            observedByEvidence(observed, evidence),
            expectedByEvidence(policy, evidence),
            `${evidence} package closure differs from the reviewed inventory`,
        );
    }

    const rootMetadata = readJson(path.join(root, "package.json"));
    if (
        observed.has("react-router") &&
        rootMetadata.dependencies?.["react-router-dom"]
    ) {
        observed.set("react-router-dom", new Set(["tree-shaken-facade"]));
    }
    if (existsSync(path.join(distDirectory, "index.html"))) {
        observed.set("vite", new Set(["vite-generated-helper"]));
    }

    const allObserved = [...observed.keys()].sort((left, right) =>
        left.localeCompare(right, "en"),
    );
    const allExpected = [...policy]
        .map((entry) => entry.name)
        .sort((left, right) => left.localeCompare(right, "en"));
    assert.deepEqual(
        allObserved,
        allExpected,
        "Combined production package closure differs from the reviewed inventory",
    );

    const serviceWorkerPath = path.join(distDirectory, "sw.js");
    if (!existsSync(serviceWorkerPath)) {
        throw new Error("Generated service worker is missing: sw.js");
    }
    const serviceWorker = readFileSync(serviceWorkerPath, "utf8");
    if (
        !serviceWorker.includes("importScripts") ||
        !/workbox-[^"']+\.js/.test(serviceWorker)
    ) {
        throw new Error(
            "Generated service worker does not reference the inspected Workbox runtime",
        );
    }
    for (const relativePath of artifacts.keys()) {
        if (!relativePath.startsWith("public/")) {
            continue;
        }
        const publicRelativePath = relativePath.slice("public/".length);
        if (!serviceWorker.includes(publicRelativePath)) {
            throw new Error(
                `License artifact is not precached by the service worker: ${publicRelativePath}`,
            );
        }
    }

    checkDistLicenses({ root, distDirectory, artifacts });
    return {
        mapCount: mapFiles.length,
        packages: allObserved,
        evidence: Object.fromEntries(
            [...observed]
                .sort(([left], [right]) => left.localeCompare(right, "en"))
                .map(([name, categories]) => [name, [...categories].sort()]),
        ),
    };
}

function printBundleResult(result) {
    console.log(
        `License bundle evidence passed: ${result.packages.length} runtime packages across ${result.mapCount} sourcemaps.`,
    );
    for (const [name, evidence] of Object.entries(result.evidence)) {
        console.log(`- ${name}: ${evidence.join(", ")}`);
    }
}

function main() {
    const [command, argument] = process.argv.slice(2);
    if (!command) {
        const artifacts = writeArtifacts();
        console.log(
            `Generated ${artifacts.size} third-party license artifacts.`,
        );
        return;
    }
    if (command === "--check") {
        const artifacts = checkArtifacts();
        console.log(
            `Third-party license artifacts are current (${artifacts.size} files).`,
        );
        return;
    }
    if (command === "--check-bundle") {
        const result = checkBundleEvidence({
            distDirectory: path.resolve(argument ?? "dist"),
        });
        printBundleResult(result);
        return;
    }
    throw new Error(`Unknown command: ${command}`);
}

const isMain =
    process.argv[1] &&
    pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
    main();
}

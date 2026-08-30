import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const GENERATED_LICENSE_PATHS = Object.freeze([
    "licenses/inventory.json",
    "public/third-party-notices.txt",
    "public/licenses",
]);

function gitStatus(root) {
    try {
        return execFileSync(
            "git",
            [
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                ...GENERATED_LICENSE_PATHS,
            ],
            { cwd: root, encoding: "utf8" },
        );
    } catch (error) {
        throw new Error(
            "Unable to check generated license artifacts with git status",
            { cause: error },
        );
    }
}

export function assertGeneratedLicenseArtifactsCommitted({
    root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."),
    status = gitStatus,
} = {}) {
    const output = status(root);
    if (output.trim()) {
        throw new Error(
            "Generated web license artifacts are modified, deleted, or untracked. Commit the regenerated artifacts.\n" +
                output.trim(),
        );
    }
}

const isMain =
    process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
    assertGeneratedLicenseArtifactsCommitted();
    console.log("Generated web license artifacts are committed.");
}

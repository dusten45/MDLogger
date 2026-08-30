import {
    existsSync,
    readdirSync,
    readFileSync,
    rmSync,
    writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE_MAP_DIRECTIVE =
    /^[ \t]*(?:(?:\/\/#)|(?:\/\*#))\s*sourceMappingURL=[^\r\n]*\r?\n?/gmu;

export function removeSourceMaps(directory) {
    if (!existsSync(directory)) {
        throw new Error(`Build directory does not exist: ${directory}`);
    }

    const result = { directivesRemoved: 0, mapsRemoved: 0 };
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const child = path.join(directory, entry.name);
        if (entry.isDirectory()) {
            const childResult = removeSourceMaps(child);
            result.directivesRemoved += childResult.directivesRemoved;
            result.mapsRemoved += childResult.mapsRemoved;
        } else if (entry.isFile() && entry.name.endsWith(".map")) {
            rmSync(child);
            result.mapsRemoved += 1;
        } else if (entry.isFile() && /\.(?:css|js)$/u.test(entry.name)) {
            const contents = readFileSync(child, "utf8");
            const directives = contents.match(SOURCE_MAP_DIRECTIVE) ?? [];
            if (directives.length > 0) {
                writeFileSync(
                    child,
                    contents.replace(SOURCE_MAP_DIRECTIVE, ""),
                    "utf8",
                );
                result.directivesRemoved += directives.length;
            }
        }
    }
    return result;
}

const isMain =
    process.argv[1] &&
    path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
    const directory = process.argv[2] ?? "dist";
    const result = removeSourceMaps(path.resolve(directory));
    console.log(
        `Removed ${result.mapsRemoved} source maps and ${result.directivesRemoved} source-map directives from ${directory}`,
    );
}

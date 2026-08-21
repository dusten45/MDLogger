import sharp from "sharp";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { existsSync, mkdirSync } from "fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "..");
const publicDir = resolve(rootDir, "public");

const sourcePath = resolve(publicDir, "icon-source.png");

if (!existsSync(sourcePath)) {
  console.error(`Source icon not found at: ${sourcePath}`);
  process.exit(1);
}

const BG_COLOR = "#0F172A";

async function generateStandardIcon(size, outputPath) {
  await sharp(sourcePath)
    .resize(size, size, {
      fit: "contain",
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    })
    .png()
    .toFile(outputPath);
  console.log(`Generated: ${outputPath} (${size}x${size})`);
}

async function generateMaskableIcon(size, outputPath) {
  // Safe zone for maskable icon is 80% in the center.
  const innerSize = Math.round(size * 0.8);
  const offset = Math.round((size - innerSize) / 2);

  const innerBuffer = await sharp(sourcePath)
    .resize(innerSize, innerSize, {
      fit: "contain",
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    })
    .png()
    .toBuffer();

  await sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: BG_COLOR,
    },
  })
    .composite([
      {
        input: innerBuffer,
        top: offset,
        left: offset,
      },
    ])
    .png()
    .toFile(outputPath);
  console.log(`Generated maskable: ${outputPath} (${size}x${size})`);
}

async function main() {
  if (!existsSync(publicDir)) {
    mkdirSync(publicDir, { recursive: true });
  }

  // 1. Standard icons
  await generateStandardIcon(192, resolve(publicDir, "pwa-192x192.png"));
  await generateStandardIcon(512, resolve(publicDir, "pwa-512x512.png"));
  await generateStandardIcon(180, resolve(publicDir, "apple-touch-icon.png"));

  // 2. Maskable icons
  await generateMaskableIcon(192, resolve(publicDir, "pwa-maskable-192x192.png"));
  await generateMaskableIcon(512, resolve(publicDir, "pwa-maskable-512x512.png"));

  console.log("All PWA icons generated successfully!");
}

main().catch((err) => {
  console.error("Failed to generate icons:", err);
  process.exit(1);
});

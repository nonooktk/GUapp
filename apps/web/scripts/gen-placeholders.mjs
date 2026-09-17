// 商品画像プレースホルダーの生成（Wave 1）。
// seed の image_path は `products/001/1.jpg`〜`products/030/1.jpg` だが実ファイルが無いため、
// `public/products/<番号>/1.jpg` に単色 PNG を書き出す（依存追加なし。zlib と手書き CRC32 のみ）。
// 拡張子は .jpg のままだが中身は PNG。ブラウザは <img> の内容をスニッフィングして表示できる（README 参照）。
// 実行: node scripts/gen-placeholders.mjs [件数=30]

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const here = dirname(fileURLToPath(import.meta.url));
const outRoot = join(here, "..", "public", "products");
const count = Number(process.argv[2] ?? 30);
const SIZE = 8; // 8×8 の単色。object-cover で拡大されても単色なので劣化しない

const crcTable = new Uint32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const typeBuf = Buffer.from(type, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])));
  return Buffer.concat([len, typeBuf, data, crc]);
}

/** 単色 RGB の PNG バイナリ */
function solidPng(r, g, b) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(SIZE, 0);
  ihdr.writeUInt32BE(SIZE, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type: truecolor
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  const row = Buffer.alloc(1 + SIZE * 3);
  for (let x = 0; x < SIZE; x++) {
    row[1 + x * 3] = r;
    row[2 + x * 3] = g;
    row[3 + x * 3] = b;
  }
  const raw = Buffer.concat(Array.from({ length: SIZE }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** 商品番号ごとに色相を回して見分けられるようにする（HSL→RGB、彩度低め） */
function colorFor(n) {
  const h = ((n - 1) * 137.5) % 360;
  const s = 0.35;
  const l = 0.7;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [r, g, b].map((v) => Math.round((v + m) * 255));
}

for (let n = 1; n <= count; n++) {
  const dir = join(outRoot, String(n).padStart(3, "0"));
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "1.jpg"), solidPng(...colorFor(n)));
}
console.log(`${count} 件のプレースホルダーを ${outRoot} に生成しました`);

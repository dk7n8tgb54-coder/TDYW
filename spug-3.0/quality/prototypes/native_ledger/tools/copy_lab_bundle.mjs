import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const prototypeRoot = path.resolve(here, "..");
const source = path.join(prototypeRoot, "dist");
const target = path.resolve(prototypeRoot, "..", "..", "..", "spug_web", "public", "lab", "native-ledger");

if (!fs.existsSync(source)) {
  console.error(`未找到原型构建产物：${source}`);
  console.error("请先在 quality/prototypes/native_ledger 下执行 npm run build。");
  process.exit(1);
}

fs.rmSync(target, { recursive: true, force: true });
fs.mkdirSync(target, { recursive: true });
fs.cpSync(source, target, { recursive: true });

const files = fs.readdirSync(target);
console.log(`已复制原型构建产物 -> ${target}`);
console.log(`顶层文件：${files.join(", ")}`);

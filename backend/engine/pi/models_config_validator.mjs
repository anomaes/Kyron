import { realpath } from "node:fs/promises";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const [, , piExecutable, modelsPath] = process.argv;
if (!piExecutable || !modelsPath) {
  throw new Error("Usage: models_config_validator.mjs <pi-executable> <models.json>");
}

const piEntry = await realpath(piExecutable);
const piModule = await import(pathToFileURL(join(dirname(piEntry), "index.js")).href);
const runtime = await piModule.ModelRuntime.create({ modelsPath, allowModelNetwork: false });
const error = runtime.getError();
if (error) {
  console.error(error);
  process.exitCode = 1;
}

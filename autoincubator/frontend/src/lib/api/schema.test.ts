// @vitest-environment node
import { readFile } from "node:fs/promises";

import openapiTS, { astToString } from "openapi-typescript";
import { describe, expect, it } from "vitest";

const spec = new URL("../../../../backend/openapi.json", import.meta.url);
const generated = new URL("./schema.d.ts", import.meta.url);

describe("generated API types", () => {
  it("match backend/openapi.json (run `pnpm gen:api` after changing the API)", async () => {
    const fresh = astToString(await openapiTS(spec));
    const committed = await readFile(generated, "utf8");
    // The CLI only adds a banner comment on top of what the library returns.
    expect(committed.endsWith(fresh)).toBe(true);
  });
});

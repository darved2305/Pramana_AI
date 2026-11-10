import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

for (const failure of ["module", "node"]) {
  test(`microphone tracks stop after ${failure} setup failure and retry works`, async () => {
    const tracks = [{ stopped: 0, stop() { this.stopped++; } }, { stopped: 0, stop() { this.stopped++; } }];
    let fail = true;
    const sent = [];
    const context = {
      exports: {},
      navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => tracks }) } },
      AudioContext: class {
        audioWorklet = { addModule: async () => { if (fail && failure === "module") throw Error("module"); } };
        createMediaStreamSource() { return { connect() {} }; }
      },
      AudioWorkletNode: class {
        constructor() { if (fail && failure === "node") throw Error("node"); }
        port = {};
        disconnect() {}
      },
      WebSocket: { OPEN: 1 },
      setTimeout,
    };
    const source = fs.readFileSync("src/lib/audio/media.ts", "utf8");
    vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
    const session = new context.exports.QuestionMediaSession("inv", "q", "token");
    session.ws = { readyState: 1, send: (data) => sent.push(JSON.parse(data)) };
    await assert.rejects(session.startMic());
    assert.deepEqual(tracks.map((track) => track.stopped), [1, 1]);
    assert.notEqual(session.current, "listening");
    session.tapAnswer("yes");
    assert.equal(sent[0].type, "tap_answer");
    fail = false;
    await session.startMic();
    assert.equal(session.current, "listening");
    session.endTurn();
  });
}

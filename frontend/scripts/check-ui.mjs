import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { build } from "esbuild";
import React from "react";
import { act, create } from "react-test-renderer";
import { useApiTask } from "../src/hooks/useApiTask.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
await mkdir(".checks", { recursive: true });
await build({
  entryPoints: ["src/App.jsx"],
  outfile: ".checks/app.mjs",
  bundle: true,
  platform: "node",
  format: "esm",
  packages: "external",
  loader: { ".css": "empty" },
});
const { default: App } = await import("../.checks/app.mjs");
let app;
await act(() => {
  app = create(React.createElement(App));
});
const component = (name) => app.root.find((node) => node.type?.name === name);
const navigate = async (id) =>
  act(() => component("Sidebar").props.goToPage(id));
const card = () =>
  app.root.findAll((node) => node.type?.name === "PostCard")[0];
const original = card().props.postState[0];
await act(() => card().props.toggleLike(0));
assert.equal(card().props.postState[0].boosts, original.boosts + 1);
await act(() => card().props.toggleLike(0));
assert.equal(card().props.postState[0].boosts, original.boosts);
await act(() => card().props.toggleRepost(0));
assert.equal(card().props.postState[0].reposts, original.reposts + 1);
await act(() => card().props.setCommentDraft(0, "  Merhaba  "));
await act(() => card().props.submitComment(0));
assert.deepEqual(card().props.postState[0].extraComments, ["Merhaba"]);
await act(() => card().props.submitComment(0));
assert.equal(card().props.postState[0].comments, original.comments + 1);
await act(() => component("PostComposer").props.setDraft("Kalıcı taslak"));
for (const id of [
  "messages",
  "settings",
  "notifications",
  "explore",
  "play",
  "communities",
  "saved",
  "likes",
  "teknofest",
  "assistant",
]) {
  await navigate(id);
  assert.ok(app.toJSON());
}
await navigate("messages");
const conversation = {
  name: "Test",
  thread: [{ from: "them", text: "Merhaba" }],
};
await act(() =>
  component("MessagesPage").props.setOpenConversation(conversation),
);
assert.equal(component("MessagesPage").props.openConversation.name, "Test");
await navigate("home");
assert.equal(component("PostComposer").props.draft, "Kalıcı taslak");
assert.deepEqual(card().props.postState[0].extraComments, ["Merhaba"]);
await navigate("messages");
assert.equal(component("MessagesPage").props.openConversation, null);
await navigate("settings");
const toggles = app.root.findAllByProps({ "aria-pressed": true });
assert.ok(toggles.length);
await act(() => toggles[0].props.onClick());
assert.ok(app.root.findAllByProps({ "aria-pressed": false }).length);
for (const id of ["ideas", "setup", "preparing"]) {
  await navigate(id);
  assert.ok(app.toJSON());
}
await navigate("setup");
const category = () => app.root.findByProps({ "data-cat": "araba" });
const wasSelected = category().props["aria-pressed"];
await act(() => category().props.onClick());
assert.equal(category().props["aria-pressed"], !wasSelected);
await navigate("ideas");
await act(() =>
  app.root
    .findByProps({ id: "prompt-input" })
    .props.onChange({ target: { value: "Yeni içerik fikri" } }),
);
await navigate("home");
assert.equal(component("PostComposer").props.draft, "Yeni içerik fikri");
await act(() => app.unmount());
let task;
function TaskProbe() {
  task = useApiTask();
  return null;
}
let probe;
await act(() => {
  probe = create(React.createElement(TaskProbe));
});
let firstResolve, firstSignal, firstRun;
await act(() => {
  firstRun = task.run((signal) => {
    firstSignal = signal;
    return new Promise((resolve) => {
      firstResolve = resolve;
    });
  });
});
await act(async () => {
  await task.run(async () => ({ value: "new result" }));
});
assert.equal(firstSignal.aborted, true);
await act(async () => {
  firstResolve({ value: "stale result" });
  await firstRun;
});
assert.deepEqual(task.data, { value: "new result" });
let lateResolve, lateRun;
await act(() => {
  lateRun = task.run(
    () =>
      new Promise((resolve) => {
        lateResolve = resolve;
      }),
  );
});
await act(() => task.reset());
await act(async () => {
  lateResolve({ value: "cancelled result" });
  await lateRun;
});
assert.equal(task.status, "idle");
assert.equal(task.data, null);
await act(() => probe.unmount());
console.log(
  "PASS: all 14 pages, feed interactions, draft persistence, navigation, theme, interest selection, stale-response protection and cancellation.",
);

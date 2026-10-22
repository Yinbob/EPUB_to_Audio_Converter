import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import { api, send, upload, fileUrl, ApiError } from "../../src/api";
import { createPinia, setActivePinia } from "pinia";
import { useStudio } from "../../src/stores/studio";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("API 边界", () => {
  it("结构化错误保留状态和中文说明", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({
          error: { code: "task_busy", message: "已有任务正在运行。" },
        }),
      }),
    );
    await expect(api("/tasks")).rejects.toMatchObject({
      code: "task_busy",
      status: 409,
      message: "已有任务正在运行。",
    });
  });
  it("上传使用 FormData，不覆盖 multipart 边界", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ id: "file" }) });
    vi.stubGlobal("fetch", fetch);
    await upload(new File(["book"], "book.epub"));
    expect(fetch.mock.calls[0][1].body).toBeInstanceOf(FormData);
    expect(fetch.mock.calls[0][1].headers["Content-Type"]).toBeUndefined();
  });
  it("文件下载地址不接收原始路径", () => {
    expect(fileUrl("registered-id", true)).toBe(
      "/api/v1/files/registered-id?download=true",
    );
  });
  it("JSON 请求使用同源接口", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetch);
    await send("/admin/login", { password: "test" });
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/admin/login");
    expect(fetch.mock.calls[0][1].headers["Content-Type"]).toBe(
      "application/json",
    );
  });
});

describe("任务状态", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
  });
  it("启动响应丢失后重试复用同一个请求 ID", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: "a", status: "starting" }),
      });
    vi.stubGlobal("fetch", fetch);
    const store = useStudio();
    const body: any = { kind: "generate", generation: { file_ids: ["file"] } };
    await expect(store.start(body)).rejects.toThrow("network");
    await store.start(body);
    const first = JSON.parse(fetch.mock.calls[0][1].body),
      second = JSON.parse(fetch.mock.calls[1][1].body);
    expect(first.request_id).toBe(second.request_id);
    expect(store.busy).toBe(true);
    store.dispose();
  });
  it("新会话只显示正在运行的任务", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          current_task: null,
          providers: [],
          settings: {},
        }),
      }),
    );
    const store = useStudio();
    await store.initialize();
    expect(store.progressVisible).toBe(false);
    expect(store.ready).toBe(true);
    store.dispose();
  });
});
